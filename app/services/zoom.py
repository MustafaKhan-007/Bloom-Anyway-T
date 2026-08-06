"""Zoom Server-to-Server OAuth — create / update / delete meetings."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime

from urllib.parse import quote

import requests
from flask import current_app

log = logging.getLogger(__name__)

TOKEN_URL = "https://zoom.us/oauth/token"
API_BASE = "https://api.zoom.us/v2"

_token: str | None = None
_token_expires_mono: float = 0.0


@dataclass(frozen=True)
class ZoomMeetingInfo:
    meeting_id: str
    join_url: str


class ZoomError(Exception):
    """User-facing Zoom failure."""


def is_configured() -> bool:
    return bool(
        current_app.config.get("ZOOM_ACCOUNT_ID")
        and current_app.config.get("ZOOM_CLIENT_ID")
        and current_app.config.get("ZOOM_CLIENT_SECRET")
        and current_app.config.get("ZOOM_HOST_EMAIL")
    )


def _use_stub() -> bool:
    """Smoke / local tests: invent a join URL without calling Zoom."""
    if current_app.config.get("ZOOM_STUB"):
        return True
    return bool(current_app.config.get("TESTING")) and not is_configured()


def _duration_minutes() -> int:
    try:
        n = int(current_app.config.get("ZOOM_MEETING_DURATION") or 90)
    except (TypeError, ValueError):
        n = 90
    return max(15, min(n, 480))


def _access_token() -> str:
    global _token, _token_expires_mono
    now = time.monotonic()
    if _token and now < _token_expires_mono:
        return _token

    account_id = current_app.config["ZOOM_ACCOUNT_ID"]
    client_id = current_app.config["ZOOM_CLIENT_ID"]
    client_secret = current_app.config["ZOOM_CLIENT_SECRET"]
    try:
        resp = requests.post(
            TOKEN_URL,
            params={
                "grant_type": "account_credentials",
                "account_id": account_id,
            },
            auth=(client_id, client_secret),
            timeout=20,
        )
    except requests.RequestException as exc:
        log.exception("Zoom token request failed")
        raise ZoomError("Could not reach Zoom to get an access token.") from exc

    if resp.status_code >= 400:
        log.error("Zoom token error %s: %s", resp.status_code, resp.text[:400])
        raise ZoomError(
            "Zoom rejected the API credentials. Check ZOOM_ACCOUNT_ID, "
            "ZOOM_CLIENT_ID, and ZOOM_CLIENT_SECRET."
        )

    data = resp.json()
    _token = data["access_token"]
    # Refresh a minute early; Zoom tokens last ~1 hour.
    _token_expires_mono = now + max(60, int(data.get("expires_in", 3600)) - 60)
    return _token


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {_access_token()}",
        "Content-Type": "application/json",
    }


def _start_time_utc(scheduled_at: datetime) -> str:
    return scheduled_at.replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _meeting_payload(topic: str, scheduled_at: datetime) -> dict:
    return {
        "topic": topic[:200],
        "type": 2,  # scheduled
        "start_time": _start_time_utc(scheduled_at),
        "duration": _duration_minutes(),
        "timezone": "UTC",
        "settings": {
            "waiting_room": True,
            "join_before_host": False,
            "mute_upon_entry": True,
            "approval_type": 2,  # no registration
        },
    }


def create_meeting(*, topic: str, scheduled_at: datetime) -> ZoomMeetingInfo:
    if _use_stub():
        stamp = int(scheduled_at.timestamp()) if scheduled_at else int(time.time())
        mid = str(900_000_000 + (stamp % 90_000_000))
        return ZoomMeetingInfo(
            meeting_id=mid,
            join_url=f"https://zoom.us/j/{mid}",
        )
    if not is_configured():
        raise ZoomError(
            "Zoom isn't configured yet. Set ZOOM_ACCOUNT_ID, ZOOM_CLIENT_ID, "
            "ZOOM_CLIENT_SECRET, and ZOOM_HOST_EMAIL on the host."
        )

    host = current_app.config["ZOOM_HOST_EMAIL"]
    url = f"{API_BASE}/users/{quote(host, safe='@.')}/meetings"
    try:
        resp = requests.post(
            url, headers=_headers(), json=_meeting_payload(topic, scheduled_at),
            timeout=25,
        )
    except requests.RequestException as exc:
        log.exception("Zoom create meeting failed")
        raise ZoomError("Could not reach Zoom to create the meeting.") from exc

    if resp.status_code >= 400:
        log.error("Zoom create error %s: %s", resp.status_code, resp.text[:500])
        raise ZoomError(_friendly_api_error(resp, "create the Zoom meeting"))

    data = resp.json()
    join = (data.get("join_url") or "").strip()
    mid = str(data.get("id") or "").strip()
    if not join or not mid:
        raise ZoomError("Zoom created a meeting but returned no join link.")
    return ZoomMeetingInfo(meeting_id=mid, join_url=join[:500])


def update_meeting(meeting_id: str, *, topic: str,
                   scheduled_at: datetime) -> ZoomMeetingInfo | None:
    """Patch start time; returns None if stub / already using stored join URL."""
    if _use_stub():
        return ZoomMeetingInfo(
            meeting_id=str(meeting_id),
            join_url=f"https://zoom.us/j/{meeting_id}",
        )
    if not is_configured():
        raise ZoomError(
            "Zoom isn't configured yet. Set ZOOM_ACCOUNT_ID, ZOOM_CLIENT_ID, "
            "ZOOM_CLIENT_SECRET, and ZOOM_HOST_EMAIL on the host."
        )

    url = f"{API_BASE}/meetings/{meeting_id}"
    body = {
        "topic": topic[:200],
        "start_time": _start_time_utc(scheduled_at),
        "duration": _duration_minutes(),
        "timezone": "UTC",
    }
    try:
        resp = requests.patch(url, headers=_headers(), json=body, timeout=25)
    except requests.RequestException as exc:
        log.exception("Zoom update meeting failed")
        raise ZoomError("Could not reach Zoom to update the meeting.") from exc

    if resp.status_code == 404:
        return None
    if resp.status_code >= 400:
        log.error("Zoom update error %s: %s", resp.status_code, resp.text[:500])
        raise ZoomError(_friendly_api_error(resp, "update the Zoom meeting"))
    return ZoomMeetingInfo(meeting_id=str(meeting_id), join_url="")


def delete_meeting(meeting_id: str) -> None:
    if not meeting_id or _use_stub():
        return
    if not is_configured():
        return
    url = f"{API_BASE}/meetings/{meeting_id}"
    try:
        resp = requests.delete(url, headers=_headers(), timeout=20)
    except requests.RequestException:
        log.exception("Zoom delete meeting failed for %s", meeting_id)
        return
    if resp.status_code not in (204, 404) and resp.status_code >= 400:
        log.warning(
            "Zoom delete error %s for %s: %s",
            resp.status_code, meeting_id, resp.text[:300],
        )


def _friendly_api_error(resp: requests.Response, action: str) -> str:
    try:
        msg = (resp.json() or {}).get("message") or ""
    except ValueError:
        msg = ""
    msg = (msg or "").strip()
    if resp.status_code in (401, 403):
        return (
            f"Zoom refused to {action}. Confirm the Server-to-Server app is "
            f"activated and has meeting write scopes."
        )
    if msg:
        return f"Could not {action}: {msg[:180]}"
    return f"Could not {action} (Zoom HTTP {resp.status_code})."
