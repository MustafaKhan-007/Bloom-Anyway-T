"""Lemon Squeezy webhook receiver.

Verifies X-Signature (HMAC-SHA256 of the raw body with the webhook secret),
handles order_created / order_refunded, and is idempotent on ls_order_id.

Also fulfills shop.bloomanyway.online digital purchases into ShopPurchase rows
for My Space (separate from legacy on-site Product/Order matching).
"""
import hashlib
import hmac
import logging
from datetime import datetime

from flask import current_app, request

from ..extensions import db
from ..services.lemonsqueezy import upsert_order
from ..services.shop_purchases import upsert_shop_purchase
from . import bp

log = logging.getLogger(__name__)

HANDLED_EVENTS = {"order_created", "order_refunded"}


def _signature_valid(raw_body: bytes, signature: str) -> bool:
    secret = current_app.config["LEMONSQUEEZY_WEBHOOK_SECRET"]
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.strip())


def _parse_purchased_at(attrs: dict):
    raw = attrs.get("created_at") or attrs.get("createdAt")
    if not raw or not isinstance(raw, str):
        return None
    try:
        # Lemon sends ISO-8601, often with Z
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


@bp.route("/lemonsqueezy", methods=["POST"])
def lemonsqueezy():
    raw = request.get_data()
    if not _signature_valid(raw, request.headers.get("X-Signature", "")):
        log.warning("webhook: invalid signature (ip=%s)", request.remote_addr)
        return {"error": "invalid signature"}, 401

    payload = request.get_json(silent=True) or {}
    event = (
        request.headers.get("X-Event-Name")
        or (payload.get("meta") or {}).get("event_name")
        or ""
    )
    if event not in HANDLED_EVENTS:
        return {"status": "ignored", "event": event}, 200

    try:
        data = payload.get("data") or {}
        attrs = data.get("attributes") or {}
        first_item = attrs.get("first_order_item") or {}
        status = attrs.get("status") or ("refunded" if event == "order_refunded" else "paid")
        # Lemon may put custom fields on meta and/or attributes
        custom = {}
        custom.update((payload.get("meta") or {}).get("custom_data") or {})
        custom.update(attrs.get("custom_data") or {})
        gift_to = custom.get("gift_to") or custom.get("giftTo") or None

        upsert_order(
            ls_order_id=data.get("id"),
            ls_variant_id=first_item.get("variant_id"),
            buyer_email=attrs.get("user_email") or "",
            total_cents=int(attrs.get("total") or 0),
            currency=attrs.get("currency") or "USD",
            status=status,
            gift_to=gift_to,
        )

        # Shop storefront fulfillment for My Space downloads.
        # Lemon does not put a stable signed file URL on order webhooks; the
        # order receipt URL is the durable customer-facing download entry point.
        urls = attrs.get("urls") or {}
        product_name = (
            first_item.get("product_name")
            or first_item.get("variant_name")
            or attrs.get("first_order_item_name")
            or "Shop purchase"
        )
        upsert_shop_purchase(
            lemon_squeezy_order_id=data.get("id"),
            customer_email=attrs.get("user_email") or "",
            product_name=product_name,
            product_id=first_item.get("product_id"),
            variant_id=first_item.get("variant_id"),
            download_url=urls.get("receipt") or None,
            purchased_at=_parse_purchased_at(attrs),
            refunded=(event == "order_refunded" or status == "refunded"),
        )

        db.session.commit()
        log.info("webhook: %s processed (order %s)", event, data.get("id"))
        return {"status": "ok"}, 200
    except Exception:
        db.session.rollback()
        log.exception("webhook: failed to process %s", event)
        return {"error": "processing failed"}, 500
