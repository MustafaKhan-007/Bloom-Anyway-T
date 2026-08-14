"""Courses & Guides catalogue helpers.

Old mock-catalogue rows (fixed slugs from the initial layout) are removed if
still present. Do not delete by title heuristics — that would wipe real
products named with words like "test".
"""
from __future__ import annotations

import re

from ..extensions import db
from ..models import Product

# Slugs created by the old mock catalogue — delete these if still present.
DEMO_SLUGS = (
    "rebuild-workbook",
    "custody-with-confidence",
    "boundaries-blueprint",
    "healing-bundle",
    "50-hooks",
    "0-to-10k",
    "first-digital-product",
    "creator-bundle",
)


def _purge_product(product: Product) -> str:
    """Delete a product, or demote to draft if it has orders. Returns action."""
    if product.orders.count():
        product.status = "draft"
        product.track = None
        product.featured = False
        product.title = f"[archived] {product.title}"[:160]
        return "archived"
    for asset in list(product.assets):
        db.session.delete(asset)
    db.session.delete(product)
    return "deleted"


def remove_demo_catalog() -> int:
    """Delete leftover mock catalogue rows by known slug only."""
    removed = 0
    for slug in DEMO_SLUGS:
        product = Product.query.filter_by(slug=slug).first()
        if product is None:
            continue
        _purge_product(product)
        removed += 1
    if removed:
        db.session.flush()
    return removed


def ensure_catalog() -> int:
    """Back-compat alias: purge demo rows instead of seeding them."""
    return remove_demo_catalog()


def slugify_title(title: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-")
    return (base or "product")[:140]


def unique_product_slug(title: str, *, exclude_id: int | None = None) -> str:
    """Build a unique product slug from a title."""
    base = slugify_title(title)
    slug = base
    n = 2
    while True:
        q = Product.query.filter_by(slug=slug)
        if exclude_id is not None:
            q = q.filter(Product.id != exclude_id)
        if q.first() is None:
            return slug
        slug = f"{base}-{n}"[:160]
        n += 1
