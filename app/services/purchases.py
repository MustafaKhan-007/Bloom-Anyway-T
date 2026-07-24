"""Lemon Squeezy shop purchases → My space downloads."""
import logging
import os

from flask import current_app

from ..extensions import db
from ..models import Purchase, User
from . import shop_catalog

log = logging.getLogger(__name__)


def purchase_files_dir() -> str:
    configured = (current_app.config.get("PURCHASE_FILES_DIR") or "").strip()
    if configured:
        return configured
    return os.path.join(current_app.instance_path, "purchase_files")


def upsert_purchase(
    *,
    order_id: str,
    email: str,
    product_id: str | None,
    variant_id: str | None,
    product_name: str = "",
    status: str = "paid",
) -> Purchase | None:
    """Insert or update a Purchase by Lemon order id. Idempotent.

    Returns the Purchase row, or None if order_id is missing.
    """
    order_id = str(order_id or "").strip()
    if not order_id:
        return None

    email = (email or "").strip().lower()
    variant_key = str(variant_id).strip() if variant_id else ""
    name = shop_catalog.display_name(
        variant_key,
        fallback=product_name or "",
    )

    row = Purchase.query.filter_by(order_id=order_id).first()
    if row is None:
        row = Purchase(order_id=order_id)
        db.session.add(row)

    row.email = email
    row.product_id = str(product_id).strip() if product_id else None
    row.variant_id = variant_key or None
    row.product_name = (name or "")[:200]
    row.status = (status or "paid").strip().lower() or "paid"

    if row.user_id is None and email:
        user = User.query.filter(db.func.lower(User.email) == email).first()
        if user and user.deleted_at is None:
            row.user_id = user.id

    return row


def link_purchases_for_user(user: User) -> int:
    """Attach any email-matched Purchases that still have a null user_id.

    Returns how many rows were linked.
    """
    if user is None or not user.email:
        return 0
    email = user.email.strip().lower()
    rows = (Purchase.query
            .filter(Purchase.user_id.is_(None),
                    db.func.lower(Purchase.email) == email)
            .all())
    for row in rows:
        row.user_id = user.id
    return len(rows)


def purchases_for_user(user: User):
    """Paid purchases owned by this account (by user_id or email)."""
    if user is None or not user.email:
        return []
    email = user.email.strip().lower()
    return (Purchase.query
            .filter(Purchase.status == "paid",
                    db.or_(Purchase.user_id == user.id,
                           db.func.lower(Purchase.email) == email))
            .order_by(Purchase.created_at.desc())
            .all())


def resolve_download(purchase: Purchase) -> tuple[str, str] | None:
    """Return (absolute_path, download_filename) if the mapped file exists."""
    entry = shop_catalog.catalog_entry(purchase.variant_id)
    if not entry:
        return None
    rel = (entry.get("file") or "").strip().lstrip("/\\")
    if not rel or ".." in rel.replace("\\", "/").split("/"):
        return None
    path = os.path.join(purchase_files_dir(), rel)
    if not os.path.isfile(path):
        log.warning("purchase file missing for variant %s: %s",
                    purchase.variant_id, path)
        return None
    return path, os.path.basename(rel)
