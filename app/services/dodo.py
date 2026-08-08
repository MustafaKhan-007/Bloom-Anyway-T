"""Dodo Payments: checkout sessions, webhook verification, order fulfillment."""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import time
from typing import Any
from urllib.parse import urljoin

import requests
from flask import current_app

from ..extensions import db
from ..models import MembershipPlan, Order, Product

log = logging.getLogger(__name__)

LIVE_API = "https://live.dodopayments.com"
TEST_API = "https://test.dodopayments.com"


class DodoError(RuntimeError):
    pass


def _api_base() -> str:
    mode = (current_app.config.get("DODO_PAYMENTS_MODE") or "test").strip().lower()
    if mode in ("live", "live_mode", "prod", "production"):
        return LIVE_API
    return TEST_API


def _api_key() -> str:
    return (current_app.config.get("DODO_PAYMENTS_API_KEY") or "").strip()


def configured() -> bool:
    return bool(_api_key())


def create_checkout_session(
    *,
    product_id: str,
    return_url: str,
    customer_email: str | None = None,
    customer_name: str | None = None,
    metadata: dict | None = None,
    quantity: int = 1,
) -> str:
    """Create a hosted checkout and return the checkout_url."""
    key = _api_key()
    if not key:
        raise DodoError("Dodo Payments is not configured (missing API key).")
    pid = (product_id or "").strip()
    if not pid:
        raise DodoError("Missing Dodo product id.")

    body: dict[str, Any] = {
        "product_cart": [{"product_id": pid, "quantity": max(1, int(quantity or 1))}],
        "return_url": return_url,
    }
    if customer_email or customer_name:
        customer: dict[str, str] = {}
        if customer_email:
            customer["email"] = customer_email.strip().lower()
        if customer_name:
            customer["name"] = customer_name.strip()[:120]
        body["customer"] = customer
    if metadata:
        body["metadata"] = {str(k): str(v) for k, v in metadata.items() if v is not None}

    url = urljoin(_api_base() + "/", "checkouts")
    try:
        resp = requests.post(
            url,
            json=body,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            timeout=25,
        )
    except requests.RequestException as exc:
        raise DodoError(f"Could not reach Dodo Payments: {exc}") from exc

    if resp.status_code >= 400:
        detail = (resp.text or "")[:300]
        log.warning("dodo checkout failed %s: %s", resp.status_code, detail)
        raise DodoError("Checkout could not be started. Try again in a moment.")

    data = resp.json() if resp.content else {}
    checkout_url = data.get("checkout_url") or data.get("url")
    if not checkout_url:
        raise DodoError("Dodo Payments returned no checkout URL.")
    return str(checkout_url)


def _webhook_key(secret: str) -> bytes:
    raw = (secret or "").strip()
    if raw.startswith("whsec_"):
        raw = raw[6:]
    try:
        return base64.b64decode(raw)
    except Exception:
        return raw.encode("utf-8")


def sign_webhook(secret: str, msg_id: str, timestamp: str, body: bytes) -> str:
    """Build a Standard Webhooks ``v1,…`` signature (for tests)."""
    key = _webhook_key(secret)
    to_sign = f"{msg_id}.{timestamp}.{body.decode('utf-8')}".encode("utf-8")
    digest = base64.b64encode(hmac.new(key, to_sign, hashlib.sha256).digest()).decode()
    return f"v1,{digest}"


def verify_webhook_signature(raw_body: bytes, headers: dict, secret: str | None = None) -> bool:
    """Verify Dodo / Standard Webhooks signature headers."""
    secret = secret if secret is not None else current_app.config.get("DODO_PAYMENTS_WEBHOOK_SECRET", "")
    if not secret:
        return False
    msg_id = (headers.get("webhook-id") or headers.get("Webhook-Id") or "").strip()
    msg_ts = (headers.get("webhook-timestamp") or headers.get("Webhook-Timestamp") or "").strip()
    msg_sig = (headers.get("webhook-signature") or headers.get("Webhook-Signature") or "").strip()
    if not (msg_id and msg_ts and msg_sig):
        return False
    try:
        ts = int(msg_ts)
    except ValueError:
        return False
    # Reject timestamps older than 5 minutes (clock skew).
    if abs(int(time.time()) - ts) > 300 and not current_app.config.get("TESTING"):
        return False

    key = _webhook_key(secret)
    to_sign = f"{msg_id}.{msg_ts}.{raw_body.decode('utf-8')}".encode("utf-8")
    expected = base64.b64encode(hmac.new(key, to_sign, hashlib.sha256).digest()).decode()
    for part in msg_sig.split(" "):
        part = part.strip()
        if not part:
            continue
        version, _, signature = part.partition(",")
        if version != "v1" or not signature:
            continue
        if hmac.compare_digest(expected, signature):
            return True
    return False


def _product_for_payment_id(product_id: str | None) -> Product | None:
    if not product_id:
        return None
    key = str(product_id).strip()
    if not key:
        return None
    row = Product.query.filter_by(dodo_product_id=key).first()
    if row:
        return row
    return Product.query.filter_by(ls_variant_id=key).first()


def _first_product_id(data: dict) -> str | None:
    cart = data.get("product_cart") or data.get("products") or []
    if isinstance(cart, list) and cart:
        first = cart[0] or {}
        if isinstance(first, dict):
            return first.get("product_id") or first.get("id")
    meta = data.get("metadata") or {}
    if isinstance(meta, dict):
        return meta.get("product_id") or meta.get("dodo_product_id")
    return None


def _buyer_email(data: dict) -> str:
    customer = data.get("customer") or {}
    if isinstance(customer, dict):
        email = customer.get("email") or ""
        if email:
            return str(email).strip().lower()
    return str(data.get("customer_email") or data.get("email") or "").strip().lower()


def _amount_cents(data: dict) -> int:
    for key in ("total_amount", "amount", "settlement_amount"):
        raw = data.get(key)
        if raw is None:
            continue
        try:
            return int(raw)
        except (TypeError, ValueError):
            continue
    return 0


def upsert_order_from_payment(
    *,
    payment_id: str,
    product_id: str | None,
    buyer_email: str,
    total_cents: int,
    currency: str,
    status: str,
    gift_to: str | None = None,
) -> Order:
    """Insert or update an order; idempotent on payment_id (stored as ls_order_id)."""
    order = Order.query.filter_by(ls_order_id=str(payment_id)).first()
    if order is None:
        order = Order(ls_order_id=str(payment_id))
        db.session.add(order)
    if product_id and str(product_id).strip():
        order.ls_variant_id = str(product_id).strip()
    order.buyer_email = (buyer_email or "").strip().lower()
    if gift_to:
        order.gift_to_email = gift_to.strip().lower()
    order.total_cents = int(total_cents or 0)
    order.currency = (currency or "USD").upper()[:3]
    order.status = status
    if order.ls_variant_id and order.product_id is None:
        product = _product_for_payment_id(order.ls_variant_id)
        if product:
            order.product_id = product.id
        else:
            log.warning(
                "dodo: no product with dodo_product_id=%s (payment %s)",
                order.ls_variant_id, order.ls_order_id,
            )
    from .memberships import apply_from_order
    apply_from_order(order)
    return order


def handle_payment_event(event_type: str, data: dict) -> Order | None:
    """Fulfill or refund from a Dodo payment webhook payload ``data`` object."""
    payment_id = (
        data.get("payment_id")
        or data.get("id")
        or (data.get("payment") or {}).get("payment_id")
    )
    if not payment_id:
        raise ValueError("payment_id missing from webhook data")

    product_id = _first_product_id(data)
    email = _buyer_email(data)
    currency = (data.get("currency") or "USD").upper()
    meta = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    gift_to = (meta or {}).get("gift_to") or (meta or {}).get("giftTo")

    if event_type in ("payment.succeeded", "payment.processing"):
        # Only grant on succeeded; processing is ignored for access.
        if event_type != "payment.succeeded":
            return None
        status = "paid"
    elif event_type in ("payment.failed", "payment.cancelled", "refund.succeeded",
                        "payment.refunded"):
        status = "refunded"
    else:
        return None

    if not email and status == "paid":
        raise ValueError("customer email missing from paid payment")

    order = upsert_order_from_payment(
        payment_id=str(payment_id),
        product_id=str(product_id) if product_id else None,
        buyer_email=email or "unknown@invalid",
        total_cents=_amount_cents(data),
        currency=currency,
        status=status,
        gift_to=gift_to,
    )

    # Digital goods → My Space library (skip membership-only products).
    from .shop_purchases import upsert_shop_purchase
    product = _product_for_payment_id(product_id) if product_id else None
    name = (
        (product.title if product else None)
        or (meta or {}).get("product_name")
        or "Course purchase"
    )
    upsert_shop_purchase(
        lemon_squeezy_order_id=str(payment_id),
        customer_email=email or order.buyer_email,
        product_name=name,
        product_id=str(product_id) if product_id else None,
        variant_id=str(product_id) if product_id else None,
        download_url=None,
        refunded=(status == "refunded"),
    )
    return order


def is_membership_product(product_id: str | None) -> bool:
    if not product_id:
        return False
    key = str(product_id).strip()
    if not key:
        return False
    if MembershipPlan.query.filter_by(dodo_product_id=key).first():
        return True
    return MembershipPlan.query.filter_by(ls_variant_id=key).first() is not None
