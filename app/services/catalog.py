"""Seed / refresh the on-site Courses & Guides catalogue."""
from __future__ import annotations

from ..extensions import db
from ..models import Product

# Demo catalogue matching the Courses & Guides mock. Owner pastes real
# Dodo product IDs in Studio; until then checkout shows a friendly message.
CATALOG = [
    {
        "slug": "rebuild-workbook",
        "title": "The Rebuild Workbook: 60 Days to Reclaiming You",
        "promise": "60 Days to Reclaiming You",
        "type": "workbook",
        "track": "healing",
        "subject": "Healing",
        "category_label": "DIVORCE RECOVERY",
        "meta_line": "80 daily pages • PDF + printable • By Ayesha",
        "description_md": "A guided 60-day workbook for reclaiming yourself after divorce.",
        "price_cents": 2700,
        "badge": "NEW",
        "sort_order": 10,
        "featured": True,
    },
    {
        "slug": "custody-with-confidence",
        "title": "Custody with Confidence",
        "promise": "Navigating the Process Without Losing Yourself",
        "type": "course",
        "track": "healing",
        "subject": "Healing",
        "category_label": "CUSTODY",
        "meta_line": "6 modules • Video + worksheets • By Ayesha",
        "description_md": "A practical course for navigating custody with clarity and calm.",
        "price_cents": 4700,
        "sort_order": 20,
    },
    {
        "slug": "boundaries-blueprint",
        "title": "Boundaries Blueprint",
        "promise": "Scripts for Every Hard Conversation",
        "type": "guide",
        "track": "healing",
        "subject": "Healing",
        "category_label": "BOUNDARIES",
        "meta_line": "40 scripts • PDF guide • By Ayesha",
        "description_md": "Ready-to-use scripts for the conversations that drain you.",
        "price_cents": 1900,
        "sort_order": 30,
    },
    {
        "slug": "healing-bundle",
        "title": "Healing Bundle",
        "promise": "Every healing resource, one price",
        "type": "bundle",
        "track": "healing",
        "subject": "Healing",
        "category_label": "BUNDLE",
        "meta_line": "All healing resources + future updates",
        "description_md": (
            "The Rebuild Workbook / Custody with Confidence / Boundaries Blueprint "
            "/ All future healing resources added free."
        ),
        "price_cents": 7900,
        "compare_at_cents": 10300,
        "sort_order": 90,
        "featured": True,
    },
    {
        "slug": "50-hooks",
        "title": "50 Hooks That Stop the Scroll",
        "promise": "Proven Formulas for Short-Form Video",
        "type": "guide",
        "track": "building",
        "subject": "Building",
        "category_label": "AUDIENCE GROWTH",
        "meta_line": "50 hooks • PDF guide • By Saman",
        "description_md": "Proven short-form hooks that stop the scroll.",
        "price_cents": 1700,
        "badge": "NEW",
        "sort_order": 10,
        "featured": True,
    },
    {
        "slug": "0-to-10k",
        "title": "0 to 10k",
        "promise": "The Exact Strategy That Grew My Following From Scratch",
        "type": "course",
        "track": "building",
        "subject": "Building",
        "category_label": "GROWTH",
        "meta_line": "8 modules • Video + workbook • By Saman",
        "description_md": "The exact strategy that grew a following from scratch.",
        "price_cents": 6700,
        "sort_order": 20,
    },
    {
        "slug": "first-digital-product",
        "title": "Your First Digital Product",
        "promise": "A Step-by-Step Launch Checklist",
        "type": "template",
        "track": "building",
        "subject": "Building",
        "category_label": "PRODUCTS",
        "meta_line": "Checklist + 3 templates • PDF • By Saman",
        "description_md": "A launch checklist and templates for your first digital product.",
        "price_cents": 2200,
        "sort_order": 30,
    },
    {
        "slug": "creator-bundle",
        "title": "Creator Bundle",
        "promise": "Every creator resource, one price",
        "type": "bundle",
        "track": "building",
        "subject": "Building",
        "category_label": "BUNDLE",
        "meta_line": "All creator resources + future updates",
        "description_md": (
            "50 Hooks / 0 to 10k / Your First Digital Product "
            "/ All future creator resources added free."
        ),
        "price_cents": 8900,
        "compare_at_cents": 10600,
        "sort_order": 90,
        "featured": True,
    },
]


def ensure_catalog() -> int:
    """Create missing catalogue rows; refresh copy fields on existing ones.

    Never overwrites ``dodo_product_id``, status, or price once set by the owner
    (price only filled when currently null). Returns how many rows were added.
    """
    added = 0
    for row in CATALOG:
        product = Product.query.filter_by(slug=row["slug"]).first()
        if product is None:
            product = Product(slug=row["slug"], status="published")
            db.session.add(product)
            added += 1
        # Always keep mock-facing catalogue fields in sync for seeded slugs.
        product.title = row["title"]
        product.promise = row.get("promise")
        product.type = row.get("type") or "guide"
        product.track = row.get("track")
        product.subject = row.get("subject")
        product.category_label = row.get("category_label")
        product.meta_line = row.get("meta_line")
        product.description_md = row.get("description_md")
        product.badge = row.get("badge")
        product.sort_order = row.get("sort_order") or 0
        product.featured = bool(row.get("featured"))
        product.currency = "USD"
        if product.price_cents is None:
            product.price_cents = row.get("price_cents")
        if product.compare_at_cents is None and row.get("compare_at_cents"):
            product.compare_at_cents = row["compare_at_cents"]
        if product.status == "draft":
            product.status = "published"
        # Placeholder cover so publish_blockers stays clean when Dodo id is set.
        if not product.cover_url:
            product.cover_url = f"local://catalog/{row['slug']}"
    if added:
        db.session.flush()
    return added
