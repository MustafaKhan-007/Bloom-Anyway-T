"""Course reading progress + purchase → catalog product linking."""
from __future__ import annotations

import os
import zipfile
from io import BytesIO
from pathlib import Path

from flask import current_app
from sqlalchemy import func

from ..extensions import db
from ..models import CourseProgress, Product, ProductAsset, ShopPurchase, utcnow


def catalog_product_for_purchase(purchase: ShopPurchase) -> Product | None:
    """Match a shop purchase to a Studio catalogue product via Dodo id."""
    if purchase is None:
        return None
    keys = []
    for raw in (purchase.variant_id, purchase.product_id):
        key = (raw or "").strip()
        if key and key not in keys:
            keys.append(key)
    for key in keys:
        row = Product.query.filter_by(dodo_product_id=key).first()
        if row:
            return row
        row = Product.query.filter_by(ls_variant_id=key).first()
        if row:
            return row
    # Fallback: exact title match (helps older purchases).
    name = (purchase.product_name or "").strip()
    if name:
        return Product.query.filter(func.lower(Product.title) == name.lower()).first()
    return None


def primary_asset(product: Product | None) -> ProductAsset | None:
    if product is None or not product.assets:
        return None
    return product.assets[0]


def owned_purchase(user, purchase_id: int) -> ShopPurchase | None:
    purchase = db.session.get(ShopPurchase, purchase_id)
    if (purchase is None
            or not user
            or not getattr(user, "is_authenticated", False)
            or purchase.user_id != user.id
            or purchase.status != "linked"):
        return None
    return purchase


def get_progress(user_id: int, purchase_id: int) -> CourseProgress | None:
    return (CourseProgress.query
            .filter_by(user_id=user_id, shop_purchase_id=purchase_id)
            .first())


def progress_map_for(user_id: int, purchase_ids: list[int]) -> dict[int, CourseProgress]:
    if not purchase_ids:
        return {}
    rows = (CourseProgress.query
            .filter(CourseProgress.user_id == user_id,
                    CourseProgress.shop_purchase_id.in_(purchase_ids))
            .all())
    return {r.shop_purchase_id: r for r in rows}


def save_progress(
    *,
    user_id: int,
    purchase_id: int,
    product_id: int | None,
    current_page: int,
    total_pages: int,
) -> CourseProgress:
    page = max(1, int(current_page or 1))
    total = max(0, int(total_pages or 0))
    if total > 0:
        page = min(page, total)
        percent = int(round(100 * page / total))
        percent = max(0, min(100, percent))
    else:
        percent = 0

    row = get_progress(user_id, purchase_id)
    if row is None:
        row = CourseProgress(
            user_id=user_id,
            shop_purchase_id=purchase_id,
            product_id=product_id,
        )
        db.session.add(row)
    row.product_id = product_id or row.product_id
    row.current_page = page
    row.total_pages = total
    row.percent = percent
    row.updated_at = utcnow()
    return row


def h5p_cache_dir(asset_id: int) -> Path:
    root = Path(current_app.instance_path) / "h5p_cache" / str(asset_id)
    return root


def ensure_h5p_extracted(asset: ProductAsset) -> Path:
    """Extract an .h5p (zip) package once; reuse on later opens."""
    dest = h5p_cache_dir(asset.id)
    marker = dest / ".ready"
    if marker.is_file() and (dest / "h5p.json").is_file():
        return dest
    dest.mkdir(parents=True, exist_ok=True)
    raw = bytes(asset.data or b"")
    with zipfile.ZipFile(BytesIO(raw)) as zf:
        zf.extractall(dest)
    marker.write_text("ok", encoding="utf-8")
    return dest


def safe_h5p_file(asset_id: int, relpath: str) -> Path | None:
    """Resolve a path inside an extracted H5P package (no traversal)."""
    base = h5p_cache_dir(asset_id).resolve()
    if not base.is_dir():
        return None
    cleaned = (relpath or "").replace("\\", "/").lstrip("/")
    if not cleaned or ".." in cleaned.split("/"):
        return None
    target = (base / cleaned).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        return None
    if not target.is_file():
        return None
    return target
