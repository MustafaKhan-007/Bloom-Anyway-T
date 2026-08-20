"""Daily.co REST API — create / update / delete rooms + meeting tokens."""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta

import requests
from flask import current_app

log = logging.getLogger(__name__)

API_BASE = "https://api.daily.co/v1"


@dataclass(frozen=True)
class DailyRoomInfo:
    room_name: str
    room_url: str


class DailyError(Exception):
    """User-facing Daily.co failure."""


def is_configured() -> bool:
    return bool(current_app.config.get("DAILY_API_KEY"))


def _use_stub() -> bool:
    if current_app.config.get("DAILY_STUB"):
        return True
    return bool(current_app.config.get("TESTING")) and not is_configured()


def _duration_minutes() -> int:
    try:
        n = int(current_app.config.get("DAILY_MEETING_DURATION") or 90)
    except (TypeError, ValueError):
        n = 90
    return max(15, min(n, 480))


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {current_app.config['DAILY_API_KEY']}",
        "Content-Type": "application/json",
    }


def _slug_name(topic: str, scheduled_at: datetime) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", (topic or "bloom").lower()).strip("-")[:40]
    stamp = int(scheduled_at.timestamp()) if scheduled_at else int(time.time())
    return f"bloom-{base or 'sg'}-{stamp}"[:80]


def _exp_unix(scheduled_at: datetime) -> int:
    """Room expires a few hours after the planned end."""
    end = scheduled_at + timedelta(minutes=_duration_minutes() + 180)
    return int(end.timestamp())


def _nbf_unix(scheduled_at: datetime) -> int:
    """Allow joining up to 45 minutes early."""
    start = scheduled_at - timedelta(minutes=45)
    return int(start.timestamp())


def _room_properties(scheduled_at: datetime) -> dict:
    return {
        "exp": _exp_unix(scheduled_at),
        "nbf": _nbf_unix(scheduled_at),
        "max_participants": 8,
        "enable_chat": True,
        "enable_screenshare": True,
        "start_video_off": True,
        "start_audio_off": True,
        "eject_at_room_exp": True,
    }


def create_room(*, topic: str, scheduled_at: datetime) -> DailyRoomInfo:
    name = _slug_name(topic, scheduled_at)
    if _use_stub():
        domain = (current_app.config.get("DAILY_DOMAIN") or "bloomanyway").strip()
        return DailyRoomInfo(
            room_name=name,
            room_url=f"https://{domain}.daily.co/{name}",
        )
    if not is_configured():
        raise DailyError(
            "Daily.co isn’t configured yet. Set DAILY_API_KEY on the host."
        )

    payload = {
        "name": name,
        "privacy": "private",
        "properties": _room_properties(scheduled_at),
    }
    try:
        resp = requests.post(
            f"{API_BASE}/rooms", headers=_headers(), json=payload, timeout=25,
        )
    except requests.RequestException as exc:
        log.exception("Daily create room failed")
        raise DailyError("Could not reach Daily.co to create the room.") from exc

    if resp.status_code >= 400:
        log.error("Daily create error %s: %s", resp.status_code, resp.text[:500])
        raise DailyError(_friendly_api_error(resp, "create the Daily room"))

    data = resp.json() or {}
    url = (data.get("url") or "").strip()
    room_name = (data.get("name") or name).strip()
    if not url or not room_name:
        raise DailyError("Daily created a room but returned no URL.")
    return DailyRoomInfo(room_name=room_name[:64], room_url=url[:500])


def update_room(room_name: str, *, scheduled_at: datetime) -> DailyRoomInfo | None:
    if _use_stub():
        domain = (current_app.config.get("DAILY_DOMAIN") or "bloomanyway").strip()
        return DailyRoomInfo(
            room_name=str(room_name),
            room_url=f"https://{domain}.daily.co/{room_name}",
        )
    if not is_configured() or not room_name:
        return None

    payload = {"properties": _room_properties(scheduled_at)}
    try:
        resp = requests.post(
            f"{API_BASE}/rooms/{room_name}",
            headers=_headers(), json=payload, timeout=25,
        )
    except requests.RequestException as exc:
        log.exception("Daily update room failed")
        raise DailyError("Could not reach Daily.co to update the room.") from exc

    if resp.status_code == 404:
        return None
    if resp.status_code >= 400:
        log.error("Daily update error %s: %s", resp.status_code, resp.text[:500])
        raise DailyError(_friendly_api_error(resp, "update the Daily room"))

    data = resp.json() or {}
    url = (data.get("url") or "").strip()
    return DailyRoomInfo(
        room_name=str(room_name),
        room_url=url[:500] if url else "",
    )


def delete_room(room_name: str) -> None:
    if not room_name or _use_stub():
        return
    if not is_configured():
        return
    try:
        resp = requests.delete(
            f"{API_BASE}/rooms/{room_name}", headers=_headers(), timeout=20,
        )
    except requests.RequestException:
        log.exception("Daily delete room failed for %s", room_name)
        return
    if resp.status_code not in (200, 204, 404) and resp.status_code >= 400:
        log.warning(
            "Daily delete error %s for %s: %s",
            resp.status_code, room_name, resp.text[:300],
        )


def create_meeting_token(
    *,
    room_name: str,
    user_name: str,
    is_owner: bool = False,
    scheduled_at: datetime | None = None,
) -> str:
    """Short-lived token so the client can join a private room."""
    if _use_stub():
        return f"stub-token-{room_name}"
    if not is_configured():
        raise DailyError("Daily.co isn’t configured yet. Set DAILY_API_KEY on the host.")
    if not room_name:
        raise DailyError("Missing Daily room name.")

    exp = _exp_unix(scheduled_at or datetime.utcnow())
    props = {
        "room_name": room_name,
        "user_name": (user_name or "Member")[:80],
        "is_owner": bool(is_owner),
        "enable_screenshare": True,
        "start_video_off": True,
        "start_audio_off": True,
        "exp": exp,
    }
    try:
        resp = requests.post(
            f"{API_BASE}/meeting-tokens",
            headers=_headers(),
            json={"properties": props},
            timeout=20,
        )
    except requests.RequestException as exc:
        log.exception("Daily meeting token failed")
        raise DailyError("Could not reach Daily.co for a join token.") from exc

    if resp.status_code >= 400:
        log.error("Daily token error %s: %s", resp.status_code, resp.text[:500])
        raise DailyError(_friendly_api_error(resp, "create a Daily join token"))

    token = ((resp.json() or {}).get("token") or "").strip()
    if not token:
        raise DailyError("Daily did not return a join token.")
    return token


def _friendly_api_error(resp: requests.Response, action: str) -> str:
    try:
        body = resp.json() or {}
        msg = (body.get("error") or body.get("info") or body.get("message") or "")
    except ValueError:
        msg = ""
    msg = (msg or "").strip()
    if resp.status_code in (401, 403):
        return (
            f"Daily.co refused to {action}. Confirm DAILY_API_KEY is valid "
            f"for this domain."
        )
    if msg:
        return f"Could not {action}: {msg[:180]}"
    return f"Could not {action} (Daily HTTP {resp.status_code})."
