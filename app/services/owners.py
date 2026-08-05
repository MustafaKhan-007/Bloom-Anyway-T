"""Invite additional Studio owner emails (co-owners).

The first owner is claimed at /setup. Extra owners are invited here by email:
existing accounts are promoted immediately; new emails are promoted on their
next successful login / email confirmation.
"""
from __future__ import annotations

import json
import logging
import re

from flask import url_for

from ..extensions import db
from ..models import Setting, User
from .mailer import send_email

log = logging.getLogger(__name__)

SETTING_KEY = "_owner_invite_emails"
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_email(email: str | None) -> str:
    return (email or "").strip().lower()


def invite_list() -> list[str]:
    row = db.session.get(Setting, SETTING_KEY)
    raw = (row.value if row else "") or "[]"
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    out, seen = [], set()
    for item in data:
        email = normalize_email(str(item) if item is not None else "")
        if email and email not in seen and _EMAIL_RE.match(email):
            seen.add(email)
            out.append(email)
    return out


def _save_invites(emails: list[str]) -> list[str]:
    cleaned, seen = [], set()
    for item in emails:
        email = normalize_email(item)
        if not email or email in seen or not _EMAIL_RE.match(email):
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


def is_invited(email: str | None) -> bool:
    return normalize_email(email) in set(invite_list())


def current_owners() -> list[User]:
    return (User.query
            .filter(User.is_admin.is_(True), User.deleted_at.is_(None))
            .order_by(User.created_at.asc())
            .all())


def admin_count() -> int:
    return (User.query
            .filter(User.is_admin.is_(True), User.deleted_at.is_(None))
            .count())


def promote(user: User) -> bool:
    """Make ``user`` an owner. Returns True if anything changed."""
    if not user or user.deleted_at is not None:
        return False
    changed = False
    if not user.is_admin:
        user.is_admin = True
        changed = True
    if user.membership != "creator":
        user.membership = "creator"
        changed = True
    if changed:
        db.session.commit()
    return changed


def apply_pending_invite(user: User) -> bool:
    """If ``user``'s email is on the invite list, promote them and drop the invite."""
    if not user or user.deleted_at is not None:
        return False
    email = normalize_email(user.email)
    if not email or not is_invited(email):
        return False
    promote(user)
    _save_invites([e for e in invite_list() if e != email])
    log.info("owners: promoted invited user %s (%s)", user.id, email)
    return True


def invite(email: str, *, actor: User | None = None) -> tuple[bool, str]:
    email = normalize_email(email)
    if not _EMAIL_RE.match(email):
        return False, "That doesn't look like an email address."
    if actor and normalize_email(actor.email) == email:
        return False, "You're already an owner."

    existing = (User.query
                .filter(User.email == email, User.deleted_at.is_(None))
                .first())
    if existing and existing.is_admin:
        # Drop a stale invite row if it somehow still exists.
        if is_invited(email):
            _save_invites([e for e in invite_list() if e != email])
        return False, "That account is already an owner."

    if existing:
        promote(existing)
        if is_invited(email):
            _save_invites([e for e in invite_list() if e != email])
        _send_invite_email(email, existing_account=True, actor=actor)
        return True, f"{email} is now an owner — they can open Studio on their next visit."

    if is_invited(email):
        return False, "That email is already on the invite list."
    current = invite_list()
    current.append(email)
    _save_invites(current)
    _send_invite_email(email, existing_account=False, actor=actor)
    return True, f"Invite saved for {email}. They become an owner when they join or sign in."


def remove(email: str, *, actor: User | None = None) -> tuple[bool, str]:
    email = normalize_email(email)
    if not email:
        return False, "Missing email."
    if actor and normalize_email(actor.email) == email:
        return False, "You can't remove your own owner access."

    removed_invite = False
    if is_invited(email):
        _save_invites([e for e in invite_list() if e != email])
        removed_invite = True

    user = (User.query
            .filter(User.email == email, User.deleted_at.is_(None))
            .first())
    if user and user.is_admin:
        if admin_count() <= 1:
            return False, "You can't remove the last owner."
        user.is_admin = False
        db.session.commit()
        return True, f"Owner access removed for {email}."

    if removed_invite:
        return True, f"Invite removed for {email}."
    return False, "That email isn't an owner or pending invite."


def _send_invite_email(email: str, *, existing_account: bool,
                       actor: User | None) -> None:
    who = ""
    if actor:
        who = f" ({actor.public_name()})" if actor.public_name() else ""
    try:
        login_url = url_for("auth.login", _external=True)
        register_url = url_for("auth.register", _external=True)
    except RuntimeError:
        login_url = "/login"
        register_url = "/register"

    if existing_account:
        subject = "You're now a Bloom Anyway owner"
        text = (
            f"Hi,\n\n"
            f"You've been added as a Studio owner{who}.\n\n"
            f"Sign in and open Studio:\n{login_url}\n\n"
            f"— Bloom Anyway\n"
        )
    else:
        subject = "You're invited as a Bloom Anyway owner"
        text = (
            f"Hi,\n\n"
            f"You've been invited as a Studio owner{who}.\n\n"
            f"Create your account with this email address:\n{register_url}\n\n"
            f"After you confirm your email, you'll have full Studio access.\n"
            f"Already have an account? Sign in here:\n{login_url}\n\n"
            f"— Bloom Anyway\n"
        )
    try:
        send_email(email, subject, text)
    except Exception:
        log.exception("owners: failed to email invite to %s", email)
