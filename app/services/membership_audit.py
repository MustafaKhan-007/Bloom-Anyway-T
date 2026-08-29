"""Explain where every paid membership came from.

Studio's member counts and Stripe's subscriber counts answer different
questions: Stripe knows who is *paying right now*, Studio shows the tier each
account currently *holds*. Comped tiers, free months bundled with a product,
annual one-off payments, and subscriptions that ended without the site hearing
about it all pull the two numbers apart. This works out which of those applies
to each person so the gap stops being a mystery.
"""
from __future__ import annotations

import logging

from flask import current_app
from sqlalchemy import func

from ..models import MEMBERSHIP_LABELS, Order, User
from .memberships import _PAID_TIERS, manual_tier, tier_for_price_id
from .perks import perk_state

log = logging.getLogger(__name__)

#: why an account holds the tier it holds, best explanation first
SOURCE_LABELS = {
    "owner": "Studio owner",
    "manual": "Set by hand in Studio",
    "perk": "Free months from a purchase",
    "order": "Paid order on file",
    "unexplained": "Nothing on file explains it",
}
SOURCE_HELP = {
    "owner": "Owners always hold Full Bloom. Never billed.",
    "manual": "You granted this tier on the Members page. No Stripe subscription "
              "is expected.",
    "perk": "A product they bought includes free membership months. No Stripe "
            "subscription is expected.",
    "order": "There's a paid membership order for this email. If it was a "
             "subscription, Stripe should show it too — unless it has since "
             "been cancelled.",
    "unexplained": "No manual grant, no perk, no paid order. Usually a "
                   "subscription that ended without the site being told, or a "
                   "member who paid Stripe under a different email address.",
}


def _paid_membership_orders(emails: set[str]) -> dict[str, list[Order]]:
    """Paid membership orders for a batch of emails, keyed by lowercase email."""
    if not emails:
        return {}
    rows = (Order.query
            .filter(Order.status == "paid",
                    func.lower(Order.buyer_email).in_(emails))
            .all())
    out: dict[str, list[Order]] = {}
    for order in rows:
        tier = (order.membership_tier or "").strip().lower()
        if tier not in _PAID_TIERS:
            tier = tier_for_price_id(order.ls_variant_id) or ""
        if tier not in _PAID_TIERS:
            continue
        out.setdefault((order.buyer_email or "").strip().lower(), []).append(order)
    return out


def audit(tier: str = "") -> dict:
    """Break down who holds a paid tier and why — local records only.

    Deliberately does not call Stripe: this has to stay fast enough to open
    from Studio. ``unexplained`` rows are the ones worth checking in Stripe.
    """
    query = User.query.filter(User.deleted_at.is_(None),
                              User.membership.in_(_PAID_TIERS))
    if tier in _PAID_TIERS:
        query = query.filter(User.membership == tier)
    people = query.order_by(User.created_at.desc()).all()

    emails = {(u.email or "").strip().lower() for u in people if u.email}
    orders_by_email = _paid_membership_orders(emails)

    rows = []
    counts: dict[str, int] = dict.fromkeys(SOURCE_LABELS, 0)
    by_tier: dict[str, dict[str, int]] = {}
    for u in people:
        email = (u.email or "").strip().lower()
        perk = perk_state(u)
        orders = orders_by_email.get(email, [])
        if u.is_admin:
            source = "owner"
        elif manual_tier(u):
            source = "manual"
        elif perk["tier"]:
            source = "perk"
        elif orders:
            source = "order"
        else:
            source = "unexplained"
        newest = max((o.created_at for o in orders if o.created_at), default=None)
        counts[source] += 1
        slot = by_tier.setdefault(u.membership, dict.fromkeys(SOURCE_LABELS, 0))
        slot[source] += 1
        rows.append({
            "user": u,
            "name": u.public_name(),
            "email": u.email,
            "tier": u.membership,
            "tier_label": MEMBERSHIP_LABELS.get(u.membership, u.membership),
            "source": source,
            "source_label": SOURCE_LABELS[source],
            "manual": manual_tier(u),
            "perk_until": perk["until"],
            "orders": len(orders),
            "last_paid": newest,
        })

    rows.sort(key=lambda r: (r["source"] != "unexplained",
                             r["last_paid"] is not None,
                             r["name"].lower()))
    return {
        "rows": rows,
        "counts": counts,
        "by_tier": by_tier,
        "total": len(rows),
        "tier": tier if tier in _PAID_TIERS else "",
    }


def resync_from_stripe(tier: str = "", limit: int = 400) -> dict:
    """Re-check every paid member against Stripe and correct their tier.

    This is the fix for a subscription that ended while the site wasn't
    listening: Stripe is asked directly, and anyone who is no longer paying
    (and holds no manual grant or perk) drops back. Slow by nature — one Stripe
    lookup per member — so it only runs when an owner asks for it.

    A member Stripe couldn't answer for is skipped rather than dropped, and
    counted in ``unreachable``. Reconciling them anyway would fall back to
    local orders, which is how a broken Stripe call could quietly report that
    every tier already matched.
    """
    from ..extensions import db
    from . import stripe_pay as pay
    from .memberships import reconcile_user

    query = User.query.filter(User.deleted_at.is_(None),
                              User.is_admin.is_(False),
                              User.membership.in_(_PAID_TIERS))
    if tier in _PAID_TIERS:
        query = query.filter(User.membership == tier)
    people = query.order_by(User.created_at.desc()).limit(limit).all()

    # Under TESTING the live lookup deliberately answers nothing, which is a
    # decision rather than a failure — fall through to local orders there.
    live_ready = pay.configured() and not current_app.config.get("TESTING")
    changed = []
    unreachable = 0
    for u in people:
        live = None
        if live_ready:
            try:
                live = pay.active_membership_tier_from_stripe(u.email)
            except Exception:
                log.exception("membership audit: stripe lookup failed for user %s", u.id)
                live = None
            if live is None:
                unreachable += 1
                continue

        before = u.membership
        try:
            if reconcile_user(u, downgrade=True, live_tier=live) \
                    and u.membership != before:
                changed.append({
                    "name": u.public_name(), "email": u.email,
                    "from": MEMBERSHIP_LABELS.get(before, before),
                    "to": MEMBERSHIP_LABELS.get(u.membership, u.membership),
                })
        except Exception:
            log.exception("membership audit: resync failed for user %s", u.id)
    if changed:
        db.session.commit()
    else:
        db.session.rollback()
    return {"checked": len(people) - unreachable, "changed": changed,
            "unreachable": unreachable}
