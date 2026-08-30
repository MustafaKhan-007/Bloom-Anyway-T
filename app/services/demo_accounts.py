"""Hand-made accounts for filling out a quiet room.

An owner types a username and a password in Studio and gets an account that
behaves like any other member: it can sign in, post, and comment, and nobody
outside Studio can tell it apart from a real one.

There is no email address to type, which is the whole point — but the users
table needs one, so each account gets a synthetic address on a domain that
cannot receive mail. ``is_demo`` is what everything else keys off; the address
is only there to satisfy the column.

These are created on demand and never seeded, so a redeploy won't bring back
ones an owner deleted.
"""
from datetime import datetime, timezone

from ..extensions import db
from ..models import MEMBERSHIPS, User
from .social_graph import normalize_username, username_error

#: .invalid is reserved by RFC 2606 — nothing can ever be delivered to it.
DEMO_EMAIL_DOMAIN = "demo.invalid"

MIN_PASSWORD = 8


def is_demo_address(email: str) -> bool:
    """True for the synthetic addresses demo accounts carry.

    Belt and braces alongside the ``is_demo`` flag: anything holding one of
    these addresses must never be handed to the mailer.
    """
    return (email or "").strip().lower().endswith("@" + DEMO_EMAIL_DOMAIN)


def address_for(username: str) -> str:
    return f"{normalize_username(username)}@{DEMO_EMAIL_DOMAIN}"


def validation_error(username: str, password: str, membership: str) -> str | None:
    """Why this can't be created, or None if it's fine."""
    handle = normalize_username(username)
    err = username_error(handle)
    if err:
        return err
    taken = User.query.filter(db.func.lower(User.username) == handle).first()
    if taken or User.query.filter_by(email=address_for(handle)).first():
        return f"@{handle} is taken. Pick another username."
    if len(password or "") < MIN_PASSWORD:
        return f"Give it a password of at least {MIN_PASSWORD} characters."
    if membership not in MEMBERSHIPS:
        return "Pick a membership tier."
    return None


def create(username: str, password: str, *, display_name: str = "",
           membership: str = "none") -> User:
    """Make the account. Call :func:`validation_error` first."""
    handle = normalize_username(username)
    user = User(
        email=address_for(handle),
        username=handle,
        display_name=(display_name or "").strip()[:80] or None,
        membership=membership,
        is_demo=True,
        # Signing in checks this, and there is no inbox to confirm from.
        email_verified_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return user


def find_by_username(username: str) -> User | None:
    """A live demo account with this handle, for the username sign-in path."""
    handle = normalize_username(username)
    if not handle:
        return None
    return (User.query
            .filter(db.func.lower(User.username) == handle,
                    User.is_demo.is_(True),
                    User.deleted_at.is_(None))
            .first())


def count() -> int:
    return User.query.filter(User.is_demo.is_(True),
                             User.deleted_at.is_(None)).count()
