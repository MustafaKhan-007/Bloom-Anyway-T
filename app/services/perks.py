"""Free membership time that comes with buying certain products.

The grant is derived from the buyer's purchases rather than stored on the
account, so it ends on its own when the months run out and disappears with a
refund — no expiry job, and nothing to clean up.
"""
from __future__ import annotations

from calendar import monthrange
from datetime import datetime

from ..models import Product, ShopPurchase, higher_membership, utcnow


def add_months(start: datetime, months: int) -> datetime:
    """``start`` plus whole calendar months, clamped to the month's length."""
    months = max(0, int(months or 0))
    total = start.month - 1 + months
    year = start.year + total // 12
    month = total % 12 + 1
    day = min(start.day, monthrange(year, month)[1])
    return start.replace(year=year, month=month, day=day)


def perk_products() -> list[Product]:
    """Catalogue products that hand out free membership months."""
    rows = (Product.query
            .filter(Product.perk_membership_tier.isnot(None),
                    Product.perk_membership_months > 0)
            .all())
    return [p for p in rows if p.has_perk()]


def purchase_has_perk(purchase: ShopPurchase) -> bool:
    products = perk_products()
    return bool(products) and _match(purchase, products) is not None


def _match(purchase: ShopPurchase, products: list[Product]) -> Product | None:
    """Same purchase → product rules the library uses, without the queries."""
    for raw in (purchase.variant_id, purchase.product_id):
        key = (raw or "").strip()
        if not key:
            continue
        for product in products:
            if key in ((product.stripe_price_id or "").strip(),
                       (product.ls_variant_id or "").strip()):
                return product
    name = (purchase.product_name or "").strip().lower()
    if name:
        for product in products:
            if (product.title or "").strip().lower() == name:
                return product
    return None


def perk_state(user) -> dict:
    """The membership perk this buyer holds right now.

    ``{"tier": "creator" | "", "until": datetime | None, "expired": bool}``.
    ``expired`` marks someone whose perk has run out and needs dropping back
    to whatever they actually pay for.
    """
    out = {"tier": "", "until": None, "expired": False}
    if user is None or not getattr(user, "id", None):
        return out

    # Reconcile runs on ordinary page loads, so look up the handful of products
    # that carry a perk once and match purchases against them in memory.
    products = perk_products()
    if not products:
        return out

    now = utcnow()
    purchases = (ShopPurchase.query
                 .filter(ShopPurchase.user_id == user.id,
                         ShopPurchase.status.in_(("linked", "removed")))
                 .all())
    best = "none"
    for purchase in purchases:
        product = _match(purchase, products)
        if product is None:
            continue
        until = add_months(purchase.purchased_at or now, product.perk_months())
        if until <= now:
            out["expired"] = True
            continue
        best = higher_membership(best, product.perk_tier())
        if out["until"] is None or until > out["until"]:
            out["until"] = until

    if best != "none":
        out["tier"] = best
        out["expired"] = False
    else:
        out["until"] = None
    return out


def perk_end_display(user) -> str:
    """Human end date for an active perk, or empty."""
    state = perk_state(user)
    if not state["tier"] or state["until"] is None:
        return ""
    try:
        return state["until"].strftime("%b %d, %Y")
    except Exception:
        return ""
