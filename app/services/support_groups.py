"""Peer-led support circles (Daily.co) — member schedule/join; admin for facilitator."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from html import escape

from flask import url_for
from sqlalchemy.orm import joinedload

from ..extensions import db
from ..models import (SUPPORT_CIRCLE_SEED, SupportGroupApplication,
                      SupportGroupCircle, SupportGroupMeeting,
                      SupportGroupTopicAlert, User, utcnow)
from .mailer import send_email
from .social_graph import notify
from .timefmt import format_local, normalize_timezone, to_local
from . import daily as daily_svc

log = logging.getLogger(__name__)

_last_sweep_mono = 0.0
_SWEEP_GAP_SEC = 60

PEER_MEETING_CAP = 8
MAX_OPEN_SESSIONS_PER_CIRCLE = 4
PEER_SCHEDULE_COOLDOWN_DAYS = 14


def peer_meeting_minutes() -> int:
    return daily_svc.meeting_duration_minutes()


def meeting_phase(meeting: SupportGroupMeeting, *, now: datetime | None = None
                  ) -> str:
    """Return ``waiting``, ``live``, ``ended``, or ``unavailable``."""
    if meeting is None or meeting.status != "scheduled" or not meeting.scheduled_at:
        return "unavailable"
    now = now or utcnow()
    start = meeting.scheduled_at
    end = start + timedelta(minutes=peer_meeting_minutes())
    if now < start:
        return "waiting"
    if now >= end:
        return "ended"
    return "live"


def ensure_circles() -> list[SupportGroupCircle]:
    """Seed / backfill the catalogue from SUPPORT_CIRCLE_SEED."""
    existing = {
        c.slug: c for c in SupportGroupCircle.query.all()
    }
    changed = False
    for i, (slug, track, title, blurb, cap, meets, icon) in enumerate(SUPPORT_CIRCLE_SEED):
        if slug in existing:
            continue
        db.session.add(SupportGroupCircle(
            slug=slug, track=track, title=title, blurb=blurb,
            capacity=cap, meets_label=meets, icon=icon,
            sort_order=(i + 1) * 10, active=True,
        ))
        changed = True
    if changed:
        db.session.commit()
    return (SupportGroupCircle.query
            .order_by(SupportGroupCircle.sort_order.asc()).all())


def is_custom_circle(circle: SupportGroupCircle | None) -> bool:
    if circle is None:
        return False
    return (circle.slug or "").startswith("custom-")


def normalize_custom_topic(raw: str | None) -> str:
    """Collapse whitespace for display + overlap matching."""
    text = " ".join((raw or "").strip().split())
    return text[:80]


def custom_topic_key(raw: str | None) -> str:
    return normalize_custom_topic(raw).casefold()


def meeting_display_title(meeting: SupportGroupMeeting) -> str:
    """Circle title, or Custom: {topic} when the host named one."""
    circle = meeting.circle
    base = circle.title if circle else "support group"
    if is_custom_circle(circle):
        topic = normalize_custom_topic(meeting.notes)
        if topic:
            return f"Custom: {topic}"
    return base


def peer_session_time_conflict(
    circle_id: int,
    when: datetime,
    *,
    topic_key: str | None = None,
    exclude_meeting_id: int | None = None,
) -> SupportGroupMeeting | None:
    """Return an overlapping scheduled peer meeting for this topic, if any.

    Fixed topics: any overlapping session on the same circle.
    Custom circles: only when the normalized custom topic name also matches.
    """
    duration = timedelta(minutes=peer_meeting_minutes())
    end = when + duration
    q = (SupportGroupMeeting.query
         .filter(
             SupportGroupMeeting.circle_id == circle_id,
             SupportGroupMeeting.status == "scheduled",
             SupportGroupMeeting.scheduled_at.isnot(None),
             SupportGroupMeeting.kind == "peer",
         ))
    if exclude_meeting_id:
        q = q.filter(SupportGroupMeeting.id != exclude_meeting_id)
    for other in q.all():
        start = other.scheduled_at
        if start is None:
            continue
        other_end = start + duration
        if when >= other_end or end <= start:
            continue
        if topic_key is None:
            return other
        if custom_topic_key(other.notes) == topic_key:
            return other
    return None


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


def user_can_access_circle(user: User | None, circle: SupportGroupCircle) -> bool:
    if not user or not getattr(user, "is_authenticated", True):
        return False
    if not user.is_member() and not user.is_admin:
        return False
    if circle.track == "building":
        return user.has_feature("support_creator")
    if circle.track == "healing":
        return user.has_feature("support_healing")
    return False


def meeting_seat_count(meeting: SupportGroupMeeting) -> int:
    return (SupportGroupApplication.query
            .filter_by(meeting_id=meeting.id, status="selected")
            .count())


def meeting_spots_left(meeting: SupportGroupMeeting) -> int:
    cap = int(meeting.capacity or PEER_MEETING_CAP)
    return max(0, cap - meeting_seat_count(meeting))


def open_peer_sessions(circle_id: int) -> list[SupportGroupMeeting]:
    """Scheduled peer sessions for a topic, soonest first."""
    now = utcnow()
    return (SupportGroupMeeting.query
            .options(joinedload(SupportGroupMeeting.circle),
                     joinedload(SupportGroupMeeting.host))
            .filter(
                SupportGroupMeeting.circle_id == circle_id,
                SupportGroupMeeting.kind == "peer",
                SupportGroupMeeting.status == "scheduled",
                SupportGroupMeeting.scheduled_at.isnot(None),
                SupportGroupMeeting.scheduled_at > now,
            )
            .order_by(SupportGroupMeeting.scheduled_at.asc())
            .all())


def open_peer_session_count(circle_id: int) -> int:
    return (SupportGroupMeeting.query
            .filter(
                SupportGroupMeeting.circle_id == circle_id,
                SupportGroupMeeting.kind == "peer",
                SupportGroupMeeting.status == "scheduled",
                SupportGroupMeeting.scheduled_at.isnot(None),
                SupportGroupMeeting.scheduled_at > utcnow(),
            )
            .count())


def user_selected_on_meeting(user_id: int, meeting_id: int
                             ) -> SupportGroupApplication | None:
    return (SupportGroupApplication.query
            .filter_by(user_id=user_id, meeting_id=meeting_id, status="selected")
            .first())


def user_open_seat_in_circle(user_id: int, circle_id: int
                            ) -> SupportGroupApplication | None:
    row = (SupportGroupApplication.query
           .options(joinedload(SupportGroupApplication.meeting))
           .filter(
               SupportGroupApplication.user_id == user_id,
               SupportGroupApplication.circle_id == circle_id,
               SupportGroupApplication.status == "selected",
           )
           .order_by(SupportGroupApplication.created_at.desc())
           .first())
    if row is None or row.meeting is None:
        return None
    if row.meeting.status not in ("draft", "scheduled"):
        return None
    if (row.meeting.status == "scheduled"
            and row.meeting.scheduled_at
            and row.meeting.scheduled_at <= utcnow()):
        return None
    return row


def last_peer_schedule_at(user_id: int) -> datetime | None:
    row = (SupportGroupMeeting.query
           .filter(
               SupportGroupMeeting.scheduled_by_user_id == user_id,
               SupportGroupMeeting.kind == "peer",
               SupportGroupMeeting.status.in_(("draft", "scheduled", "completed")),
           )
           .order_by(SupportGroupMeeting.created_at.desc())
           .first())
    return row.created_at if row else None


def can_schedule_peer(user: User) -> tuple[bool, str | None]:
    if not user or not user.is_member():
        return False, "Support groups are for Healing, Creator, and Full Bloom members."
    # Owners/admins can schedule freely — no cooldown.
    if getattr(user, "is_admin", False):
        return True, None
    last = last_peer_schedule_at(user.id)
    if last is None:
        return True, None
    unlock = last + timedelta(days=PEER_SCHEDULE_COOLDOWN_DAYS)
    if utcnow() < unlock:
        when = format_local(unlock, "%b %d", tz_name=getattr(user, "timezone", None) or "UTC")
        return False, (
            f"You can schedule another peer session after {when or 'two weeks'} "
            f"(one every {PEER_SCHEDULE_COOLDOWN_DAYS} days)."
        )
    return True, None


def circle_stats() -> list[dict]:
    """Per-circle cards for the public page + Studio overview."""
    out = []
    for c in circles_by_track():
        sessions = open_peer_sessions(c.id)
        open_n = len(sessions)
        joinable = sum(1 for m in sessions if meeting_spots_left(m) > 0)
        out.append({
            "circle": c,
            "open_sessions": open_n,
            "joinable_sessions": joinable,
            "sessions_full": open_n >= MAX_OPEN_SESSIONS_PER_CIRCLE,
            "sessions": sessions,
            "session_seats": {m.id: meeting_seat_count(m) for m in sessions},
            "session_spots": {m.id: meeting_spots_left(m) for m in sessions},
            # Legacy keys used by older Studio occupancy widgets
            "pending": 0,
            "seated": sum(meeting_seat_count(m) for m in sessions),
            "used": sum(meeting_seat_count(m) for m in sessions),
            "spots_left": joinable,
            "full": open_n >= MAX_OPEN_SESSIONS_PER_CIRCLE and joinable == 0,
            "queue": [],
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


def upcoming_for_user(user: User, limit: int = 12) -> list[SupportGroupApplication]:
    """Selected seats on upcoming peer (or facilitator) sessions."""
    rows = (SupportGroupApplication.query
            .options(joinedload(SupportGroupApplication.meeting)
                     .joinedload(SupportGroupMeeting.circle),
                     joinedload(SupportGroupApplication.circle))
            .filter_by(user_id=user.id, status="selected")
            .order_by(SupportGroupApplication.created_at.desc())
            .limit(40)
            .all())
    out = []
    now = utcnow()
    for row in rows:
        m = row.meeting
        if m is None or m.status != "scheduled" or not m.scheduled_at:
            continue
        if m.scheduled_at <= now:
            continue
        out.append(row)
        if len(out) >= limit:
            break
    out.sort(key=lambda r: r.meeting.scheduled_at or now)
    return out


def open_meetings():
    return (SupportGroupMeeting.query
            .options(joinedload(SupportGroupMeeting.circle),
                     joinedload(SupportGroupMeeting.host))
            .filter(SupportGroupMeeting.status.in_(("draft", "scheduled")))
            .order_by(SupportGroupMeeting.created_at.desc())
            .all())


def recent_meetings(limit: int = 20):
    return (SupportGroupMeeting.query
            .options(joinedload(SupportGroupMeeting.circle),
                     joinedload(SupportGroupMeeting.host))
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


def wrap_peers(meeting: SupportGroupMeeting, viewer: User) -> list[User]:
    """Other seated members shown on the post-session wrap page."""
    peers = []
    for seat in meeting_seats(meeting):
        user = seat.author
        if not user or user.deleted_at or user.id == viewer.id:
            continue
        peers.append(user)
    return peers


def pending_count(circle_id: int | None = None) -> int:
    """Legacy waitlist count (peer flow no longer uses pending)."""
    q = SupportGroupApplication.query.filter_by(status="pending")
    if circle_id is not None:
        q = q.filter_by(circle_id=circle_id)
    return q.count()


def user_topic_alert_ids(user_id: int) -> set[int]:
    rows = (SupportGroupTopicAlert.query
            .filter_by(user_id=user_id)
            .all())
    return {r.circle_id for r in rows}


def has_topic_alert(user_id: int, circle_id: int) -> bool:
    return (SupportGroupTopicAlert.query
            .filter_by(user_id=user_id, circle_id=circle_id)
            .first()) is not None


def toggle_topic_alert(user: User, circle_id: int
                       ) -> tuple[bool | None, str | None]:
    """Subscribe/unsubscribe. Returns (now_on, error)."""
    circle = get_circle(circle_id)
    if circle is None or not circle.active:
        return None, "That topic isn’t available."
    if not user_can_access_circle(user, circle):
        return None, "That topic isn’t included in your plan."

    row = (SupportGroupTopicAlert.query
           .filter_by(user_id=user.id, circle_id=circle.id)
           .first())
    if row:
        db.session.delete(row)
        db.session.commit()
        return False, None

    db.session.add(SupportGroupTopicAlert(
        user_id=user.id, circle_id=circle.id, created_at=utcnow(),
    ))
    db.session.commit()
    return True, None


def _meeting_room_url(meeting: SupportGroupMeeting) -> str:
    try:
        return url_for("main.support_session_room", meeting_id=meeting.id)
    except RuntimeError:
        return f"/support-groups/meetings/{meeting.id}/room"


def _circle_browse_url(circle_id: int | None) -> str:
    try:
        base = url_for("main.support_groups_page")
    except RuntimeError:
        base = "/support-groups"
    if circle_id:
        return f"{base}#circle-{circle_id}"
    return base


def schedule_peer_session(
    user: User,
    *,
    circle_id: int,
    date_s: str,
    time_s: str,
    tz_name: str | None = None,
    topic_title: str | None = None,
) -> tuple[SupportGroupMeeting | None, str | None]:
    """Member schedules a peer support session for a topic."""
    ok, err = can_schedule_peer(user)
    if not ok:
        return None, err

    circle = get_circle(circle_id)
    if circle is None or not circle.active:
        return None, "Choose a support group topic."
    if not user_can_access_circle(user, circle):
        if circle.track == "building":
            return None, "Creator accountability groups aren’t included in your plan."
        return None, "Healing peer groups aren’t included in your plan."

    if open_peer_session_count(circle.id) >= MAX_OPEN_SESSIONS_PER_CIRCLE:
        return None, (
            f"{circle.title} already has {MAX_OPEN_SESSIONS_PER_CIRCLE} upcoming "
            "sessions. Join one of those, or try another topic."
        )

    if user_open_seat_in_circle(user.id, circle.id):
        return None, f"You're already booked in an upcoming {circle.title} session."

    when = parse_owner_parts(date_s, time_s, tz_name or getattr(user, "timezone", None))
    if when is None:
        return None, "Pick a date and time for the session."
    if when <= utcnow():
        return None, "Choose a time in the future."

    custom = is_custom_circle(circle)
    topic = normalize_custom_topic(topic_title) if custom else ""
    if custom and not topic:
        return None, "Name your custom topic (what this session is about)."
    topic_key = custom_topic_key(topic) if custom else None

    conflict = peer_session_time_conflict(
        circle.id, when, topic_key=topic_key,
    )
    if conflict is not None:
        label = meeting_display_title(conflict) if custom else circle.title
        return None, (
            f"There’s already a {label} session at that time. "
            "Pick a different time, or join the existing one."
        )

    meeting = SupportGroupMeeting(
        circle_id=circle.id,
        capacity=PEER_MEETING_CAP,
        kind="peer",
        scheduled_by_user_id=user.id,
        status="draft",
        notes=topic if custom else None,
        created_at=utcnow(),
    )
    db.session.add(meeting)
    db.session.flush()

    seat = SupportGroupApplication(
        user_id=user.id,
        circle_id=circle.id,
        meeting_id=meeting.id,
        message="",
        status="selected",
        created_at=utcnow(),
    )
    db.session.add(seat)
    db.session.commit()

    err = schedule_meeting(meeting, scheduled_at=when, owner=user)
    if err:
        # Roll the draft back so the member can try again.
        cancel_meeting(meeting, owner=user, return_to_queue=False)
        return None, err
    return meeting, None


def join_peer_session(user: User, meeting_id: int
                     ) -> tuple[SupportGroupApplication | None, str | None]:
    meeting = db.session.get(SupportGroupMeeting, meeting_id)
    if meeting is None or meeting.kind != "peer" or meeting.status != "scheduled":
        return None, "That session isn’t open to join."
    if not meeting.circle or not meeting.circle.active:
        return None, "That topic isn’t available."
    if not user_can_access_circle(user, meeting.circle):
        return None, "That session isn’t included in your plan."
    if not meeting.scheduled_at or meeting.scheduled_at <= utcnow():
        return None, "That session has already started or ended."
    if meeting_spots_left(meeting) <= 0:
        return None, "That session is full (8 women max)."

    existing = user_selected_on_meeting(user.id, meeting.id)
    if existing:
        return existing, None

    other = user_open_seat_in_circle(user.id, meeting.circle_id)
    if other and other.meeting_id != meeting.id:
        return None, (
            f"You're already booked for another {meeting.circle.title} session. "
            "Leave that one first if you want to switch."
        )

    row = SupportGroupApplication(
        user_id=user.id,
        circle_id=meeting.circle_id,
        meeting_id=meeting.id,
        message="",
        status="selected",
        created_at=utcnow(),
    )
    db.session.add(row)
    db.session.commit()
    _notify_joiner(meeting, user)
    return row, None


def leave_peer_session(user: User, meeting_id: int) -> str | None:
    meeting = db.session.get(SupportGroupMeeting, meeting_id)
    if meeting is None:
        return "Session not found."
    row = user_selected_on_meeting(user.id, meeting.id)
    if row is None:
        return "You're not in that session."

    # Host leaving cancels the whole peer session.
    if meeting.scheduled_by_user_id == user.id and meeting.kind == "peer":
        cancel_meeting(meeting, owner=user, return_to_queue=False)
        return None

    row.status = "cancelled"
    db.session.commit()
    return None


def _notify_joiner(meeting: SupportGroupMeeting, user: User) -> None:
    room = _meeting_room_url(meeting)
    group = _circle_name(meeting)
    when = _when_for(user, meeting.scheduled_at)
    seats = max(0, meeting_seat_count(meeting) - 1)
    note = f"You're in for {group} — {when}."
    notify(user.id, kind="support_group", body=note[:300],
           actor_id=meeting.scheduled_by_user_id, url=room)
    text = (
        f"Hi {user.first_name() or user.public_name()},\n\n"
        f"You've joined {group}.\n\n"
        f"When: {when}\n"
        f"With: up to {PEER_MEETING_CAP - 1} other members "
        f"({seats} already seated)\n"
        f"Join in Bloom Anyway: {room}\n\n"
        f"We'll remind you again 24 hours before.\n\n"
        f"— Bloom Anyway\n"
    )
    html = (
        f"<p>Hi {escape(user.first_name() or user.public_name())},</p>"
        f"<p>You've joined <strong>{escape(group)}</strong>.</p>"
        f"<p><strong>When:</strong> {escape(when)}</p>"
        f"<p><a href=\"{escape(room)}\">Join the session</a></p>"
        f"<p>We'll remind you again 24 hours before.</p>"
        f"<p>— Bloom Anyway</p>"
    )
    try:
        send_email(user.email, f"You're in for {group}", text, html_body=html)
    except Exception:
        log.exception("Support-group join email failed for user %s", user.id)
    db.session.commit()


# --- legacy waitlist helpers (kept for older rows / smoke migration) ---------

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


def apply(user: User, message: str = "", *, circle_id: int | None = None,
          circle_slug: str | None = None
          ) -> tuple[SupportGroupApplication | None, str | None]:
    """Deprecated waitlist apply — peer flow uses schedule/join instead."""
    return None, (
        "Peer circles are join-as-you-go now. Open upcoming sessions on the "
        "Support Groups page, or schedule a new one."
    )


def withdraw(user: User, app_id: int) -> str | None:
    row = db.session.get(SupportGroupApplication, app_id)
    if row is None or row.user_id != user.id:
        return "Application not found."
    if row.status == "selected" and row.meeting_id:
        return leave_peer_session(user, row.meeting_id)
    if row.status != "pending":
        return "Only pending applications can be withdrawn."
    row.status = "cancelled"
    db.session.commit()
    return None


def form_next_meeting(capacity: int, *, circle_id: int | None = None
                      ) -> tuple[SupportGroupMeeting | None, str | None]:
    """Admin-only: create a facilitator-led draft from any leftover waitlist."""
    try:
        capacity = int(capacity)
    except (TypeError, ValueError):
        return None, "Enter how many seats you want."
    if capacity < 2 or capacity > PEER_MEETING_CAP:
        return None, f"Seat count must be between 2 and {PEER_MEETING_CAP}."
    circle = get_circle(circle_id) if circle_id else None
    if circle_id and circle is None:
        return None, "Unknown circle."
    queue = pending_queue(circle_id=circle.id if circle else None, limit=capacity)
    if not queue:
        return None, (
            "No waitlist applicants. Peer sessions are member-scheduled — "
            "use Facilitator booking for guided sessions."
        )
    if circle is None and queue[0].circle_id:
        circle = get_circle(queue[0].circle_id)
    meeting = SupportGroupMeeting(
        circle_id=circle.id if circle else None,
        capacity=capacity, status="draft", kind="facilitator",
        created_at=utcnow(),
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

    # Also block overlapping times when rescheduling an existing peer meeting.
    if (meeting.kind or "peer") == "peer" and meeting.circle_id:
        topic_key = (
            custom_topic_key(meeting.notes)
            if is_custom_circle(meeting.circle) else None
        )
        conflict = peer_session_time_conflict(
            meeting.circle_id,
            scheduled_at,
            topic_key=topic_key,
            exclude_meeting_id=meeting.id,
        )
        if conflict is not None:
            return (
                "There’s already a session for this topic at that time. "
                "Pick a different time."
            )

    title = meeting_display_title(meeting)
    topic = f"Bloom Anyway — {title}"
    try:
        if meeting.zoom_meeting_id:
            updated = daily_svc.update_room(
                meeting.zoom_meeting_id, scheduled_at=scheduled_at,
            )
            if updated is None:
                info = daily_svc.create_room(topic=topic, scheduled_at=scheduled_at)
                meeting.zoom_meeting_id = info.room_name
                meeting.zoom_url = info.room_url
            else:
                if updated.room_url:
                    meeting.zoom_url = updated.room_url
                meeting.zoom_meeting_id = updated.room_name or meeting.zoom_meeting_id
        else:
            info = daily_svc.create_room(topic=topic, scheduled_at=scheduled_at)
            meeting.zoom_meeting_id = info.room_name
            meeting.zoom_url = info.room_url
    except daily_svc.DailyError as exc:
        return str(exc)

    if not (meeting.zoom_url or "").strip():
        return "Daily.co did not return a room URL."

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
        if (meeting.kind or "peer") == "peer":
            notify_topic_watchers(meeting, actor_id=getattr(owner, "id", None))
    return None


def cancel_meeting(meeting: SupportGroupMeeting, *, owner: User | None = None,
                   return_to_queue: bool = False) -> None:
    seats = meeting_seats(meeting)
    was_live = meeting.status == "scheduled" and bool(meeting.booked_notified_at)
    room_name = (meeting.zoom_meeting_id or "").strip()
    meeting.status = "cancelled"
    for row in seats:
        if return_to_queue:
            row.status = "pending"
            row.meeting_id = None
        else:
            row.status = "cancelled"
    db.session.commit()
    if room_name:
        try:
            daily_svc.delete_room(room_name)
        except Exception:
            log.exception("Failed to delete Daily room %s", room_name)
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


def notify_topic_watchers(meeting: SupportGroupMeeting,
                          *, actor_id: int | None = None) -> int:
    """Fan out to members who tapped Notify me on this topic."""
    if not meeting.circle_id:
        return 0
    seated_ids = {
        s.user_id for s in SupportGroupApplication.query
        .filter_by(meeting_id=meeting.id, status="selected").all()
    }
    alerts = (SupportGroupTopicAlert.query
              .options(joinedload(SupportGroupTopicAlert.author))
              .filter_by(circle_id=meeting.circle_id)
              .all())
    group = _circle_name(meeting)
    browse = _circle_browse_url(meeting.circle_id)
    sent = 0
    for alert in alerts:
        user = alert.author
        if not user or user.deleted_at:
            continue
        if user.id in seated_ids:
            continue
        when = _when_for(user, meeting.scheduled_at)
        note = f"New {group} session scheduled — {when}."
        notify(
            user.id,
            kind="support_group_alert",
            body=note[:300],
            actor_id=actor_id,
            url=browse,
        )
        sent += 1
    if sent:
        db.session.commit()
    return sent


def _when_for(user: User, dt: datetime | None) -> str:
    tz = normalize_timezone(getattr(user, "timezone", None)) or "UTC"
    stamp = format_local(dt, "%A, %b %d, %Y at %I:%M %p", tz_name=tz)
    return f"{stamp} ({tz})" if stamp else "the scheduled time"


def _reminder_day_and_timing(
    user: User, scheduled_at: datetime | None, *, now: datetime | None = None,
) -> tuple[str | None, str]:
    """Return (day_word, timing) for reminder copy in the member's timezone.

    day_word is ``today``, ``tomorrow``, or None. timing is a short phrase like
    ``starting soon`` / ``later today`` / ``in about 20 hours``.
    """
    now = now or utcnow()
    if scheduled_at is None:
        return None, "coming up"

    start = scheduled_at
    if start.tzinfo is not None:
        start = start.astimezone(timezone.utc).replace(tzinfo=None)
    ref = now
    if ref.tzinfo is not None:
        ref = ref.astimezone(timezone.utc).replace(tzinfo=None)

    tz = normalize_timezone(getattr(user, "timezone", None)) or "UTC"
    local_now = to_local(ref, tz)
    local_start = to_local(start, tz)
    delta = start - ref
    secs = max(0, int(delta.total_seconds()))

    if local_now is not None and local_start is not None:
        day_delta = (local_start.date() - local_now.date()).days
        if day_delta <= 0:
            day_word = "today"
            timing = "starting soon" if secs <= 90 * 60 else "later today"
            return day_word, timing
        if day_delta == 1:
            hours = max(1, int(round(secs / 3600)))
            return "tomorrow", (
                f"in about {hours} hour{'s' if hours != 1 else ''}"
            )

    if secs <= 90 * 60:
        return None, "starting soon"
    hours = max(1, int(round(secs / 3600)))
    return None, f"in about {hours} hour{'s' if hours != 1 else ''}"


def _circle_name(meeting: SupportGroupMeeting) -> str:
    return meeting_display_title(meeting)


def _notify_seats(meeting: SupportGroupMeeting, *, kind: str,
                  actor_id: int | None = None,
                  seats: list[SupportGroupApplication] | None = None) -> None:
    seats = seats if seats is not None else meeting_seats(meeting)
    others = max(0, len(seats) - 1)
    room = _meeting_room_url(meeting)
    group = _circle_name(meeting)
    browse = _circle_browse_url(meeting.circle_id)

    for row in seats:
        user = row.author
        if not user or user.deleted_at:
            continue
        when = _when_for(user, meeting.scheduled_at)
        join_url = room if kind in ("booked", "updated", "reminder") else browse
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
                f"Join in Bloom Anyway: {room}\n\n"
                f"We'll remind you again 24 hours before.\n\n"
                f"See you there,\n— Bloom Anyway\n"
            )
            html = (
                f"<p>Hi {escape(user.first_name() or user.public_name())},</p>"
                f"<p>You're in for <strong>{escape(group)}</strong>.</p>"
                f"<p><strong>When:</strong> {escape(when)}<br>"
                f"<strong>With:</strong> {others} other "
                f"member{'s' if others != 1 else ''}</p>"
                f"<p><a href=\"{escape(room)}\">Join the session</a></p>"
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
                f"Join in Bloom Anyway: {room}\n\n"
                f"— Bloom Anyway\n"
            )
            html = (
                f"<p>Hi {escape(user.first_name() or user.public_name())},</p>"
                f"<p>Your {escape(group)} details changed.</p>"
                f"<p><strong>When:</strong> {escape(when)}</p>"
                f"<p><a href=\"{escape(room)}\">Join the session</a></p>"
                f"<p>— Bloom Anyway</p>"
            )
        elif kind == "cancelled":
            note = f"Your {group} meeting was cancelled."
            subject = f"{group} cancelled"
            text = (
                f"Hi {user.first_name() or user.public_name()},\n\n"
                f"The {group} you were booked for has been cancelled.\n"
                f"You can join or schedule another session on Support Groups.\n\n"
                f"— Bloom Anyway\n"
            )
            html = None
        elif kind == "cancelled_draft":
            note = f"The {group} session you were seated for was cancelled."
            subject = f"{group} cancelled"
            text = (
                f"Hi {user.first_name() or user.public_name()},\n\n"
                f"The {group} session was cancelled before it went live.\n"
                f"You can join or schedule another on Support Groups.\n\n"
                f"— Bloom Anyway\n"
            )
            html = None
        elif kind == "reminder":
            day_word, timing = _reminder_day_and_timing(
                user, meeting.scheduled_at)
            if day_word:
                note = f"Reminder: {group} {day_word} — {when}."
                subject = f"Reminder: {group} {day_word}"
            else:
                note = f"Reminder: {group} — {when}."
                subject = f"Reminder: {group}"
            text = (
                f"Hi {user.first_name() or user.public_name()},\n\n"
                f"Friendly reminder — your {group} is {timing}.\n\n"
                f"When: {when}\n"
                f"With: {others} other member{'s' if others != 1 else ''}\n"
                f"Join in Bloom Anyway: {room}\n\n"
                f"See you there,\n— Bloom Anyway\n"
            )
            html = (
                f"<p>Hi {escape(user.first_name() or user.public_name())},</p>"
                f"<p>Friendly reminder — your {escape(group)} is "
                f"{escape(timing)}.</p>"
                f"<p><strong>When:</strong> {escape(when)}<br>"
                f"<strong>With:</strong> {others} other "
                f"member{'s' if others != 1 else ''}</p>"
                f"<p><a href=\"{escape(room)}\">Join the session</a></p>"
                f"<p>See you there,<br>— Bloom Anyway</p>"
            )
        else:
            continue

        notify(user.id, kind="support_group", body=note[:300],
               actor_id=actor_id, url=join_url)
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
