"""Lemon Squeezy webhook receiver.

Verifies X-Signature (HMAC-SHA256 of the raw body with the webhook secret),
handles order_created / order_refunded, and is idempotent on ls_order_id.
Also records shop downloads (Purchase) for the external storefront.
"""
import hashlib
import hmac
import json
import logging

from flask import current_app, request

from ..extensions import db
from ..services.lemonsqueezy import upsert_order
from ..services.purchases import upsert_purchase
from . import bp

log = logging.getLogger(__name__)

HANDLED_EVENTS = {"order_created", "order_refunded"}


def _signature_valid(raw_body: bytes, signature: str) -> bool:
    secret = current_app.config["LEMONSQUEEZY_WEBHOOK_SECRET"]
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.strip())


@bp.route("/lemonsqueezy", methods=["POST"])
def lemonsqueezy():
    # Raw body for HMAC — do not rely on Flask's JSON cache for signing.
    raw = request.get_data()
    if not _signature_valid(raw, request.headers.get("X-Signature", "")):
        log.warning("webhook: invalid signature (ip=%s)", request.remote_addr)
        return {"error": "invalid signature"}, 401

    try:
        payload = json.loads(raw.decode("utf-8") or "{}")
    except (UnicodeDecodeError, ValueError):
        log.warning("webhook: malformed JSON body")
        return {"error": "malformed payload"}, 400

    if not isinstance(payload, dict):
        return {"error": "malformed payload"}, 400

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

        order_id = data.get("id")
        buyer_email = attrs.get("user_email") or ""
        variant_id = first_item.get("variant_id")
        product_id = first_item.get("product_id")
        product_name = first_item.get("product_name") or first_item.get("variant_name") or ""

        # Studio / membership products (matched by Product.ls_variant_id)
        upsert_order(
            ls_order_id=order_id,
            ls_variant_id=variant_id,
            buyer_email=buyer_email,
            total_cents=int(attrs.get("total") or 0),
            currency=attrs.get("currency") or "USD",
            status=status,
            gift_to=gift_to,
        )

        # External shop downloads (shop.bloomanyway.online → My space)
        purchase_status = "refunded" if event == "order_refunded" else str(status).lower()
        if purchase_status in ("paid", "refunded"):
            upsert_purchase(
                order_id=str(order_id) if order_id is not None else "",
                email=buyer_email,
                product_id=str(product_id) if product_id is not None else None,
                variant_id=str(variant_id) if variant_id is not None else None,
                product_name=product_name,
                status=purchase_status,
            )

        db.session.commit()
        log.info("webhook: %s processed (order %s)", event, order_id)
        return {"status": "ok"}, 200
    except Exception:
        db.session.rollback()
        log.exception("webhook: failed to process %s", event)
        return {"error": "processing failed"}, 500
