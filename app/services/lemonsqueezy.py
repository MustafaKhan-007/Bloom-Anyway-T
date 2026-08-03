"""Lemon Squeezy order helpers used by the webhook.

Webhooks are the source of truth for purchases and membership grants.
"""
import logging

from ..extensions import db
from ..models import Order, Product

log = logging.getLogger(__name__)


def _product_for_variant(variant_id: str | None) -> Product | None:
    """Match a store product by Lemon variant ID (string-normalized)."""
    if not variant_id:
        return None
    key = str(variant_id).strip()
    if not key:
        return None
    return Product.query.filter_by(ls_variant_id=key).first()


def upsert_order(ls_order_id: str, ls_variant_id: str | None, buyer_email: str,
                 total_cents: int, currency: str, status: str, created_at=None,
                 gift_to: str | None = None) -> Order:
    """Insert or update an order row; idempotent on ls_order_id.

    When the variant matches a Studio product, ``product_id`` is set so the
    purchase appears in the buyer's My space library (read online — no download).
    """
    order = Order.query.filter_by(ls_order_id=str(ls_order_id)).first()
    if order is None:
        order = Order(ls_order_id=str(ls_order_id))
        db.session.add(order)
    if ls_variant_id is not None and str(ls_variant_id).strip():
        order.ls_variant_id = str(ls_variant_id).strip()
    order.buyer_email = (buyer_email or "").strip().lower()
    if gift_to:
        order.gift_to_email = gift_to.strip().lower()
    order.total_cents = total_cents
    order.currency = (currency or "USD").upper()
    order.status = status
    if created_at is not None:
        order.created_at = created_at
    if order.ls_variant_id and order.product_id is None:
        product = _product_for_variant(order.ls_variant_id)
        if product:
            order.product_id = product.id
        else:
            log.warning("webhook: no product with ls_variant_id=%s "
                        "(order %s won't appear in My space until it's set)",
                        order.ls_variant_id, order.ls_order_id)
    # grant/revoke membership when the purchased variant is a membership plan
    from .memberships import apply_from_order
    apply_from_order(order)
    return order
