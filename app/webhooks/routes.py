"""Dodo Payments webhook receiver.

Verifies Standard Webhooks signatures, handles payment.succeeded /
refund.succeeded, and is idempotent on payment_id.
"""
import logging

from flask import current_app, request

from ..extensions import db
from ..services import dodo as dodo_svc
from . import bp

log = logging.getLogger(__name__)

HANDLED = {
    "payment.succeeded",
    "payment.failed",
    "refund.succeeded",
    "payment.refunded",
}


@bp.route("/dodo", methods=["POST"])
@bp.route("/dodopayments", methods=["POST"])
def dodo_payments():
    raw = request.get_data()
    headers = {k.lower(): v for k, v in request.headers.items()}
    if not dodo_svc.verify_webhook_signature(raw, headers):
        log.warning("dodo webhook: invalid signature (ip=%s)", request.remote_addr)
        return {"error": "invalid signature"}, 401

    payload = request.get_json(silent=True) or {}
    event = (payload.get("type") or payload.get("event_type") or "").strip()
    if event not in HANDLED:
        return {"status": "ignored", "event": event}, 200

    data = payload.get("data") or {}
    if not isinstance(data, dict):
        return {"error": "invalid payload"}, 400

    try:
        dodo_svc.handle_payment_event(event, data)
        db.session.commit()
        log.info("dodo webhook: %s processed (payment %s)",
                 event, data.get("payment_id") or data.get("id"))
        return {"status": "ok"}, 200
    except Exception:
        db.session.rollback()
        log.exception("dodo webhook: failed to process %s", event)
        return {"error": "processing failed"}, 500


# Legacy Lemon path kept only to return a clear 410 so old LS webhooks fail loudly.
@bp.route("/lemonsqueezy", methods=["POST"])
def lemonsqueezy_retired():
    return {
        "error": "Lemon Squeezy webhooks are retired. Use /webhooks/dodo.",
    }, 410
