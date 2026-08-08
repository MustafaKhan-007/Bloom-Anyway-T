"""PRELAUNCH LOCK — delete this module + the gate in app/__init__.py +
Studio /admin/prelaunch routes/template when you go live.

Flip off instantly with env ``PRELAUNCH_LOCK=0`` (no code change needed).
"""
from __future__ import annotations

import json
import re

from flask import current_app

from ..extensions import db
from ..models import Setting

#: always allowed (owner). Lowercase only.
OWNER_EMAILS = frozenset({
    "mustafakhanabdullah07@gmail.com",
})

# Underscore prefix keeps this out of public `site` template settings.
SETTING_KEY = "_prelaunch_allowlist"
PUBLIC_BROWSE_KEY = "_prelaunch_public_browse"

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Paths anyone may hit while the lock is on (auth + infra only).
_PUBLIC_EXACT = frozenset({
    "/login", "/register", "/setup", "/verify-email",
    "/forgot-password", "/reset-password", "/logout", "/healthz",
})
_PUBLIC_PREFIXES = ("/static/", "/webhooks/", "/media/site/", "/cron/")


def enabled() -> bool:
    return bool(current_app.config.get("PRELAUNCH_LOCK"))


def public_browse_enabled() -> bool:
    """When True, invite-list restrictions are off while PRELAUNCH_LOCK stays on."""
    row = db.session.get(Setting, PUBLIC_BROWSE_KEY)
    return (row.value if row else "").strip().lower() in ("1", "true", "yes", "on")


def set_public_browse(on: bool) -> bool:
    payload = "1" if on else "0"
    row = db.session.get(Setting, PUBLIC_BROWSE_KEY)
    if row is None:
        db.session.add(Setting(key=PUBLIC_BROWSE_KEY, value=payload))
    else:
        row.value = payload
    db.session.commit()
    return on


def is_public_path(path: str) -> bool:
    if path in _PUBLIC_EXACT:
        return True
    return any(path.startswith(p) for p in _PUBLIC_PREFIXES)


def allowlist() -> list[str]:
    row = db.session.get(Setting, SETTING_KEY)
    raw = (row.value if row else "") or "[]"
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    out = []
    seen = set()
    for item in data:
        email = (str(item) if item is not None else "").strip().lower()
        if email and email not in seen and _EMAIL_RE.match(email):
            seen.add(email)
            out.append(email)
    return out


def save_allowlist(emails: list[str]) -> list[str]:
    cleaned = []
    seen = set()
    for item in emails:
        email = (item or "").strip().lower()
        if not email or email in seen or not _EMAIL_RE.match(email):
            continue
        if email in OWNER_EMAILS:
            continue
        seen.add(email)
        cleaned.append(email)
    row = db.session.get(Setting, SETTING_KEY)
    payload = json.dumps(cleaned)
    if row is None:
        db.session.add(Setting(key=SETTING_KEY, value=payload))
    else:
        row.value = payload
    db.session.commit()
    return cleaned


def add_email(email: str) -> tuple[bool, str]:
    email = (email or "").strip().lower()
    if not _EMAIL_RE.match(email):
        return False, "That doesn't look like an email address."
    if email in OWNER_EMAILS:
        return False, "The owner account already has access."
    current = allowlist()
    if email in current:
        return False, "That email is already on the list."
    current.append(email)
    save_allowlist(current)
    return True, "Access granted."


def remove_email(email: str) -> tuple[bool, str]:
    email = (email or "").strip().lower()
    current = allowlist()
    if email not in current:
        return False, "That email wasn't on the list."
    save_allowlist([e for e in current if e != email])
    return True, "Access removed."


def user_allowed(user) -> bool:
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "deleted_at", None):
        return False
    email = (getattr(user, "email", None) or "").strip().lower()
    if email in OWNER_EMAILS:
        return True
    if getattr(user, "is_admin", False):
        return True
    return email in set(allowlist())
