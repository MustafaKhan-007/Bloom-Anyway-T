"""Grant / revoke membership tiers from purchases.

Memberships are sold as ``MembershipPlan`` rows. Each plan carries a Dodo
product id; an order for that product grants the plan's tier. A member's tier
is kept on ``users.membership``. Purchases *upgrade* that column; a refund
recomputes the tier from remaining paid membership orders. The owner
(``is_admin``) is always Creator and is untouched.
"""
import logging

from sqlalchemy import func, or_

from ..extensions import db
from ..models import MembershipPlan, Order, User, higher_membership

log = logging.getLogger(__name__)


def _plan_for_product_id(product_id):
    if not product_id:
        return None
    key = str(product_id).strip()
    if not key:
        return None
    return (MembershipPlan.query
            .filter(or_(MembershipPlan.dodo_product_id == key,
                        MembershipPlan.ls_variant_id == key))
            .first())


def purchased_tier(email: str) -> str:
    """Highest membership tier this email owns via a paid order matching a plan."""
    if not email:
        return "none"
    rows = (db.session.query(MembershipPlan.tier)
            .join(Order, or_(
                Order.ls_variant_id == MembershipPlan.dodo_product_id,
                Order.ls_variant_id == MembershipPlan.ls_variant_id,
            ))
            .filter(Order.status == "paid",
                    func.lower(Order.buyer_email) == email.strip().lower(),
                    MembershipPlan.tier.in_(("healing", "creator")))
            .all())
    best = "none"
    for (tier,) in rows:
        best = higher_membership(best, tier)
    return best


def reconcile_user(user: User, downgrade: bool = False) -> bool:
    """Sync a user's membership column from their purchases.

    Always upgrades to a purchased tier; only lowers it when ``downgrade`` is
    True (used on refunds). Returns True if the tier changed. Never touches the
    owner. The caller commits.
    """
    if user is None:
        return False
    if user.is_admin:
        if user.membership != "creator":
            user.membership = "creator"
            return True
        return False
    tier = purchased_tier(user.email)
    current = user.membership or "none"
    new = higher_membership(current, tier)
    if downgrade:
        new = tier
    if new != current:
        user.membership = new
        log.info("membership: user %s %s -> %s", user.id, current, new)
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
    if not plan or plan.tier not in ("healing", "creator"):
        return
    reconcile_email(order.buyer_email, downgrade=(order.status != "paid"))
