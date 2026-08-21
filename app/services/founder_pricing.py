"""Launch founder pricing: first-month promo via Stripe codes.

Healing & Creator → 25% off first payment with ``MEMBERFOUNDER``.
Full Bloom → 20% off first payment with ``FULLBLOOMFOUNDER``.

Active while ``founder_price_ends`` (ISO date in site settings) is today or later.
Actual discount is applied in Stripe checkout when the member enters the code;
this module drives the membership page banner and displayed founder prices.
"""
from __future__ import annotations

from datetime import date

from .settings import get_setting

#: percent off the first payment during the founder window
DISCOUNT_PCT = {
    "healing": 25,
    "creator": 25,
    "full_bloom": 20,
}

PROMO_CODES = {
    "healing": "MEMBERFOUNDER",
    "creator": "MEMBERFOUNDER",
    "full_bloom": "FULLBLOOMFOUNDER",
}


def ends_date() -> date | None:
    raw = (get_setting("founder_price_ends") or "").strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def is_active() -> bool:
    end = ends_date()
    return end is not None and end >= date.today()


def ends_display() -> str:
    end = ends_date()
    if end is None:
        return ""
    return end.strftime("%b %d, %Y")


def discount_pct(tier: str) -> int | None:
    return DISCOUNT_PCT.get((tier or "").strip().lower())


def promo_code(tier: str) -> str | None:
    return PROMO_CODES.get((tier or "").strip().lower())


def discounted_cents(cents: int | None, tier: str) -> int | None:
    if cents is None or cents < 0:
        return None
    pct = discount_pct(tier)
    if not pct:
        return None
    return max(0, round(cents * (100 - pct) / 100))


def _money(cents: int | None, currency: str = "USD") -> str:
    if cents is None:
        return ""
    symbol = {"USD": "$", "EUR": "€", "GBP": "£"}.get(
        (currency or "USD").upper(), f"{currency} "
    )
    amount = cents / 100
    if cents % 100 == 0:
        return f"{symbol}{amount:,.0f}"
    return f"{symbol}{amount:,.2f}"


def tier_bid(plan) -> dict | None:
    """Public display fields for one plan during the founder window."""
    if plan is None:
        return None
    tier = plan.tier
    pct = discount_pct(tier)
    code = promo_code(tier)
    if not pct or not code:
        return None
    currency = getattr(plan, "currency", None) or "USD"
    monthly = getattr(plan, "price_cents", None)
    annual = getattr(plan, "annual_price_cents", None)
    return {
        "tier": tier,
        "pct": pct,
        "code": code,
        "regular_month": _money(monthly, currency) if monthly is not None else "",
        "founder_month": _money(discounted_cents(monthly, tier), currency)
        if monthly is not None else "",
        "regular_year": _money(annual, currency) if annual is not None else "",
        "founder_year": _money(discounted_cents(annual, tier), currency)
        if annual is not None else "",
    }


def public_state(plans: dict) -> dict:
    """Bundle for the membership page template."""
    active = is_active()
    end = ends_date()
    tiers = {}
    if active:
        for key in ("healing", "creator", "full_bloom"):
            info = tier_bid(plans.get(key) if plans else None)
            if info:
                tiers[key] = info
    return {
        "active": active and bool(tiers),
        "ends": end.isoformat() if end else "",
        "ends_display": ends_display(),
        "member_code": PROMO_CODES["healing"],
        "full_code": PROMO_CODES["full_bloom"],
        "tiers": tiers,
    }
