"""Grant / revoke membership tiers from purchases.

Memberships are sold as ``MembershipPlan`` rows. Each plan carries a Stripe
product id; an order for that product grants the plan's tier. A member's tier
is kept on ``users.membership``. Live Stripe subscriptions are the source of
truth when available; otherwise paid local Orders drive the tier. Buying a new
membership replaces any prior one. The owner (``is_admin``) is always Full
Bloom and is untouched.
"""
import logging

from sqlalchemy import func, or_

from ..models import MembershipPlan, Order, User, higher_membership

log = logging.getLogger(__name__)

_PAID_TIERS = ("healing", "creator", "full_bloom")


def _plan_for_product_id(product_id):
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
    # Same Stripe price on multiple plans (Studio misconfig). Prefer a half-tier
    # over Full Bloom so a Creator checkout cannot grant Full Bloom by accident.
    halves = [p for p in matches if p.tier in ("healing", "creator")]
    pick = halves[0] if len(halves) == 1 else matches[0]
    log.warning(
        "membership: price %s matches plans %s; using %s",
        key, [p.tier for p in matches], pick.tier,
    )
    return pick


def purchased_tier(email: str) -> str:
    """Highest membership tier this email owns via paid membership orders."""
    if not email:
        return "none"
    orders = (Order.query
              .filter(Order.status == "paid",
                      func.lower(Order.buyer_email) == email.strip().lower(),
                      Order.ls_variant_id.isnot(None))
              .all())
    best = "none"
    for order in orders:
        plan = _plan_for_product_id(order.ls_variant_id)
        if plan and plan.tier in _PAID_TIERS:
            best = higher_membership(best, plan.tier)
    return best


def reconcile_user(user: User, downgrade: bool = False) -> bool:
    """Sync a user's membership column from Stripe / purchases.

    Prefer the live Stripe subscription tier when Stripe is reachable. Fall
    back to paid local Orders. Studio-only grants are kept only when neither
    Stripe nor Orders show a membership (unless ``downgrade``). Never touches
    the owner. The caller commits.
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
    """After an order changes, grant/revoke membership if its product matches a plan."""
    if not order or not order.ls_variant_id:
        return
    plan = _plan_for_product_id(order.ls_variant_id)
    if not plan or plan.tier not in _PAID_TIERS:
        return
    reconcile_email(order.buyer_email, downgrade=(order.status == "refunded"))
