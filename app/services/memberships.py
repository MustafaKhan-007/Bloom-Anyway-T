"""Grant / revoke membership tiers from purchases.

Source of truth (in order):
1. ``orders.membership_tier`` on paid membership orders (set at checkout)
2. Stripe price id → ``MembershipPlan``
3. Stripe product id → ``MembershipPlan``
4. Known Stripe product names (Healing/Creator/Full Bloom Membership Monthly|Annual)
5. Checkout / subscription metadata ``tier``
"""
import logging
import re

from sqlalchemy import func, or_

from ..models import MembershipPlan, Order, User, higher_membership

log = logging.getLogger(__name__)

_PAID_TIERS = ("healing", "creator", "full_bloom")

# Exact Stripe product names used in the dashboard (normalized lowercase).
_STRIPE_PRODUCT_NAME_TIERS = {
    "full bloom membership (annual)": "full_bloom",
    "full bloom membership (monthly)": "full_bloom",
    "creator membership (annual)": "creator",
    "creator membership (monthly)": "creator",
    "healing membership (annual)": "healing",
    "healing membership (monthly)": "healing",
}


def _norm_name(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def tier_from_stripe_product_name(name: str | None) -> str | None:
    """Map a Stripe product name to a tier when it matches the known catalog."""
    key = _norm_name(name)
    if not key:
        return None
    if key in _STRIPE_PRODUCT_NAME_TIERS:
        return _STRIPE_PRODUCT_NAME_TIERS[key]
    # Tolerate missing "Membership" or swapped punctuation.
    compact = key.replace("—", "-").replace("–", "-")
    for label, tier in _STRIPE_PRODUCT_NAME_TIERS.items():
        if compact == label:
            return tier
    # Last resort: clear "[Tier] Membership" without billing suffix.
    for needle, tier in (
        ("full bloom membership", "full_bloom"),
        ("creator membership", "creator"),
        ("healing membership", "healing"),
    ):
        if compact.startswith(needle):
            return tier
    return None


def _plan_for_product_id(product_id):
    """Match a Stripe *price* id (or legacy variant) to a MembershipPlan."""
    if not product_id:
        return None
    key = str(product_id).strip()
    if not key:
        return None
    matches = (MembershipPlan.query
               .filter(or_(MembershipPlan.stripe_price_id == key,
                           MembershipPlan.stripe_price_id_annual == key,
                           MembershipPlan.ls_variant_id == key))
               .all())
    if not matches:
        return None
    if len(matches) == 1:
        return matches[0]
    by_tier = {p.tier: p for p in matches}
    log.error(
        "membership: price %s matches multiple plans %s — fix Studio price ids",
        key, [p.tier for p in matches],
    )
    halves = [p for p in matches if p.tier in ("healing", "creator")]
    if len(halves) == 1:
        return halves[0]
    return by_tier.get("full_bloom") or matches[0]


def _plan_for_stripe_product_id(stripe_product_id):
    """Match a Stripe *product* id (prod_…) to a MembershipPlan."""
    if not stripe_product_id:
        return None
    key = str(stripe_product_id).strip()
    if not key:
        return None
    matches = (MembershipPlan.query
               .filter(or_(MembershipPlan.stripe_product_id == key,
                           MembershipPlan.stripe_product_id_annual == key))
               .all())
    if not matches:
        return None
    if len(matches) == 1:
        return matches[0]
    log.error(
        "membership: Stripe product %s matches multiple plans %s",
        key, [p.tier for p in matches],
    )
    return matches[0]


def tier_for_price_id(price_id: str | None) -> str | None:
    """Map a Stripe price id to a membership tier via MembershipPlan."""
    plan = _plan_for_product_id(price_id)
    if plan and plan.tier in _PAID_TIERS:
        return plan.tier
    return None


def tier_for_stripe_product(
    product_id: str | None = None,
    product_name: str | None = None,
) -> str | None:
    """Resolve tier from Studio product id and/or known Stripe product name."""
    plan = _plan_for_stripe_product_id(product_id)
    if plan and plan.tier in _PAID_TIERS:
        return plan.tier
    return tier_from_stripe_product_name(product_name)


def purchased_tier(email: str) -> str:
    """Highest membership tier this email owns via paid membership orders."""
    if not email:
        return "none"
    orders = (Order.query
              .filter(Order.status == "paid",
                      func.lower(Order.buyer_email) == email.strip().lower())
              .all())
    best = "none"
    for order in orders:
        tier = (order.membership_tier or "").strip().lower()
        if tier not in _PAID_TIERS:
            tier = tier_for_price_id(order.ls_variant_id) or ""
            if tier in _PAID_TIERS and not order.membership_tier:
                order.membership_tier = tier
        if tier in _PAID_TIERS:
            best = higher_membership(best, tier)
    return best


def reconcile_user(user: User, downgrade: bool = False) -> bool:
    """Sync a user's membership column from Stripe / paid orders.

    Prefer live Stripe (price/product → plan). Else paid local orders.
    Never touches the owner. The caller commits.
    """
    if user is None:
        return False
    if user.is_admin:
        if user.membership != "full_bloom":
            user.membership = "full_bloom"
            return True
        return False

    live = None
    try:
        from .stripe_pay import active_membership_tier_from_stripe
        live = active_membership_tier_from_stripe(user.email)
    except Exception:
        log.exception("membership: stripe live sync failed for user %s", user.id)
        live = None

    purchased = purchased_tier(user.email)
    current = user.membership or "none"

    if live is not None:
        new = live
    elif purchased != "none":
        new = purchased
    elif downgrade:
        new = "none"
    else:
        new = current

    if new != current:
        user.membership = new
        log.info("membership: user %s %s -> %s (live=%s purchased=%s)",
                 user.id, current, new, live, purchased)
        from .listings import enforce_listing_limits
        enforce_listing_limits(user)
        return True
    return False


def reconcile_email(email: str, downgrade: bool = False) -> bool:
    """Reconcile the account matching an email (if one exists). Caller commits."""
    if not email:
        return False
    user = (User.query
            .filter(func.lower(User.email) == email.strip().lower(),
                    User.deleted_at.is_(None))
            .first())
    return reconcile_user(user, downgrade=downgrade)


def apply_from_order(order: Order) -> None:
    """After an order changes, grant/revoke membership if it is a membership order."""
    if not order:
        return
    tier = (order.membership_tier or "").strip().lower()
    if tier not in _PAID_TIERS:
        tier = tier_for_price_id(order.ls_variant_id) or ""
        if tier in _PAID_TIERS:
            order.membership_tier = tier
    if tier not in _PAID_TIERS:
        return
    reconcile_email(order.buyer_email, downgrade=(order.status == "refunded"))
