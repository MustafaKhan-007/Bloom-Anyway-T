"""Home-page spotlight: Creator of the Month and Reel of the Week.

Both slots are the owner's own pick — Creator of the Month is drawn from the
Creator members who put an Instagram link on their Bloom Anyway profile, and
Reel of the Week is whatever reel she found that week. Neither is an
application queue; that's Reel reviews, which is a separate feature.

Each slot carries a run-until date so a stale card doesn't sit on the home page
forever, and owners get a Bloom Anyway notification a day before one runs out.
"""
import logging
import random
import time
from datetime import date, timedelta

from ..models import User
from .settings import get_setting, set_setting
from .social import instagram_from_links, instagram_profile_url

log = logging.getLogger(__name__)

#: how long a fresh pick runs for by default
CREATOR_RUN_DAYS = 30
REEL_RUN_DAYS = 7
#: how long before the end date owners get the heads-up
NOTICE_DAYS = 1

_SWEEP_GAP_SEC = 3600
_last_sweep_mono = 0.0


def _parse_date(raw: str | None) -> date | None:
    text = (raw or "").strip()[:10]
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def default_end(kind: str, start: date | None = None) -> date:
    """The date a freshly saved slot should run until."""
    days = CREATOR_RUN_DAYS if kind == "creator" else REEL_RUN_DAYS
    return (start or date.today()) + timedelta(days=days)


def slot_state(kind: str, today: date | None = None) -> dict:
    """Status of one spotlight slot for Studio and the expiry sweep."""
    today = today or date.today()
    if kind == "creator":
        label = "Creator of the month"
        who = (get_setting("creator_name") or "").strip()
        ends = _parse_date(get_setting("creator_expires"))
    else:
        label = "Reel of the week"
        who = (get_setting("reel_url") or "").strip()
        ends = _parse_date(get_setting("reel_expires"))
    days_left = (ends - today).days if ends else None
    return {
        "kind": kind,
        "label": label,
        "filled": bool(who),
        "subject": who,
        "ends": ends,
        "days_left": days_left,
        "expired": bool(ends and days_left is not None and days_left < 0),
        "ending_soon": bool(ends and days_left is not None
                            and 0 <= days_left <= NOTICE_DAYS),
    }


def spotlight_slots(today: date | None = None) -> list[dict]:
    return [slot_state("creator", today), slot_state("reel", today)]


# --- who can be featured -----------------------------------------------------

def eligible_creators() -> list[dict]:
    """Creator-tier members who linked Instagram on their Bloom Anyway profile.

    These are the only people who can be Creator of the Month, so this is the
    list the random pick draws from.
    """
    rows = (User.query
            .filter(User.deleted_at.is_(None),
                    User.is_admin.is_(False),
                    User.membership.in_(("creator", "full_bloom")))
            .order_by(User.display_name, User.username)
            .all())
    out = []
    for u in rows:
        handle = instagram_from_links(u.links())
        out.append({
            "user_id": u.id,
            "name": u.public_name(),
            "email": u.email,
            "username": u.username or "",
            "tier": u.membership_label(),
            "handle": handle,
            "profile_url": instagram_profile_url(handle) if handle else "",
            "bio": (u.bio or "").strip(),
            "has_photo": bool(u.avatar_mime or (u.avatar_url or "").strip()),
        })
    return out


def eligible_split() -> tuple[list[dict], list[dict]]:
    """``(ready, missing_instagram)`` — the two halves of the Creator list."""
    ready, missing = [], []
    for row in eligible_creators():
        (ready if row["handle"] else missing).append(row)
    return ready, missing


def pick_random_creator(exclude_handle: str = "") -> dict | None:
    """Draw one eligible Creator member at random, skipping the current pick."""
    ready, _missing = eligible_split()
    if not ready:
        return None
    current = (exclude_handle or "").strip().lstrip("@").lower()
    pool = [c for c in ready if c["handle"].lower() != current] or ready
    return random.choice(pool)


def candidate(user_id: int) -> dict | None:
    for row in eligible_creators():
        if row["user_id"] == int(user_id):
            return row
    return None


# --- expiry notices ----------------------------------------------------------

def _notified_key(kind: str) -> str:
    return f"spotlight_{kind}_notified"


def mark_slot_saved(kind: str, *, filled: bool, end: date | None) -> None:
    """Record a slot's run-until date and re-arm its expiry notice."""
    key = "creator_expires" if kind == "creator" else "reel_expires"
    set_setting(key, end.isoformat() if (filled and end) else "")
    set_setting(_notified_key(kind), "")


def sweep_expiry_notices(today: date | None = None) -> int:
    """Notify owners a day before a spotlight slot runs out."""
    from flask import url_for

    from ..extensions import db
    from .social_graph import notify_owners

    try:
        href = url_for("admin.spotlight")
    except RuntimeError:
        href = "/admin/spotlight"   # sweep can run without a request (cron/CLI)
    today = today or date.today()
    sent = 0
    for slot in spotlight_slots(today):
        if not slot["filled"] or not slot["ends"]:
            continue
        if not (slot["ending_soon"] or slot["expired"]):
            continue
        stamp = slot["ends"].isoformat()
        if (get_setting(_notified_key(slot["kind"])) or "").strip() == stamp:
            continue
        if slot["expired"]:
            when = "has run out"
        elif slot["days_left"] == 0:
            when = "runs out today"
        else:
            when = "runs out tomorrow"
        who = slot["subject"]
        if slot["kind"] == "creator":
            tail = f" — {who} has been up all month." if who else ""
        else:
            tail = " — time to pick this week's reel."
        notify_owners(
            kind="spotlight_expiry",
            body=f"{slot['label']} {when}{tail}",
            url=href,
        )
        set_setting(_notified_key(slot["kind"]), stamp)
        sent += 1
    if sent:
        db.session.commit()
    return sent


def maybe_sweep() -> int:
    """Hourly-at-most expiry check, safe to call from any request."""
    global _last_sweep_mono
    now_mono = time.monotonic()
    if (now_mono - _last_sweep_mono) < _SWEEP_GAP_SEC:
        return 0
    _last_sweep_mono = now_mono
    try:
        return sweep_expiry_notices()
    except Exception:
        log.exception("spotlight: expiry sweep failed")
        from ..extensions import db
        try:
            db.session.rollback()
        except Exception:
            pass
        return 0
