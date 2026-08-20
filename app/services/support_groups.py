"""Named peer circles (Zoom) — apply, seat, schedule, remind."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from html import escape

from sqlalchemy.orm import joinedload

from ..extensions import db
from ..models import (SUPPORT_CIRCLE_SEED, SupportGroupApplication,
                      SupportGroupCircle, SupportGroupMeeting, User, utcnow)
from .mailer import send_email
from .social_graph import notify
from .timefmt import format_local, normalize_timezone
from . import zoom as zoom_svc

log = logging.getLogger(__name__)

_last_sweep_mono = 0.0
_SWEEP_GAP_SEC = 60


def ensure_circles() -> list[SupportGroupCircle]:
    """Seed the catalogue if the table is empty (dev / smoke / fresh DB)."""
    rows = (SupportGroupCircle.query
            .order_by(SupportGroupCircle.sort_order.asc()).all())
    if rows:
        return rows
    for i, (slug, track, title, blurb, cap, meets, icon) in enumerate(SUPPORT_CIRCLE_SEED):
        db.session.add(SupportGroupCircle(
            slug=slug, track=track, title=title, blurb=blurb,
            capacity=cap, meets_label=meets, icon=icon,
            sort_order=(i + 1) * 10, active=True,
        ))
    db.session.commit()
    return (SupportGroupCircle.query
            .order_by(SupportGroupCircle.sort_order.asc()).all())


def circles_by_track(track: str | None = None) -> list[SupportGroupCircle]:
    ensure_circles()
    q = SupportGroupCircle.query.filter_by(active=True)
    if track:
        q = q.filter_by(track=track)
    return q.order_by(SupportGroupCircle.sort_order.asc()).all()


def get_circle(circle_id: int | None = None, *, slug: str | None = None
               ) -> SupportGroupCircle | None:
    ensure_circles()
    if circle_id:
        return db.session.get(SupportGroupCircle, circle_id)
    if slug:
        return SupportGroupCircle.query.filter_by(slug=slug).first()
    return None


def active_application(user_id: int, circle_id: int | None = None
                       ) -> SupportGroupApplication | None:
    q = (SupportGroupApplication.query
         .options(joinedload(SupportGroupApplication.meeting),
                  joinedload(SupportGroupApplication.circle))
         .filter(
             SupportGroupApplication.user_id == user_id,
             SupportGroupApplication.status.in_(("pending", "selected")),
         ))
    if circle_id is not None:
        q = q.filter(SupportGroupApplication.circle_id == circle_id)
    row = q.order_by(SupportGroupApplication.created_at.desc()).first()
    if row is None:
        return None
    if row.status == "selected" and row.meeting is not None:
        if row.meeting.status in ("completed", "cancelled"):
            return None
    return row


def pending_queue(circle_id: int | None = None, limit: int = 200):
    q = (SupportGroupApplication.query
         .options(joinedload(SupportGroupApplication.author),
                  joinedload(SupportGroupApplication.circle))
         .filter_by(status="pending"))
    if circle_id is not None:
        q = q.filter_by(circle_id=circle_id)
    return q.order_by(SupportGroupApplication.created_at.asc()).limit(limit).all()


def pending_count(circle_id: int | None = None) -> int:
    q = SupportGroupApplication.query.filter_by(status="pending")
    if circle_id is not None:
        q = q.filter_by(circle_id=circle_id)
    return q.count()


def seated_open_count(circle_id: int) -> int:
    """Selected seats on draft/scheduled meetings for a circle."""
    return (SupportGroupApplication.query
            .join(SupportGroupMeeting)
            .filter(
                SupportGroupApplication.circle_id == circle_id,
                SupportGroupApplication.status == "selected",
                SupportGroupMeeting.status.in_(("draft", "scheduled")),
            )
            .count())


def spots_left(circle: SupportGroupCircle) -> int:
    """Open seats on the current draft/scheduled meeting cohort."""
    return max(0, int(circle.capacity) - seated_open_count(circle.id))


def circle_stats() -> list[dict]:
    """Per-circle occupancy for Studio + public page cards."""
    out = []
    for c in circles_by_track():
        pending = pending_count(c.id)
        seated = seated_open_count(c.id)
        left = max(0, c.capacity - seated)
        queue = pending_queue(circle_id=c.id, limit=40)
        out.append({
            "circle": c,
            "pending": pending,
            "seated": seated,
            "used": seated,
            "spots_left": left,
            "full": left <= 0,
            "queue": queue,
        })
    return out


def applications_for(user_id: int, limit: int = 12):
    return (SupportGroupApplication.query
            .options(joinedload(SupportGroupApplication.meeting),
                     joinedload(SupportGroupApplication.circle))
            .filter_by(user_id=user_id)
            .order_by(SupportGroupApplication.created_at.desc())
            .limit(limit)
            .all())


def open_meetings():
    return (SupportGroupMeeting.query
            .options(joinedload(SupportGroupMeeting.circle))
            .filter(SupportGroupMeeting.status.in_(("draft", "scheduled")))
            .order_by(SupportGroupMeeting.created_at.desc())
            .all())


def recent_meetings(limit: int = 20):
    return (SupportGroupMeeting.query
            .options(joinedload(SupportGroupMeeting.circle))
            .filter(SupportGroupMeeting.status.in_(("completed", "cancelled")))
            .order_by(SupportGroupMeeting.created_at.desc())
            .limit(limit)
            .all())


def meeting_seats(meeting: SupportGroupMeeting):
    return (SupportGroupApplication.query
            .options(joinedload(SupportGroupApplication.author))
            .filter_by(meeting_id=meeting.id, status="selected")
            .order_by(SupportGroupApplication.created_at.asc())
            .all())


def apply(user: User, message: str = "", *, circle_id: int | None = None,
          circle_slug: str | None = None
          ) -> tuple[SupportGroupApplication | None, str | None]:
    if not user or not user.is_member():
        return None, "Support groups are for Healing, Creator, and Full Bloom members."
    circle = get_circle(circle_id, slug=circle_slug)
    if circle is None or not circle.active:
        return None, "Choose a support group circle."
    if circle.track == "building" and not user.has_feature("support_creator"):
        return None, "Creator accountability groups aren’t included in your plan."
    if circle.track == "healing" and not user.has_feature("support_healing"):
        return None, "Healing peer groups aren’t included in your plan."
    if active_application(user.id, circle.id):
        return None, f"You're already in the queue (or booked) for {circle.title}."
    body = (message or "").strip()
    if len(body) > 2000:
        return None, "Keep your note under 2,000 characters."
    row = SupportGroupApplication(
        user_id=user.id, circle_id=circle.id, message=body,
        status="pending", created_at=utcnow(),
    )
    db.session.add(row)
    db.session.commit()
    return row, None


def withdraw(user: User, app_id: int) -> str | None:
    row = db.session.get(SupportGroupApplication, app_id)
    if row is None or row.user_id != user.id:
        return "Application not found."
    if row.status != "pending":
        return "Only pending applications can be withdrawn."
    row.status = "cancelled"
    db.session.commit()
    return None


def form_next_meeting(capacity: int, *, circle_id: int | None = None
                      ) -> tuple[SupportGroupMeeting | None, str | None]:
    try:
        capacity = int(capacity)
    except (TypeError, ValueError):
        return None, "Enter how many seats you want."
    if capacity < 2 or capacity > 40:
        return None, "Seat count must be between 2 and 40."
    circle = get_circle(circle_id) if circle_id else None
    if circle_id and circle is None:
        return None, "Unknown circle."
    # Prefer seating from the named circle; fall back to global queue for legacy.
    queue = pending_queue(circle_id=circle.id if circle else None, limit=capacity)
    if not queue:
        return None, "No pending applicants yet."
    if circle is None and queue[0].circle_id:
        circle = get_circle(queue[0].circle_id)
    meeting = SupportGroupMeeting(
        circle_id=circle.id if circle else None,
        capacity=capacity, status="draft", created_at=utcnow(),
    )
    db.session.add(meeting)
    db.session.flush()
    for row in queue:
        row.status = "selected"
        row.meeting_id = meeting.id
        if circle and not row.circle_id:
            row.circle_id = circle.id
    db.session.commit()
    return meeting, None


def parse_owner_local(dt_local: str, tz_name: str | None) -> datetime | None:
    """Parse ``YYYY-MM-DDTHH:MM`` from the owner's calendar in their timezone → UTC naive."""
    raw = (dt_local or "").strip()
    if not raw:
        return None
    try:
        if len(raw) == 16:
            local = datetime.strptime(raw, "%Y-%m-%dT%H:%M")
        else:
            local = datetime.fromisoformat(raw)
    except ValueError:
        return None
    tz = normalize_timezone(tz_name) or "UTC"
    from zoneinfo import ZoneInfo
    aware = local.replace(tzinfo=ZoneInfo(tz))
    return aware.astimezone(timezone.utc).replace(tzinfo=None)


def parse_owner_parts(date_s: str, time_s: str, tz_name: str | None) -> datetime | None:
    d = (date_s or "").strip()
    t = (time_s or "").strip()
    if not d or not t:
        return None
    if len(t) == 5:
        t = t + ":00"
    return parse_owner_local(f"{d}T{t[:8]}", tz_name)


def schedule_meeting(meeting: SupportGroupMeeting, *, scheduled_at: datetime,
                     owner: User | None = None) -> str | None:
    if scheduled_at is None:
        return "Pick a date and time."
    if scheduled_at <= utcnow():
        return "Choose a time in the future."

    title = meeting.circle.title if meeting.circle else "support group"
    topic = f"Bloom Anyway — {title}"
    try:
        if meeting.zoom_meeting_id:
            updated = zoom_svc.update_meeting(
                meeting.zoom_meeting_id, topic=topic, scheduled_at=scheduled_at,
            )
            if updated is None:
                info = zoom_svc.create_meeting(topic=topic, scheduled_at=scheduled_at)
                meeting.zoom_meeting_id = info.meeting_id
                meeting.zoom_url = info.join_url
            elif updated.join_url:
                meeting.zoom_url = updated.join_url
        else:
            info = zoom_svc.create_meeting(topic=topic, scheduled_at=scheduled_at)
            meeting.zoom_meeting_id = info.meeting_id
            meeting.zoom_url = info.join_url
    except zoom_svc.ZoomError as exc:
        return str(exc)

    if not (meeting.zoom_url or "").strip():
        return "Zoom did not return a join link."

    was_scheduled = meeting.status == "scheduled" and meeting.booked_notified_at
    meeting.scheduled_at = scheduled_at
    meeting.status = "scheduled"
    db.session.commit()
    if was_scheduled:
        _notify_seats(meeting, kind="updated", actor_id=getattr(owner, "id", None))
    else:
        _notify_seats(meeting, kind="booked", actor_id=getattr(owner, "id", None))
        meeting.booked_notified_at = utcnow()
        db.session.commit()
    return None


def cancel_meeting(meeting: SupportGroupMeeting, *, owner: User | None = None,
                   return_to_queue: bool = True) -> None:
    seats = meeting_seats(meeting)
    was_live = meeting.status == "scheduled" and bool(meeting.booked_notified_at)
    zoom_id = (meeting.zoom_meeting_id or "").strip()
    meeting.status = "cancelled"
    for row in seats:
        if return_to_queue:
            row.status = "pending"
            row.meeting_id = None
        else:
            row.status = "cancelled"
    db.session.commit()
    if zoom_id:
        try:
            zoom_svc.delete_meeting(zoom_id)
        except Exception:
            log.exception("Failed to delete Zoom meeting %s", zoom_id)
    if seats:
        _notify_seats(
            meeting,
            kind="cancelled" if was_live else "cancelled_draft",
            actor_id=getattr(owner, "id", None),
            seats=seats,
        )


def complete_meeting(meeting: SupportGroupMeeting) -> None:
    meeting.status = "completed"
    for row in meeting_seats(meeting):
        row.status = "attended"
    db.session.commit()


def _when_for(user: User, dt: datetime | None) -> str:
    tz = normalize_timezone(getattr(user, "timezone", None)) or "UTC"
    stamp = format_local(dt, "%A, %b %d, %Y at %I:%M %p", tz_name=tz)
    return f"{stamp} ({tz})" if stamp else "the scheduled time"


def _circle_name(meeting: SupportGroupMeeting) -> str:
    if meeting.circle:
        return meeting.circle.title
    return "support group"


def _notify_seats(meeting: SupportGroupMeeting, *, kind: str,
                  actor_id: int | None = None,
                  seats: list[SupportGroupApplication] | None = None) -> None:
    seats = seats if seats is not None else meeting_seats(meeting)
    others = max(0, len(seats) - 1)
    zoom = (meeting.zoom_url or "").strip()
    group = _circle_name(meeting)

    for row in seats:
        user = row.author
        if not user or user.deleted_at:
            continue
        when = _when_for(user, meeting.scheduled_at)
        if kind == "booked":
            note = (
                f"You're booked for {group} with "
                f"{others} other{'s' if others != 1 else ''} — {when}."
            )
            subject = f"You're booked for {group}"
            text = (
                f"Hi {user.first_name() or user.public_name()},\n\n"
                f"You're in for {group}.\n\n"
                f"When: {when}\n"
                f"With: {others} other member{'s' if others != 1 else ''}\n"
                f"Zoom: {zoom}\n\n"
                f"We'll remind you again 24 hours before.\n\n"
                f"See you there,\n— Bloom Anyway\n"
            )
            html = (
                f"<p>Hi {escape(user.first_name() or user.public_name())},</p>"
                f"<p>You're in for <strong>{escape(group)}</strong>.</p>"
                f"<p><strong>When:</strong> {escape(when)}<br>"
                f"<strong>With:</strong> {others} other "
                f"member{'s' if others != 1 else ''}<br>"
                f"<strong>Zoom:</strong> <a href=\"{escape(zoom)}\">{escape(zoom)}</a></p>"
                f"<p>We'll remind you again 24 hours before.</p>"
                f"<p>— Bloom Anyway</p>"
            )
        elif kind == "updated":
            note = f"Your {group} was rescheduled — {when}."
            subject = f"{group} time updated"
            text = (
                f"Hi {user.first_name() or user.public_name()},\n\n"
                f"Your {group} details changed.\n\n"
                f"When: {when}\n"
                f"With: {others} other member{'s' if others != 1 else ''}\n"
                f"Zoom: {zoom}\n\n"
                f"— Bloom Anyway\n"
            )
            html = (
                f"<p>Hi {escape(user.first_name() or user.public_name())},</p>"
                f"<p>Your {escape(group)} details changed.</p>"
                f"<p><strong>When:</strong> {escape(when)}<br>"
                f"<strong>Zoom:</strong> <a href=\"{escape(zoom)}\">{escape(zoom)}</a></p>"
                f"<p>— Bloom Anyway</p>"
            )
        elif kind == "cancelled":
            note = (
                f"Your {group} meeting was cancelled. "
                "You're back on the waiting list with your original place."
            )
            subject = f"{group} cancelled"
            text = (
                f"Hi {user.first_name() or user.public_name()},\n\n"
                f"The {group} you were booked for has been cancelled.\n"
                f"You're back on the waiting list — no need to re-apply, and you "
                f"keep your place ahead of anyone who applied after you.\n\n"
                f"— Bloom Anyway\n"
            )
            html = None
        elif kind == "cancelled_draft":
            note = (
                f"The {group} circle you were seated for was cancelled. "
                "You're back on the waiting list with your original place."
            )
            subject = f"{group} cancelled"
            text = (
                f"Hi {user.first_name() or user.public_name()},\n\n"
                f"The {group} circle you were seated for has been cancelled "
                f"before a date was set.\n"
                f"You're back on the waiting list — no need to re-apply.\n\n"
                f"— Bloom Anyway\n"
            )
            html = None
        elif kind == "reminder":
            note = f"Reminder: {group} tomorrow — {when}."
            subject = f"Reminder: {group} in 24 hours"
            text = (
                f"Hi {user.first_name() or user.public_name()},\n\n"
                f"Friendly reminder — your {group} is in about 24 hours.\n\n"
                f"When: {when}\n"
                f"With: {others} other member{'s' if others != 1 else ''}\n"
                f"Zoom: {zoom}\n\n"
                f"See you there,\n— Bloom Anyway\n"
            )
            html = (
                f"<p>Hi {escape(user.first_name() or user.public_name())},</p>"
                f"<p>Friendly reminder — your {escape(group)} is in about 24 hours.</p>"
                f"<p><strong>When:</strong> {escape(when)}<br>"
                f"<strong>With:</strong> {others} other "
                f"member{'s' if others != 1 else ''}<br>"
                f"<strong>Zoom:</strong> <a href=\"{escape(zoom)}\">{escape(zoom)}</a></p>"
                f"<p>See you there,<br>— Bloom Anyway</p>"
            )
        else:
            continue

        notify(user.id, kind="support_group", body=note[:300],
               actor_id=actor_id)
        try:
            send_email(user.email, subject, text, html_body=html)
        except Exception:
            log.exception("Support-group email failed for user %s", user.id)
    db.session.commit()


def due_reminders(now: datetime | None = None):
    now = now or utcnow()
    window_end = now + timedelta(hours=24)
    return (SupportGroupMeeting.query
            .filter(
                SupportGroupMeeting.status == "scheduled",
                SupportGroupMeeting.reminded_at.is_(None),
                SupportGroupMeeting.scheduled_at.isnot(None),
                SupportGroupMeeting.scheduled_at > now,
                SupportGroupMeeting.scheduled_at <= window_end,
            )
            .all())


def dispatch_due_reminders(now: datetime | None = None) -> int:
    meetings = due_reminders(now=now)
    sent = 0
    for meeting in meetings:
        _notify_seats(meeting, kind="reminder")
        meeting.reminded_at = utcnow()
        db.session.commit()
        sent += 1
    return sent


def maybe_sweep_reminders(force: bool = False) -> int:
    global _last_sweep_mono
    now_mono = time.monotonic()
    if not force and (now_mono - _last_sweep_mono) < _SWEEP_GAP_SEC:
        return 0
    _last_sweep_mono = now_mono
    try:
        return dispatch_due_reminders()
    except Exception:
        log.exception("Support-group reminder sweep failed")
        try:
            db.session.rollback()
        except Exception:
            pass
        return 0
