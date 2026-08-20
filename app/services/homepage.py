"""Homepage marketplace features: Product of the Day + top products."""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy.orm import joinedload

from ..models import MarketplaceListing, utcnow


def _active_product_listings():
    return (
        MarketplaceListing.query
        .options(joinedload(MarketplaceListing.author),
                 joinedload(MarketplaceListing.images))
        .filter_by(active=True, kind="product")
        .all()
    )


def product_of_the_day() -> MarketplaceListing | None:
    """Stable daily pick from active Showcase digital products.

    Prefers Creator-member listings (eligibility perk); falls back to any
    active product listing so the section can still fill.
    """
    listings = _active_product_listings()
    if not listings:
        return None
    creators = [
        ln for ln in listings
        if ln.author and ln.author.has_feature("spotlight")
    ]
    pool = creators or listings
    # Sort for a stable order, then pick by day-of-year.
    pool = sorted(pool, key=lambda ln: (ln.id,))
    idx = utcnow().toordinal() % len(pool)
    return pool[idx]


def top_products(limit: int = 6) -> list[MarketplaceListing]:
    """Most-clicked active digital products, preferring the last 30 days."""
    since = utcnow() - timedelta(days=30)
    recent = (
        MarketplaceListing.query
        .options(joinedload(MarketplaceListing.author),
                 joinedload(MarketplaceListing.images))
        .filter_by(active=True, kind="product")
        .filter(MarketplaceListing.created_at >= since)
        .order_by(MarketplaceListing.clicks.desc(),
                  MarketplaceListing.created_at.desc())
        .limit(limit)
        .all()
    )
    if len(recent) >= limit:
        return recent

    seen = {ln.id for ln in recent}
    filler = (
        MarketplaceListing.query
        .options(joinedload(MarketplaceListing.author),
                 joinedload(MarketplaceListing.images))
        .filter_by(active=True, kind="product")
        .order_by(MarketplaceListing.clicks.desc(),
                  MarketplaceListing.created_at.desc())
        .limit(limit * 2)
        .all()
    )
    out = list(recent)
    for ln in filler:
        if ln.id in seen:
            continue
        out.append(ln)
        seen.add(ln.id)
        if len(out) >= limit:
            break
    return out
