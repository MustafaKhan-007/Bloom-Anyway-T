"""Format stored UTC datetimes in the viewer's timezone."""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import request
from flask_login import current_user

DEFAULT_TZ = "UTC"


def normalize_timezone(name: str | None) -> str | None:
    raw = (name or "").strip()
    if not raw or len(raw) > 64:
        return None
    try:
        ZoneInfo(raw)
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        return None
    return raw


def viewer_timezone() -> str:
    if getattr(current_user, "is_authenticated", False):
        saved = normalize_timezone(getattr(current_user, "timezone", None))
        if saved:
            return saved
    cookie = normalize_timezone(request.cookies.get("tz"))
    return cookie or DEFAULT_TZ


def to_local(dt: datetime | None, tz_name: str | None = None) -> datetime | None:
    if dt is None:
        return None
    tz = ZoneInfo(normalize_timezone(tz_name) or viewer_timezone())
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(tz)


def format_local(dt: datetime | None, fmt: str = "%b %d, %Y · %I:%M %p",
                 tz_name: str | None = None) -> str:
    local = to_local(dt, tz_name)
    if local is None:
        return ""
    return local.strftime(fmt)
