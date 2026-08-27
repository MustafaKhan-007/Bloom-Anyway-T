"""Account closure / data-minimization helpers."""
from __future__ import annotations

import logging

from ..extensions import db
from ..models import ForumComment, ForumPost, User, utcnow

log = logging.getLogger(__name__)


def close_account(user: User) -> None:
    """Soft-delete and scrub personal data so the account can't be recovered
    as the same person, while keeping forum integrity (hidden, not wiped).

    Cancels any Stripe membership subscriptions immediately before the email
    is scrubbed, so billing stops when the account is deleted.
    """
    uid = user.id
    email = (user.email or "").strip()

    # Cancel memberships while we still have the real email on file.
    if email and "@" in email and not email.endswith("@invalid.local"):
        try:
            from . import stripe_pay as pay
            if pay.configured():
                result = pay.cancel_membership_subscriptions(
                    email, at_period_end=False,
                )
                if not result.get("ok"):
                    log.warning(
                        "close_account: Stripe cancel incomplete for user %s: %s",
                        uid, result.get("errors"),
                    )
                else:
                    log.info(
                        "close_account: cancelled %s subscription(s) for user %s",
                        len(result.get("cancelled") or []), uid,
                    )
        except Exception:
            log.exception(
                "close_account: Stripe cancel failed for user %s (%s)",
                uid, email,
            )

    # Hide public community content
    ForumPost.query.filter_by(user_id=uid, hidden=False).update(
        {"hidden": True}, synchronize_session=False)
    ForumComment.query.filter_by(user_id=uid, hidden=False).update(
        {"hidden": True}, synchronize_session=False)

    user.deleted_at = utcnow()
    user.email = f"deleted+{uid}@invalid.local"
    user.password_hash = None
    user.email_verified_at = None
    user.display_name = "Former member"
    user.username = None
    user.avatar_url = None
    user.avatar_data = None
    user.avatar_mime = None
    user.avatar_anim_data = None
    user.avatar_anim_mime = None
    user.bio = None
    user.links_json = None
    user.goals_json = None
    user.timezone = None
    user.displayed_badges_json = None
    user.default_anonymous = False
    user.membership = "none"
    user.membership_cancel_at = None
    try:
        from .listings import enforce_listing_limits
        enforce_listing_limits(user)
    except Exception:
        log.exception("close_account: listing limit enforce failed for user %s", uid)
    db.session.commit()
