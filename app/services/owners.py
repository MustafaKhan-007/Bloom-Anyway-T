"""Invite additional Studio owner emails (co-owners).

The first owner is claimed at /setup. Extra owners are invited here by email:
existing accounts are promoted immediately; new emails are promoted on their
next successful login / email confirmation.

Invites may be full Studio owners or view-only (can open Studio, cannot save).
"""
from __future__ import annotations

import json
import logging
import re

from flask import url_for

from ..extensions import db
from ..models import Setting, User
from .mailer import send_styled_email

log = logging.getLogger(__name__)

SETTING_KEY = "_owner_invite_emails"
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_email(email: str | None) -> str:
    return (email or "").strip().lower()


def _parse_invite_entries(raw) -> list[dict]:
    """Accept legacy ``["a@b.com"]`` or ``[{"email": "...", "readonly": bool}]``."""
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    out, seen = [], set()
    for item in data:
        readonly = False
        if isinstance(item, dict):
            email = normalize_email(item.get("email"))
            readonly = bool(item.get("readonly"))
        else:
            email = normalize_email(str(item) if item is not None else "")
        if not email or email in seen or not _EMAIL_RE.match(email):
            continue
        seen.add(email)
        out.append({"email": email, "readonly": readonly})
    return out


def invite_entries() -> list[dict]:
    row = db.session.get(Setting, SETTING_KEY)
    raw = (row.value if row else "") or "[]"
    return _parse_invite_entries(raw)


def invite_list() -> list[str]:
    """Emails only (compat for older callers / smoke tests)."""
    return [e["email"] for e in invite_entries()]


def invite_readonly_for(email: str | None) -> bool:
    key = normalize_email(email)
    for entry in invite_entries():
        if entry["email"] == key:
            return bool(entry["readonly"])
    return False


def _save_invites(entries: list[dict]) -> list[dict]:
    cleaned, seen = [], set()
    for item in entries:
        if isinstance(item, dict):
            email = normalize_email(item.get("email"))
            readonly = bool(item.get("readonly"))
        else:
            email = normalize_email(str(item) if item is not None else "")
            readonly = False
        if not email or email in seen or not _EMAIL_RE.match(email):
            continue
        seen.add(email)
        cleaned.append({"email": email, "readonly": readonly})
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


def heal_stale_owner_creator_tiers() -> int:
    """One-time: drop Creator on non-owners who only had it from past owner access.

    Skips anyone with a paid Creator order. Manually granted Creators without a
    purchase are also reset — re-grant them under Studio → Members if needed.
    Returns how many users were changed.
    """
    from .memberships import purchased_tier, reconcile_user
    from .settings import get_setting, set_setting

    if (get_setting("_healed_stale_owner_creator_tiers") or "").strip() == "1":
        return 0
    changed = 0
    rows = (User.query
            .filter(User.deleted_at.is_(None),
                    User.is_admin.is_(False),
                    User.membership == "creator")
            .all())
    for user in rows:
        if purchased_tier(user.email) == "creator":
            continue
        if reconcile_user(user, downgrade=True):
            changed += 1
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        return 0
    set_setting("_healed_stale_owner_creator_tiers", "1")
    if changed:
        log.info("owners: healed %s stale Creator tier(s) after demotion", changed)
    return changed


def promote(user: User, *, readonly: bool = False) -> bool:
    """Make ``user`` a Studio owner. Returns True if anything changed.

    ``readonly`` → can open Studio but cannot save changes (view-only observers).

    Does not rewrite ``membership`` — owners already get Creator perks via
    ``User.effective_membership()``. Writing the column used to leave demoted
    co-owners stuck on Creator forever.
    """
    if not user or user.deleted_at is not None:
        return False
    want_ro = bool(readonly)
    if user.is_admin:
        if bool(getattr(user, "admin_readonly", False)) == want_ro:
            return False
        user.admin_readonly = want_ro
        db.session.commit()
        return True
    user.is_admin = True
    user.admin_readonly = want_ro
    db.session.commit()
    return True


def apply_pending_invite(user: User) -> bool:
    """If ``user``'s email is on the invite list, promote them and drop the invite."""
    if not user or user.deleted_at is not None:
        return False
    email = normalize_email(user.email)
    if not email or not is_invited(email):
        return False
    readonly = invite_readonly_for(email)
    promote(user, readonly=readonly)
    _save_invites([e for e in invite_entries() if e["email"] != email])
    log.info("owners: promoted invited user %s (%s) readonly=%s",
             user.id, email, readonly)
    return True


def invite(email: str, *, actor: User | None = None,
           readonly: bool = False) -> tuple[bool, str]:
    email = normalize_email(email)
    readonly = bool(readonly)
    if not _EMAIL_RE.match(email):
        return False, "That doesn't look like an email address."
    if actor and normalize_email(actor.email) == email:
        return False, "You're already an owner."
    if actor and getattr(actor, "admin_readonly", False):
        return False, "View-only Studio accounts can't invite owners."

    existing = (User.query
                .filter(User.email == email, User.deleted_at.is_(None))
                .first())
    role_label = "view-only Studio access" if readonly else "full Studio access"
    if existing and existing.is_admin:
        # Already an owner — update role if needed, drop stale invite.
        changed = promote(existing, readonly=readonly)
        if is_invited(email):
            _save_invites([e for e in invite_entries() if e["email"] != email])
        if changed:
            return True, f"{email} is now set to {role_label}."
        return False, "That account is already an owner."

    if existing:
        promote(existing, readonly=readonly)
        if is_invited(email):
            _save_invites([e for e in invite_entries() if e["email"] != email])
        _send_invite_email(email, existing_account=True, actor=actor,
                           readonly=readonly)
        if readonly:
            return True, (
                f"{email} now has view-only Studio access — they can open Studio "
                f"but can’t change anything."
            )
        return True, f"{email} is now an owner — they can open Studio on their next visit."

    if is_invited(email):
        # Refresh role on pending invite.
        entries = [e for e in invite_entries() if e["email"] != email]
        entries.append({"email": email, "readonly": readonly})
        _save_invites(entries)
        _send_invite_email(email, existing_account=False, actor=actor,
                           readonly=readonly)
        return True, f"Invite updated for {email} ({role_label})."

    current = invite_entries()
    current.append({"email": email, "readonly": readonly})
    _save_invites(current)
    _send_invite_email(email, existing_account=False, actor=actor,
                       readonly=readonly)
    if readonly:
        return True, (
            f"View-only invite saved for {email}. They unlock Studio (read-only) "
            f"when they join or sign in."
        )
    return True, f"Invite saved for {email}. They become an owner when they join or sign in."


def remove(email: str, *, actor: User | None = None) -> tuple[bool, str]:
    email = normalize_email(email)
    if not email:
        return False, "Missing email."
    if actor and normalize_email(actor.email) == email:
        return False, "You can't remove your own owner access."
    if actor and getattr(actor, "admin_readonly", False):
        return False, "View-only Studio accounts can't change owners."

    removed_invite = False
    if is_invited(email):
        _save_invites([e for e in invite_entries() if e["email"] != email])
        removed_invite = True

    user = (User.query
            .filter(User.email == email, User.deleted_at.is_(None))
            .first())
    if user and user.is_admin:
        if admin_count() <= 1:
            return False, "You can't remove the last owner."
        user.is_admin = False
        user.admin_readonly = False
        # Only clear a leftover Creator column from old promote/Studio-visit
        # behaviour. Do not touch Healing (or other) tiers that were already set.
        if user.membership == "creator":
            from .memberships import reconcile_user
            reconcile_user(user, downgrade=True)
        db.session.commit()
        return True, f"Owner access removed for {email}."

    if user and not user.is_admin and user.membership == "creator":
        # Already demoted earlier — still clear a stuck Creator column.
        from .memberships import reconcile_user
        if reconcile_user(user, downgrade=True):
            db.session.commit()
            return True, f"Membership synced for {email} (owner access was already removed)."

    if removed_invite:
        return True, f"Invite removed for {email}."
    return False, "That email isn't an owner or pending invite."


def _send_invite_email(email: str, *, existing_account: bool,
                       actor: User | None, readonly: bool = False) -> None:
    who = ""
    if actor:
        who = f" ({actor.public_name()})" if actor.public_name() else ""
    try:
        login_url = url_for("auth.login", _external=True)
        register_url = url_for("auth.register", _external=True)
    except RuntimeError:
        login_url = "/login"
        register_url = "/register"

    if readonly:
        access = "view-only Studio access (you can look around; changes stay locked)"
    else:
        access = "full Studio owner access"

    if existing_account:
        subject = "You're now a Bloom Anyway Studio owner" if not readonly else (
            "Bloom Anyway Studio access (view-only)")
        title = "Studio access"
        body = (
            f"You've been given {access}{who}.\n\n"
            "Sign in and open Studio from your account."
        )
        button_text = "Sign in"
        button_url = login_url
    else:
        subject = "You're invited to Bloom Anyway Studio"
        title = "You're invited to Studio"
        body = (
            f"You've been invited with {access}{who}.\n\n"
            "Create your account with this email address. After you confirm "
            "your email, you'll unlock Studio."
        )
        button_text = "Create account"
        button_url = register_url
    try:
        send_styled_email(
            email,
            subject=subject,
            preview=title,
            header="Bloom Anyway Studio",
            title=title,
            body=body,
            button_text=button_text,
            button_url=button_url,
        )
    except Exception:
        log.exception("owners: failed to email invite to %s", email)
