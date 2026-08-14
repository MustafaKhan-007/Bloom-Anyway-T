"""Digital purchase fulfillment for My Space (Dodo Payments)."""
from datetime import datetime

from sqlalchemy import func, or_

from ..extensions import db
from ..models import MembershipPlan, ShopPurchase, User, utcnow


def _norm_email(email: str) -> str:
    return (email or "").strip().lower()


def is_membership_variant(variant_id) -> bool:
    """True when this product id is a membership plan (not a course/guide)."""
    if variant_id is None:
        return False
    key = str(variant_id).strip()
    if not key:
        return False
    return (MembershipPlan.query
            .filter(or_(MembershipPlan.dodo_product_id == key,
                        MembershipPlan.dodo_product_id_annual == key,
                        MembershipPlan.ls_variant_id == key))
            .first()) is not None


def upsert_shop_purchase(
    *,
    lemon_squeezy_order_id: str,
    customer_email: str,
    product_name: str | None = None,
    product_id: str | None = None,
    variant_id: str | None = None,
    download_url: str | None = None,
    purchased_at: datetime | None = None,
    refunded: bool = False,
) -> ShopPurchase | None:
    """Create or update a shop purchase. Idempotent on lemon_squeezy_order_id.

    Skips membership-plan variants (those stay on the Order + membership path).
    Returns None when the variant is a membership (no ShopPurchase row).
    """
    order_id = str(lemon_squeezy_order_id or "").strip()
    if not order_id:
        raise ValueError("lemon_squeezy_order_id is required")

    email = _norm_email(customer_email)
    if not email:
        raise ValueError("customer_email is required")

    row = ShopPurchase.query.filter_by(lemon_squeezy_order_id=order_id).first()

    # Membership plans stay on the Order + membership path — never create a
    # ShopPurchase for them. Still allow refunds to mark an existing row.
    if is_membership_variant(variant_id) and row is None:
        return None

    if refunded:
        if row is None:
            # Refund before we ever saw the order — record it as refunded.
            row = ShopPurchase(
                lemon_squeezy_order_id=order_id,
                customer_email=email,
                product_name=(product_name or "").strip()[:200] or "Shop purchase",
                product_id=str(product_id).strip()[:80] if product_id else None,
                variant_id=str(variant_id).strip()[:80] if variant_id else None,
                download_url=(download_url or "").strip()[:1000] or None,
                purchased_at=purchased_at or utcnow(),
                status="refunded",
            )
            db.session.add(row)
        else:
            row.status = "refunded"
        return row

    # Idempotency: keep an existing non-refunded row, but still try to link
    # pending purchases and refresh the display name when we learn more.
    if row is not None:
        if product_name:
            cleaned = (product_name or "").strip()[:200]
            if cleaned:
                row.product_name = cleaned
        if row.status != "refunded" and (row.user_id is None or row.status == "pending_link"):
            user = (User.query
                    .filter(func.lower(User.email) == email, User.deleted_at.is_(None))
                    .first())
            if user:
                row.user_id = user.id
                row.status = "linked"
        return row

    user = (User.query
            .filter(func.lower(User.email) == email, User.deleted_at.is_(None))
            .first())
    row = ShopPurchase(
        lemon_squeezy_order_id=order_id,
        customer_email=email,
        user_id=user.id if user else None,
        product_name=(product_name or "").strip()[:200] or "Shop purchase",
        product_id=str(product_id).strip()[:80] if product_id else None,
        variant_id=str(variant_id).strip()[:80] if variant_id else None,
        download_url=(download_url or "").strip()[:1000] or None,
        purchased_at=purchased_at or utcnow(),
        status="linked" if user else "pending_link",
    )
    db.session.add(row)
    return row


def link_pending_purchases(user: User) -> int:
    """Attach pending shop purchases for this email. Returns how many were linked."""
    if user is None or not user.email:
        return 0
    email = _norm_email(user.email)
    pending = (ShopPurchase.query
               .filter(func.lower(ShopPurchase.customer_email) == email,
                       ShopPurchase.status == "pending_link")
               .all())
    for row in pending:
        row.user_id = user.id
        row.status = "linked"
    return len(pending)


def linked_purchases_for(user: User):
    """Shop purchases shown in My Space (linked only)."""
    if user is None or not getattr(user, "is_authenticated", False):
        return []
    return (ShopPurchase.query
            .filter_by(user_id=user.id, status="linked")
            .order_by(ShopPurchase.purchased_at.desc())
            .all())
