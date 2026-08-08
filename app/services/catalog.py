"""Courses & Guides catalogue helpers.

Demo/mock products from the initial layout are removed on deploy so the
page stays empty until the owner adds real resources in Studio.
"""
from __future__ import annotations

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


def remove_demo_catalog() -> int:
    """Delete leftover mock catalogue rows. Returns how many were removed."""
    removed = 0
    for slug in DEMO_SLUGS:
        product = Product.query.filter_by(slug=slug).first()
        if product is None:
            continue
        # Keep the row (as draft) if orders already reference it.
        if product.orders.count():
            product.status = "draft"
            product.track = None
            product.featured = False
        else:
            for asset in list(product.assets):
                db.session.delete(asset)
            db.session.delete(product)
        removed += 1
    if removed:
        db.session.flush()
    return removed


def ensure_catalog() -> int:
    """Back-compat alias: purge demo rows instead of seeding them."""
    return remove_demo_catalog()
