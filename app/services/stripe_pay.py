"""Stripe: Checkout Sessions, webhook verification, order fulfillment."""
from __future__ import annotations

import hashlib
import hmac
import logging
import time
from typing import Any
from urllib.parse import urlparse, urlunparse

import stripe
from flask import current_app

from ..extensions import db
from ..models import Order, Product

log = logging.getLogger(__name__)


class StripeError(RuntimeError):
    pass


def _secret_key() -> str:
    return (current_app.config.get("STRIPE_SECRET_KEY") or "").strip()


def _webhook_secret() -> str:
    return (current_app.config.get("STRIPE_WEBHOOK_SECRET") or "").strip()


def configured() -> bool:
    return bool(_secret_key())


def _configure_stripe() -> None:
    key = _secret_key()
    if not key:
        raise StripeError("Stripe is not configured (missing STRIPE_SECRET_KEY).")
    stripe.api_key = key


def _cancel_url_from_success(success_url: str) -> str:
    """Best-effort cancel URL (same origin, drop purchase flags)."""
    try:
        parts = urlparse(success_url)
        path = parts.path or "/"
        if path.startswith("/account"):
            path = "/membership" if "membership" in (parts.query or "") else "/courses"
        if "/membership" in success_url or "tier" in (parts.query or ""):
            path = "/membership"
        return urlunparse((parts.scheme, parts.netloc, path, "", "", ""))
    except Exception:
        return success_url


def create_checkout_session(
    *,
    product_id: str,
    return_url: str,
    customer_email: str | None = None,
    customer_name: str | None = None,
    metadata: dict | None = None,
    quantity: int = 1,
) -> str:
    """Create a Stripe Checkout Session and return the hosted URL.

    ``product_id`` is a Stripe Price id (``price_…``).
    Memberships use ``mode=subscription``; courses/guides use ``mode=payment``.
    """
    _configure_stripe()
    price_id = (product_id or "").strip()
    if not price_id:
        raise StripeError("Missing Stripe price id.")

    meta = {str(k): str(v) for k, v in (metadata or {}).items() if v is not None}
    meta["price_id"] = price_id
    kind = (meta.get("kind") or "").strip().lower()
    mode = "subscription" if kind == "membership" else "payment"

    success = (return_url or "").strip()
    if "session_id=" not in success:
        joiner = "&" if "?" in success else "?"
        success = f"{success}{joiner}session_id={{CHECKOUT_SESSION_ID}}"

    params: dict[str, Any] = {
        "mode": mode,
        "line_items": [{"price": price_id, "quantity": max(1, int(quantity or 1))}],
        "success_url": success,
        "cancel_url": _cancel_url_from_success(return_url),
        "metadata": meta,
        "allow_promotion_codes": True,
    }
    if customer_email:
        params["customer_email"] = customer_email.strip().lower()
    if customer_name:
        params["metadata"]["customer_name"] = customer_name.strip()[:120]
    if mode == "subscription":
        params["subscription_data"] = {"metadata": meta}

    try:
        session = stripe.checkout.Session.create(**params)
    except Exception as exc:
        log.warning("stripe checkout failed: %s", exc)
        raise StripeError(_friendly_checkout_error(exc, price_id)) from exc

    url = getattr(session, "url", None)
    if not url:
        raise StripeError("Stripe returned no checkout URL.")
    return str(url)


def _friendly_checkout_error(exc: Exception, price_id: str) -> str:
    """Turn opaque Stripe failures into something an owner can act on."""
    msg = str(exc or "").strip()
    low = msg.lower()
    pid = (price_id or "").strip()

    if pid and not pid.startswith("price_"):
        return (
            "Checkout needs a Stripe Price ID (starts with price_...), "
            "not a Product ID. In Stripe: Product -> open the price -> copy its ID, "
            "then paste that into Studio."
        )
    if "no such price" in low or ("no such" in low and "price" in low):
        return (
            "Stripe doesn't recognize that Price ID. Check it in the Stripe Dashboard, "
            "and make sure you're using test keys with test prices (or live with live)."
        )
    if "no such product" in low:
        return (
            "That looks like a Product ID. Create/open a Price under the product in Stripe "
            "and paste the price_... ID into Studio instead."
        )
    if "invalid api key" in low or "invalid api_key" in low:
        return "Stripe rejected the secret key. Double-check STRIPE_SECRET_KEY on Render."
    if "mode" in low and ("subscription" in low or "recurring" in low
                          or "one.time" in low or "one-time" in low):
        return (
            "That Price's billing type doesn't match this checkout "
            "(courses need a one-time price; memberships need a recurring price)."
        )
    if msg:
        short = msg.split("\n", 1)[0].strip()
        if len(short) > 180:
            short = short[:177] + "..."
        return f"Checkout could not be started: {short}"
    return "Checkout could not be started. Try again in a moment."


def sign_webhook(secret: str, payload: bytes, timestamp: int | None = None) -> str:
    """Build a Stripe-Signature header value (for tests)."""
    ts = int(timestamp if timestamp is not None else time.time())
    signed = f"{ts}.{payload.decode('utf-8')}".encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    return f"t={ts},v1={digest}"


def verify_webhook_signature(raw_body: bytes, headers: dict, secret: str | None = None) -> bool:
    """Verify Stripe-Signature header. Returns True when valid."""
    secret = secret if secret is not None else _webhook_secret()
    if not secret:
        return False
    sig_header = (
        headers.get("stripe-signature")
        or headers.get("Stripe-Signature")
        or ""
    ).strip()
    if not sig_header:
        return False
    try:
        parts = {}
        for piece in sig_header.split(","):
            k, _, v = piece.partition("=")
            parts.setdefault(k.strip(), []).append(v.strip())
        ts = int((parts.get("t") or [""])[0])
        if abs(int(time.time()) - ts) > 300 and not current_app.config.get("TESTING"):
            return False
        signed = f"{ts}.{raw_body.decode('utf-8')}".encode("utf-8")
        expected = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
        for candidate in parts.get("v1") or []:
            if hmac.compare_digest(expected, candidate):
                return True
    except Exception:
        return False
    return False


def construct_event(raw_body: bytes, headers: dict, secret: str | None = None):
    """Parse and verify a Stripe webhook into an Event-like dict."""
    secret = secret if secret is not None else _webhook_secret()
    sig_header = (
        headers.get("stripe-signature")
        or headers.get("Stripe-Signature")
        or ""
    ).strip()
    if not secret or not sig_header:
        raise StripeError("Missing webhook secret or signature.")
    if not verify_webhook_signature(raw_body, headers, secret=secret):
        raise StripeError("Invalid Stripe webhook signature.")
    import json
    payload = json.loads(raw_body.decode("utf-8"))
    if not isinstance(payload, dict):
        raise StripeError("Invalid webhook payload.")
    return payload


def _product_for_price_id(price_id: str | None) -> Product | None:
    if not price_id:
        return None
    key = str(price_id).strip()
    if not key:
        return None
    row = Product.query.filter_by(stripe_price_id=key).first()
    if row:
        return row
    return Product.query.filter_by(ls_variant_id=key).first()


def _product_from_metadata(data: dict) -> Product | None:
    meta = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    slug = str((meta or {}).get("slug") or "").strip()
    if not slug:
        return None
    return Product.query.filter_by(slug=slug).first()


def _resolve_product(data: dict, price_id: str | None) -> Product | None:
    return _product_for_price_id(price_id) or _product_from_metadata(data)


def _first_price_id(data: dict) -> str | None:
    meta = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    if isinstance(meta, dict):
        pid = meta.get("price_id") or meta.get("product_id")
        if pid:
            return str(pid)
    cart = data.get("product_cart") or data.get("line_items") or []
    if isinstance(cart, list) and cart:
        first = cart[0] or {}
        if isinstance(first, dict):
            pid = first.get("price") or first.get("product_id") or first.get("id")
            if isinstance(pid, dict):
                pid = pid.get("id")
            if pid:
                return str(pid)
    product = _product_from_metadata(data)
    if product and (product.stripe_price_id or "").strip():
        return product.stripe_price_id.strip()
    return None


def _buyer_email(data: dict) -> str:
    customer = data.get("customer") or {}
    if isinstance(customer, dict):
        email = customer.get("email") or ""
        if email:
            return str(email).strip().lower()
    details = data.get("customer_details") or {}
    if isinstance(details, dict) and details.get("email"):
        return str(details["email"]).strip().lower()
    billing = data.get("billing_details") or {}
    if isinstance(billing, dict) and billing.get("email"):
        return str(billing["email"]).strip().lower()
    for key in ("customer_email", "email", "billing_email"):
        raw = data.get(key)
        if raw:
            return str(raw).strip().lower()
    return ""


def _amount_cents(data: dict) -> int:
    for key in ("amount_total", "total_amount", "amount"):
        raw = data.get(key)
        if raw is None:
            continue
        try:
            return int(raw)
        except (TypeError, ValueError):
            continue
    return 0


def _as_dict(obj) -> dict:
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "to_dict_recursive"):
        return obj.to_dict_recursive()
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    try:
        return dict(obj)
    except Exception:
        return {}


def _stripe_id(value) -> str | None:
    """Normalize a Stripe id that may arrive as a string or expanded object."""
    if value is None:
        return None
    if isinstance(value, str):
        key = value.strip()
        return key or None
    if isinstance(value, dict):
        return _stripe_id(value.get("id"))
    return _stripe_id(getattr(value, "id", None))


def _session_should_fulfill(session: dict) -> bool:
    """True when a Checkout Session should grant access (incl. $0 / 100% off)."""
    status = (session.get("status") or "").strip().lower()
    if status and status not in ("complete", "completed"):
        return False
    ps = (session.get("payment_status") or "").strip().lower()
    if ps in ("paid", "no_payment_required"):
        return True
    # Fully discounted sessions sometimes omit payment_status; still fulfill.
    try:
        amount = int(session.get("amount_total") if session.get("amount_total") is not None else -1)
    except (TypeError, ValueError):
        amount = -1
    if amount == 0 and (not status or status in ("complete", "completed")):
        return True
    return False


def _session_to_payment_data(session) -> dict:
    """Normalize a Checkout Session into our fulfillment shape."""
    session = _as_dict(session)
    meta = session.get("metadata") if isinstance(session.get("metadata"), dict) else {}
    price_id = (meta or {}).get("price_id")
    if not price_id:
        items = session.get("line_items") or {}
        items = _as_dict(items)
        data_items = items.get("data") if isinstance(items, dict) else items
        if isinstance(data_items, list) and data_items:
            first = _as_dict(data_items[0])
            price = first.get("price")
            if isinstance(price, dict):
                price_id = price.get("id")
            elif price:
                price_id = price
    email = _buyer_email(session)
    payment_id = (
        _stripe_id(session.get("payment_intent"))
        or _stripe_id(session.get("subscription"))
        or _stripe_id(session.get("id"))
    )
    return {
        "payment_id": str(payment_id) if payment_id else "",
        "total_amount": session.get("amount_total") or 0,
        "currency": (session.get("currency") or "usd").upper(),
        "customer": {"email": email},
        "customer_email": email,
        "customer_details": session.get("customer_details") or {},
        "product_cart": [{"product_id": str(price_id), "quantity": 1}] if price_id else [],
        "metadata": dict(meta or {}),
        "payment_status": session.get("payment_status"),
        "mode": session.get("mode"),
        "id": _stripe_id(session.get("id")) or session.get("id"),
    }


def stripe_event_to_internal(event_type: str, obj: dict) -> tuple[str | None, dict]:
    """Map a Stripe event type + object into (internal_event, payment_data)."""
    if event_type in (
        "checkout.session.completed",
        "checkout.session.async_payment_succeeded",
    ):
        data = _session_to_payment_data(obj)
        if not _session_should_fulfill(obj):
            return None, data
        return "payment.succeeded", data
    if event_type == "invoice.paid":
        # Subscription first invoice can be $0 with a 100% promo — still grant access.
        meta = obj.get("metadata") if isinstance(obj.get("metadata"), dict) else {}
        lines = (obj.get("lines") or {}).get("data") or []
        price_id = (meta or {}).get("price_id")
        if not price_id and lines:
            price = (lines[0].get("price") or {})
            price_id = price.get("id") if isinstance(price, dict) else None
            if not price_id and isinstance(lines[0].get("pricing"), dict):
                # newer invoice line shape
                price_details = (lines[0].get("pricing") or {}).get("price_details") or {}
                price_id = price_details.get("price")
        email = ""
        cust = obj.get("customer_email")
        if cust:
            email = str(cust).strip().lower()
        if not email:
            email = _buyer_email(obj)
        payment_id = (
            _stripe_id(obj.get("payment_intent"))
            or _stripe_id(obj.get("subscription"))
            or _stripe_id(obj.get("id"))
        )
        amount = obj.get("amount_paid")
        if amount is None:
            amount = obj.get("total") or 0
        return "payment.succeeded", {
            "payment_id": str(payment_id) if payment_id else "",
            "total_amount": amount or 0,
            "currency": (obj.get("currency") or "usd").upper(),
            "customer": {"email": email},
            "customer_email": email,
            "product_cart": [{"product_id": str(price_id), "quantity": 1}] if price_id else [],
            "metadata": dict(meta or {}),
        }
    if event_type == "invoice.payment_failed":
        meta = obj.get("metadata") if isinstance(obj.get("metadata"), dict) else {}
        lines = (obj.get("lines") or {}).get("data") or []
        price_id = None
        if lines:
            price = (lines[0].get("price") or {})
            price_id = price.get("id") if isinstance(price, dict) else None
        email = ""
        cust = obj.get("customer_email")
        if cust:
            email = str(cust).strip().lower()
        return "payment.failed", {
            "payment_id": str(
                _stripe_id(obj.get("payment_intent")) or _stripe_id(obj.get("id")) or ""
            ),
            "total_amount": obj.get("amount_due") or 0,
            "currency": (obj.get("currency") or "usd").upper(),
            "customer": {"email": email},
            "product_cart": [{"product_id": price_id, "quantity": 1}] if price_id else [],
            "metadata": dict(meta or {}),
        }
    if event_type in ("charge.refunded", "charge.refund.updated"):
        pi = _stripe_id(obj.get("payment_intent"))
        return "payment.refunded", {
            "payment_id": str(pi or _stripe_id(obj.get("id")) or ""),
            "total_amount": obj.get("amount_refunded") or obj.get("amount") or 0,
            "currency": (obj.get("currency") or "usd").upper(),
            "customer": {"email": _buyer_email(obj)},
            "product_cart": [],
            "metadata": obj.get("metadata") if isinstance(obj.get("metadata"), dict) else {},
        }
    if event_type == "customer.subscription.deleted":
        meta = obj.get("metadata") if isinstance(obj.get("metadata"), dict) else {}
        price_id = (meta or {}).get("price_id")
        items = (obj.get("items") or {}).get("data") or []
        if not price_id and items:
            price = (items[0].get("price") or {})
            price_id = price.get("id") if isinstance(price, dict) else None
        return "payment.refunded", {
            "payment_id": str(_stripe_id(obj.get("id")) or ""),
            "total_amount": 0,
            "currency": "USD",
            "customer": {"email": ""},
            "product_cart": [{"product_id": price_id, "quantity": 1}] if price_id else [],
            "metadata": dict(meta or {}),
        }
    return None, {}


def fulfill_checkout_session_id(session_id: str) -> Order | None:
    """Retrieve a Checkout Session by id and fulfill it (webhook backup / $0 codes)."""
    sid = (session_id or "").strip()
    if not sid or not configured():
        return None
    if current_app.config.get("TESTING"):
        return None
    _configure_stripe()
    try:
        full = stripe.checkout.Session.retrieve(sid, expand=["line_items"])
    except Exception as exc:
        log.warning("stripe: could not retrieve session %s: %s", sid, exc)
        return None
    session = _as_dict(full)
    if not _session_should_fulfill(session):
        log.info(
            "stripe: session %s not ready to fulfill (status=%s payment_status=%s)",
            sid, session.get("status"), session.get("payment_status"),
        )
        return None
    data = _session_to_payment_data(session)
    if not data.get("payment_id"):
        return None
    return handle_payment_event("payment.succeeded", data)


def sync_recent_payments(*, days: int = 60, max_pages: int = 3) -> dict:
    """Pull recent completed Checkout Sessions and fulfill any missing locally."""
    if not configured():
        return {"ok": False, "error": "not_configured", "imported": 0, "checked": 0}
    if current_app.config.get("TESTING"):
        return {"ok": True, "imported": 0, "checked": 0, "errors": 0, "skipped": "testing"}

    from datetime import datetime, timedelta, timezone

    _configure_stripe()
    since = datetime.now(timezone.utc) - timedelta(days=max(1, int(days or 60)))
    created_gte = int(since.timestamp())
    checked = 0
    imported = 0
    errors = 0

    starting_after = None
    for _ in range(max(1, int(max_pages or 1))):
        try:
            kwargs: dict[str, Any] = {
                "limit": 50,
                "created": {"gte": created_gte},
                "status": "complete",
            }
            if starting_after:
                kwargs["starting_after"] = starting_after
            page = stripe.checkout.Session.list(**kwargs)
        except Exception as exc:
            log.warning("stripe sync list failed: %s", exc)
            return {
                "ok": False,
                "error": str(exc),
                "imported": imported,
                "checked": checked,
            }
        items = list(page.data or [])
        if not items:
            break
        for session in items:
            checked += 1
            starting_after = session.id
            try:
                full = stripe.checkout.Session.retrieve(
                    session.id, expand=["line_items"]
                )
                data = _session_to_payment_data(full)
                payment_id = data.get("payment_id")
                if not payment_id:
                    continue
                before = Order.query.filter_by(ls_order_id=str(payment_id)).first()
                was_new = before is None or before.status != "paid"
                if not _session_should_fulfill(_as_dict(full)):
                    continue
                handle_payment_event("payment.succeeded", data)
                db.session.commit()
                if was_new:
                    imported += 1
            except Exception:
                errors += 1
                db.session.rollback()
                log.exception("stripe sync: failed to fulfill %s", session.id)
        if len(items) < 50:
            break

    log.info(
        "stripe sync: checked=%s imported=%s errors=%s",
        checked, imported, errors,
    )
    return {
        "ok": True,
        "imported": imported,
        "checked": checked,
        "errors": errors,
    }


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
    email_norm = (buyer_email or "").strip().lower()
    if email_norm and "@" in email_norm and not email_norm.endswith("@invalid"):
        order.buyer_email = email_norm
    elif not order.buyer_email:
        order.buyer_email = email_norm or "unknown@invalid"
    if gift_to:
        order.gift_to_email = gift_to.strip().lower()
    order.total_cents = int(total_cents or 0)
    order.currency = (currency or "USD").upper()[:3]
    order.status = status
    if order.ls_variant_id and order.product_id is None:
        product = _product_for_price_id(order.ls_variant_id)
        if product:
            order.product_id = product.id
        else:
            log.warning(
                "stripe: no product with stripe_price_id=%s (payment %s)",
                order.ls_variant_id, order.ls_order_id,
            )
    from .memberships import apply_from_order
    apply_from_order(order)
    return order


def handle_payment_event(event_type: str, data: dict) -> Order | None:
    """Fulfill or refund from a normalized payment payload."""
    from datetime import timedelta

    from sqlalchemy import func

    from ..models import User, utcnow
    from .memberships import _plan_for_product_id

    payment_id = (
        data.get("payment_id")
        or data.get("id")
        or (data.get("payment") or {}).get("payment_id")
    )
    if not payment_id:
        raise ValueError("payment_id missing from webhook data")

    product_id = _first_price_id(data)
    email = _buyer_email(data)
    currency = (data.get("currency") or "USD").upper()
    meta = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    gift_to = (meta or {}).get("gift_to") or (meta or {}).get("giftTo")

    if event_type in ("payment.succeeded", "payment.processing"):
        if event_type != "payment.succeeded":
            return None
        status = "paid"
    elif event_type == "payment.failed":
        status = "failed"
    elif event_type in ("payment.cancelled", "refund.succeeded", "payment.refunded"):
        status = "refunded"
    else:
        return None

    if not email and status in ("paid", "failed"):
        if status == "paid":
            raise ValueError("customer email missing from paid payment")
        log.warning("stripe: payment.failed missing customer email (%s)", payment_id)
        return None

    prior = Order.query.filter_by(ls_order_id=str(payment_id)).first()
    send_receipt = status == "paid" and (prior is None or prior.status != "paid")
    send_decline = (
        status == "failed"
        and (prior is None or prior.status != "failed")
    )

    plan = _plan_for_product_id(product_id) if product_id else None
    prev_tier = "none"
    if email:
        buyer = (User.query
                 .filter(func.lower(User.email) == email.strip().lower(),
                         User.deleted_at.is_(None))
                 .first())
        if buyer:
            prev_tier = buyer.effective_membership()

    order = upsert_order_from_payment(
        payment_id=str(payment_id),
        product_id=str(product_id) if product_id else None,
        buyer_email=email or "unknown@invalid",
        total_cents=_amount_cents(data),
        currency=currency,
        status=status,
        gift_to=gift_to,
    )

    product = _resolve_product(data, product_id)
    if product and order.product_id is None:
        order.product_id = product.id
        if not order.ls_variant_id and (product.stripe_price_id or "").strip():
            order.ls_variant_id = product.stripe_price_id.strip()

    name = (
        (product.title if product else None)
        or (plan.name if plan else None)
        or (meta or {}).get("product_name")
        or "Course purchase"
    )

    from .shop_purchases import upsert_shop_purchase
    if status == "paid":
        upsert_shop_purchase(
            lemon_squeezy_order_id=str(payment_id),
            customer_email=email or order.buyer_email,
            product_name=name,
            product_id=str(product_id) if product_id else None,
            variant_id=str(product_id) if product_id else None,
            download_url=None,
            refunded=False,
        )
    elif status == "refunded":
        upsert_shop_purchase(
            lemon_squeezy_order_id=str(payment_id),
            customer_email=email or order.buyer_email,
            product_name=name,
            product_id=str(product_id) if product_id else None,
            variant_id=str(product_id) if product_id else None,
            download_url=None,
            refunded=True,
        )

    if send_receipt and order.buyer_email and "@" in order.buyer_email:
        try:
            from .mailer import send_order_receipt
            when = order.created_at
            order_date = when.strftime("%b %d, %Y") if when else ""
            send_order_receipt(
                order.buyer_email,
                order_id=order.ls_order_id,
                product_name=name,
                amount=order.total_display(),
                order_date=order_date,
            )
        except Exception:
            log.exception("Order receipt email failed for %s", order.ls_order_id)

    if (send_receipt and plan and plan.tier in ("healing", "creator", "full_bloom")
            and order.buyer_email and "@" in order.buyer_email):
        already = (
            (plan.tier == "healing" and prev_tier in ("healing", "creator", "full_bloom"))
            or (plan.tier == "creator" and prev_tier in ("creator", "full_bloom"))
            or (plan.tier == "full_bloom" and prev_tier == "full_bloom")
        )
        if not already and plan.tier in ("healing", "creator"):
            try:
                from .mailer import send_creator_welcome, send_healing_welcome
                key = str(product_id or "").strip()
                annual_id = (plan.stripe_price_id_annual or "").strip()
                is_annual = bool(annual_id and key == annual_id)
                if is_annual:
                    billing_interval = "annually"
                    plan_price = plan.annual_price_display() or order.total_display()
                else:
                    billing_interval = "monthly"
                    plan_price = plan.price_display() or order.total_display()
                trial_days = 14 if plan.tier == "healing" else 7
                trial_end = (utcnow() + timedelta(days=trial_days)).strftime("%b %d, %Y")
                sender = send_healing_welcome if plan.tier == "healing" else send_creator_welcome
                sender(
                    order.buyer_email,
                    trial_end_date=trial_end,
                    plan_price=plan_price,
                    billing_interval=billing_interval,
                )
            except Exception:
                log.exception(
                    "%s welcome email failed for %s",
                    plan.tier.title(), order.ls_order_id,
                )

    if send_decline and plan and plan.tier in ("healing", "creator", "full_bloom"):
        to = (email or order.buyer_email or "").strip()
        if to and "@" in to:
            try:
                from .mailer import send_card_declined
                grace = current_app.config.get("MEMBERSHIP_GRACE_DAYS") or 3
                plan_name = plan.name or f"{plan.tier.replace('_', ' ').title()} membership"
                send_card_declined(
                    to,
                    plan_name=plan_name,
                    grace_days=grace,
                )
            except Exception:
                log.exception("Card-declined email failed for %s", payment_id)

    return order
