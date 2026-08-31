"""Let a Studio owner browse the site as an ordinary member.

Owners rank as Full Bloom through ``User.effective_membership()``, which is
convenient right up until you want to check what a paying member actually
gets — or whether the free membership perk on a test product really lands.
Owners are the only people allowed to buy a test product, and the only people
whose tier can't move, so without this there is no way to see the perk work.

The choice lives in the session, never on the account, so it costs nothing to
enter or leave, expires with the login, and can't leak onto anyone else. It
changes what the owner *sees*: Studio stays open, and test products stay
visible, because those are owner tools rather than membership gates.
"""
from __future__ import annotations

from ..models import MEMBERSHIP_LABELS, MEMBERSHIPS, higher_membership

#: session key holding the owner's choice
SESSION_KEY = "owner_preview"

#: "real" means "whatever I have actually earned" — the membership column plus
#: any perk from a product I bought, which is the interesting case for testing.
REAL = "real"

#: everything the switch accepts
CHOICES = (REAL,) + MEMBERSHIPS


def choice_label(choice: str) -> str:
    if choice == REAL:
        return "What I've actually earned"
    return MEMBERSHIP_LABELS.get(choice, choice)


def _session():
    """The Flask session, or None when there's no request to read it from."""
    try:
        from flask import has_request_context, session
    except ImportError:
        return None
    return session if has_request_context() else None


def current_choice() -> str:
    """The raw choice this owner picked, or "" when not previewing."""
    store = _session()
    if store is None:
        return ""
    choice = (store.get(SESSION_KEY) or "").strip()
    return choice if choice in CHOICES else ""


def set_choice(choice: str) -> str:
    """Start (or switch) preview. Returns the choice actually stored."""
    store = _session()
    choice = (choice or "").strip().lower()
    if store is None or choice not in CHOICES:
        return ""
    store[SESSION_KEY] = choice
    _forget_cache()
    return choice


def clear() -> None:
    store = _session()
    if store is not None:
        store.pop(SESSION_KEY, None)
    _forget_cache()


def _forget_cache() -> None:
    try:
        from flask import g, has_app_context
        if has_app_context():
            g.pop("_owner_preview_tier", None)
    except (ImportError, AttributeError):
        pass


def earned_tier(user) -> str:
    """The tier this account would hold if it weren't an owner.

    The membership column plus any product perk. Owners are skipped by
    ``reconcile_user``, so the column is usually "none" and the perk is the
    whole answer — which is exactly what a test purchase should change.
    """
    from .perks import perk_state
    base = getattr(user, "membership", None) or "none"
    return higher_membership(base, perk_state(user)["tier"] or "none")


def preview_tier(user) -> str:
    """Concrete tier ``user`` is previewing as, or "" when they are not.

    Only ever answers for the owner who is signed in: ``effective_membership``
    runs against arbitrary rows (the members table, the membership audit), and
    one owner's preview must not colour anybody else's tier.
    """
    if not getattr(user, "is_admin", False) or not getattr(user, "id", None):
        return ""

    try:
        from flask import g, has_app_context
        has_g = has_app_context()
    except ImportError:
        g, has_g = None, False
    if has_g:
        cached = getattr(g, "_owner_preview_tier", None)
        if cached is not None and cached[0] == user.id:
            return cached[1]

    tier = ""
    choice = current_choice()
    if choice:
        from flask_login import current_user
        signed_in = getattr(current_user, "id", None)
        if signed_in == user.id:
            tier = earned_tier(user) if choice == REAL else choice

    if has_g:
        g._owner_preview_tier = (user.id, tier)
    return tier


def state(user) -> dict:
    """What the preview bar needs: ``{"on", "choice", "tier", "label"}``."""
    tier = preview_tier(user)
    if not tier:
        return {"on": False, "choice": "", "tier": "", "label": ""}
    choice = current_choice()
    label = MEMBERSHIP_LABELS.get(tier, tier)
    if choice == REAL:
        from .perks import perk_end_display
        until = perk_end_display(user)
        if until:
            label += f", until {until}"
        elif tier == "none":
            label += " — nothing earned yet"
    return {"on": True, "choice": choice, "tier": tier, "label": label}
