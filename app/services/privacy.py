"""Account closure / data-minimization helpers."""
from __future__ import annotations

import logging

from sqlalchemy import func

from ..extensions import db
from ..models import ForumComment, ForumPost, Order, ShopPurchase, User, utcnow

log = logging.getLogger(__name__)

_PAID_TIERS = frozenset({"healing", "creator", "full_bloom"})


def _scrub_email_token(user_id: int, row_id: int) -> str:
    return f"closed+{user_id}.{row_id}@invalid.local"


def _clear_membership_history(email: str, *, user_id: int) -> dict:
    """Cancel Stripe billing and detach local purchase history from this email.

    Re-signing up with the same address must start Free: paid Orders and shop
    rows must not still match the email for ``purchased_tier`` / link-pending.
    """
    email_norm = (email or "").strip().lower()
    out = {
        "stripe_ok": True,
        "stripe_cancelled": 0,
        "orders_ended": 0,
        "orders_scrubbed": 0,
        "shop_scrubbed": 0,
        "errors": [],
    }
    if not email_norm or "@" not in email_norm or email_norm.endswith("@invalid.local"):
        return out

    # 1. Cancel live Stripe memberships immediately (also ends matching Orders).
    try:
        from . import stripe_pay as pay
        if pay.configured():
            result = pay.cancel_membership_subscriptions(
                email_norm, at_period_end=False,
            )
            out["stripe_ok"] = bool(result.get("ok"))
            out["stripe_cancelled"] = len(result.get("cancelled") or [])
            out["orders_ended"] = int(result.get("orders_ended") or 0)
            if not result.get("ok"):
                out["errors"].extend(result.get("errors") or ["stripe_cancel_incomplete"])
                log.warning(
                    "close_account: Stripe cancel incomplete for user %s: %s",
                    user_id, result.get("errors"),
                )
            else:
                log.info(
                    "close_account: cancelled %s subscription(s) for user %s",
                    out["stripe_cancelled"], user_id,
                )
    except Exception:
        out["stripe_ok"] = False
        out["errors"].append("stripe_cancel_exception")
        log.exception(
            "close_account: Stripe cancel failed for user %s (%s)",
            user_id, email_norm,
        )

    # 2. End any remaining paid membership Orders (price ids missing / sync lag).
    try:
        from .memberships import tier_for_price_id
    except Exception:
        tier_for_price_id = lambda _pid: None  # noqa: E731

    orders = (
        Order.query
        .filter(
            (func.lower(Order.buyer_email) == email_norm)
            | (func.lower(Order.gift_to_email) == email_norm)
        )
        .all()
    )
    for order in orders:
        buyer_match = (order.buyer_email or "").strip().lower() == email_norm
        gift_match = (order.gift_to_email or "").strip().lower() == email_norm
        if buyer_match:
            tier = (order.membership_tier or "").strip().lower()
            if tier not in _PAID_TIERS:
                tier = (tier_for_price_id(order.ls_variant_id) or "").strip().lower()
            if tier in _PAID_TIERS and order.status == "paid":
                order.status = "refunded"
                out["orders_ended"] += 1
            # Detach from the real email so reconcile cannot revive access on re-signup.
            order.buyer_email = _scrub_email_token(user_id, order.id)
        if gift_match:
            order.gift_to_email = None
        out["orders_scrubbed"] += 1

    # 3. Detach shop / course purchases so they don't auto-link on re-signup.
    shops = (
        ShopPurchase.query
        .filter(func.lower(ShopPurchase.customer_email) == email_norm)
        .all()
    )
    for row in shops:
        row.customer_email = _scrub_email_token(user_id, row.id)
        row.user_id = None
        if row.status == "linked":
            row.status = "pending_link"
        out["shop_scrubbed"] += 1

    return out


def close_account(user: User) -> None:
    """Soft-delete and scrub personal data so the account can't be recovered
    as the same person, while keeping forum integrity (hidden, not wiped).

    Cancels Stripe memberships, ends local membership orders, and detaches
    purchase history from the email so a new account with the same address
    starts Free.
    """
    uid = user.id
    email = (user.email or "").strip()

    # Cancel memberships / clear purchase history while we still have the email.
    clear_info = _clear_membership_history(email, user_id=uid)
    if clear_info.get("errors"):
        log.warning(
            "close_account: membership cleanup warnings for user %s: %s",
            uid, clear_info.get("errors"),
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
