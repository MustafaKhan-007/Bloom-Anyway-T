"""Coaching / support-group circles (Zoom) — apply, seat, schedule, remind."""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timedelta, timezone
from html import escape
from urllib.parse import urlparse

from flask import url_for
from sqlalchemy.orm import joinedload

from ..extensions import db
from ..models import SupportGroupApplication, SupportGroupMeeting, User, utcnow
from .mailer import send_email
from .social_graph import notify
from .timefmt import format_local, normalize_timezone

log = logging.getLogger(__name__)

ZOOM_HOSTS = ("zoom.us", "www.zoom.us", "us02web.zoom.us", "us04web.zoom.us",
              "us05web.zoom.us", "us06web.zoom.us")

# Throttle lazy reminder sweeps across workers/requests.
_last_sweep_mono = 0.0
_SWEEP_GAP_SEC = 60


def active_application(user_id: int) -> SupportGroupApplication | None:
    """Pending, or selected for a draft/scheduled meeting."""
    row = (SupportGroupApplication.query
           .options(joinedload(SupportGroupApplication.meeting))
           .filter(
               SupportGroupApplication.user_id == user_id,
               SupportGroupApplication.status.in_(("pending", "selected")),
           )
           .order_by(SupportGroupApplication.created_at.desc())
           .first())
    if row is None:
        return None
    if row.status == "selected" and row.meeting is not None:
        if row.meeting.status in ("completed", "cancelled"):
            return None
    return row


def pending_queue(limit: int = 200):
    return (SupportGroupApplication.query
            .options(joinedload(SupportGroupApplication.author))
            .filter_by(status="pending")
            .order_by(SupportGroupApplication.created_at.asc())
            .limit(limit)
            .all())


def pending_count() -> int:
    return SupportGroupApplication.query.filter_by(status="pending").count()


def applications_for(user_id: int, limit: int = 12):
    return (SupportGroupApplication.query
            .options(joinedload(SupportGroupApplication.meeting))
            .filter_by(user_id=user_id)
            .order_by(SupportGroupApplication.created_at.desc())
            .limit(limit)
            .all())


def open_meetings():
    return (SupportGroupMeeting.query
            .filter(SupportGroupMeeting.status.in_(("draft", "scheduled")))
            .order_by(SupportGroupMeeting.created_at.desc())
            .all())


def recent_meetings(limit: int = 20):
    return (SupportGroupMeeting.query
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


def apply(user: User, message: str = "") -> tuple[SupportGroupApplication | None, str | None]:
    if not user or not user.is_member():
        return None, "Support groups are for Healing and Creator members."
    if active_application(user.id):
        return None, "You're already in the queue (or booked) for a support group."
    body = (message or "").strip()
    if len(body) > 2000:
        return None, "Keep your note under 2,000 characters."
    row = SupportGroupApplication(
        user_id=user.id, message=body, status="pending", created_at=utcnow(),
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


def form_next_meeting(capacity: int) -> tuple[SupportGroupMeeting | None, str | None]:
    try:
        capacity = int(capacity)
    except (TypeError, ValueError):
        return None, "Enter how many seats you want."
    if capacity < 2 or capacity > 40:
        return None, "Seat count must be between 2 and 40."
    queue = pending_queue(limit=capacity)
    if not queue:
        return None, "No pending applicants yet."
    meeting = SupportGroupMeeting(
        capacity=capacity, status="draft", created_at=utcnow(),
    )
    db.session.add(meeting)
    db.session.flush()
    for row in queue:
        row.status = "selected"
        row.meeting_id = meeting.id
    db.session.commit()
    return meeting, None


def _valid_zoom_url(raw: str) -> str | None:
    url = (raw or "").strip()
    if not url or len(url) > 500:
        return None
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    host = (parsed.hostname or "").lower()
    if not host:
        return None
    if host in ZOOM_HOSTS or host.endswith(".zoom.us"):
        return url
    # Allow other https meeting hosts the owner pastes (Meet, etc.)
    if parsed.scheme in ("http", "https") and "." in host:
        return url
    return None


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
    """Parse separate date + time fields (``YYYY-MM-DD`` + ``HH:MM``) → UTC naive."""
    d = (date_s or "").strip()
    t = (time_s or "").strip()
    if not d or not t:
        return None
    if len(t) == 5:
        t = t + ":00"
    return parse_owner_local(f"{d}T{t[:8]}", tz_name)


def schedule_meeting(meeting: SupportGroupMeeting, *, scheduled_at: datetime,
                     zoom_url: str, owner: User | None = None
                     ) -> str | None:
    zoom = _valid_zoom_url(zoom_url)
    if not zoom:
        return "Paste a valid Zoom (or meeting) link."
    if scheduled_at is None:
        return "Pick a date and time."
    if scheduled_at <= utcnow():
        return "Choose a time in the future."
    was_scheduled = meeting.status == "scheduled" and meeting.booked_notified_at
    meeting.scheduled_at = scheduled_at
    meeting.zoom_url = zoom
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
    was_live = meeting.status == "scheduled" and meeting.booked_notified_at
    meeting.status = "cancelled"
    for row in seats:
        if return_to_queue and not was_live:
            row.status = "pending"
            row.meeting_id = None
        else:
            row.status = "cancelled"
    db.session.commit()
    if was_live:
        _notify_seats(meeting, kind="cancelled", actor_id=getattr(owner, "id", None),
                      seats=seats)


def complete_meeting(meeting: SupportGroupMeeting) -> None:
    meeting.status = "completed"
    for row in meeting_seats(meeting):
        row.status = "attended"
    db.session.commit()


def _when_for(user: User, dt: datetime | None) -> str:
    tz = normalize_timezone(getattr(user, "timezone", None)) or "UTC"
    stamp = format_local(dt, "%A, %b %d, %Y at %I:%M %p", tz_name=tz)
    return f"{stamp} ({tz})" if stamp else "the scheduled time"


def _account_url() -> str:
    try:
        return url_for("main.account", _external=True) + "#support-groups"
    except RuntimeError:
        return "/account#support-groups"


def _notify_seats(meeting: SupportGroupMeeting, *, kind: str,
                  actor_id: int | None = None,
                  seats: list[SupportGroupApplication] | None = None) -> None:
    seats = seats if seats is not None else meeting_seats(meeting)
    others = max(0, len(seats) - 1)
    zoom = (meeting.zoom_url or "").strip()
    href = _account_url()

    for row in seats:
        user = row.author
        if not user or user.deleted_at:
            continue
        when = _when_for(user, meeting.scheduled_at)
        if kind == "booked":
            note = (
                f"You're booked for a Bloom Anyway support group with "
                f"{others} other{'s' if others != 1 else ''} — {when}."
            )
            subject = "You're booked for a support group"
            text = (
                f"Hi {user.first_name() or user.public_name()},\n\n"
                f"You're in for the next coaching / support group circle.\n\n"
                f"When: {when}\n"
                f"With: {others} other member{'s' if others != 1 else ''}\n"
                f"Zoom: {zoom}\n\n"
                f"We'll remind you again 24 hours before.\n\n"
                f"See you there,\n— Bloom Anyway\n"
            )
            html = (
                f"<p>Hi {escape(user.first_name() or user.public_name())},</p>"
                f"<p>You're in for the next coaching / support group circle.</p>"
                f"<p><strong>When:</strong> {escape(when)}<br>"
                f"<strong>With:</strong> {others} other "
                f"member{'s' if others != 1 else ''}<br>"
                f"<strong>Zoom:</strong> <a href=\"{escape(zoom)}\">{escape(zoom)}</a></p>"
                f"<p>We'll remind you again 24 hours before.</p>"
                f"<p>— Bloom Anyway</p>"
            )
        elif kind == "updated":
            note = f"Your support group was rescheduled — {when}."
            subject = "Support group time updated"
            text = (
                f"Hi {user.first_name() or user.public_name()},\n\n"
                f"Your support group details changed.\n\n"
                f"When: {when}\n"
                f"With: {others} other member{'s' if others != 1 else ''}\n"
                f"Zoom: {zoom}\n\n"
                f"— Bloom Anyway\n"
            )
            html = (
                f"<p>Hi {escape(user.first_name() or user.public_name())},</p>"
                f"<p>Your support group details changed.</p>"
                f"<p><strong>When:</strong> {escape(when)}<br>"
                f"<strong>Zoom:</strong> <a href=\"{escape(zoom)}\">{escape(zoom)}</a></p>"
                f"<p>— Bloom Anyway</p>"
            )
        elif kind == "cancelled":
            note = "Your support group meeting was cancelled. You can re-apply anytime."
            subject = "Support group cancelled"
            text = (
                f"Hi {user.first_name() or user.public_name()},\n\n"
                f"The support group you were booked for has been cancelled.\n"
                f"You're welcome to apply again from My space whenever you're ready.\n\n"
                f"— Bloom Anyway\n"
            )
            html = None
        elif kind == "reminder":
            note = f"Reminder: support group tomorrow — {when}."
            subject = "Reminder: support group in 24 hours"
            text = (
                f"Hi {user.first_name() or user.public_name()},\n\n"
                f"Friendly reminder — your Bloom Anyway support group is in about 24 hours.\n\n"
                f"When: {when}\n"
                f"With: {others} other member{'s' if others != 1 else ''}\n"
                f"Zoom: {zoom}\n\n"
                f"See you there,\n— Bloom Anyway\n"
            )
            html = (
                f"<p>Hi {escape(user.first_name() or user.public_name())},</p>"
                f"<p>Friendly reminder — your support group is in about 24 hours.</p>"
                f"<p><strong>When:</strong> {escape(when)}<br>"
                f"<strong>With:</strong> {others} other "
                f"member{'s' if others != 1 else ''}<br>"
                f"<strong>Zoom:</strong> <a href=\"{escape(zoom)}\">{escape(zoom)}</a></p>"
                f"<p>See you there,<br>— Bloom Anyway</p>"
            )
        else:
            continue

        notify(user.id, kind="support_group", body=note[:300],
               actor_id=actor_id, url=href)
        try:
            send_email(user.email, subject, text, html_body=html)
        except Exception:
            log.exception("Support-group email failed for user %s", user.id)
    db.session.commit()


def due_reminders(now: datetime | None = None):
    """Meetings whose 24h reminder window has opened and not yet sent."""
    now = now or utcnow()
    window_end = now + timedelta(hours=24)
    # Remind when we're inside ~24h before start (and not after start).
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
    """Cheap throttle for before_request / page hits."""
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
