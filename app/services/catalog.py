"""Courses & Guides catalogue helpers.

Demo/mock products from the initial layout are removed on deploy so the
page stays empty until the owner adds real resources in Studio.
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

# Titles that look like leftover test/placeholder rows.
_PLACEHOLDER_TITLE = re.compile(
    r"\b(test|demo|placeholder|sample|lorem)\b|this is a test",
    re.IGNORECASE,
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
    """Delete leftover mock/test catalogue rows. Returns how many were removed."""
    removed = 0
    seen_ids: set[int] = set()

    for slug in DEMO_SLUGS:
        product = Product.query.filter_by(slug=slug).first()
        if product is None or product.id in seen_ids:
            continue
        _purge_product(product)
        seen_ids.add(product.id)
        removed += 1

    for product in Product.query.all():
        if product.id in seen_ids:
            continue
        title = (product.title or "").strip()
        if not title or not _PLACEHOLDER_TITLE.search(title):
            continue
        _purge_product(product)
        seen_ids.add(product.id)
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
