"""Store product covers and gallery images in Postgres.

Local disk under Flask ``instance/`` is wiped on Render redeploys; URL columns
alone are not enough. Bytes live in the DB (same pattern as avatars / site
images / Showcase photos). Public URLs stay ``/media/product-cover/...`` and
``/media/product-gallery/...``.
"""
from __future__ import annotations

import io
import uuid
from pathlib import Path

from flask import current_app
from PIL import Image, ImageOps, UnidentifiedImageError
from werkzeug.datastructures import FileStorage

from ..extensions import db
from ..models import Product, ProductGalleryImage

MAX_UPLOAD_BYTES = 8 * 1024 * 1024
MAX_EDGE = 1200
OUTPUT_MIME = "image/jpeg"


class CoverError(ValueError):
    pass


def public_url(product_id: int) -> str:
    return f"/media/product-cover/{int(product_id)}"


def gallery_public_url(product_id: int, filename: str) -> str:
    return f"/media/product-gallery/{int(product_id)}/{filename}"


def _crop_to_aspect(img: Image.Image, aw: int, ah: int) -> Image.Image:
    tw, th = img.size
    if tw < 1 or th < 1:
        return img
    target = aw / ah
    current = tw / th
    if abs(current - target) < 0.02:
        return img
    if current > target:
        nw = max(1, int(round(th * target)))
        left = max(0, (tw - nw) // 2)
        return img.crop((left, 0, left + nw, th))
    nh = max(1, int(round(tw / target)))
    top = max(0, (th - nh) // 2)
    return img.crop((0, top, tw, top + nh))


def _read_jpeg(
    upload: FileStorage,
    *,
    label: str,
    max_edge: tuple[int, int],
    aspect: tuple[int, int] | None = None,
) -> bytes:
    if not upload or not getattr(upload, "filename", None):
        raise CoverError(f"Choose a {label} image first.")
    raw = upload.read(MAX_UPLOAD_BYTES + 1)
    if not raw:
        raise CoverError("That file was empty.")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise CoverError(f"Keep {label} images under 8 MB.")
    try:
        img = Image.open(io.BytesIO(raw))
        img = ImageOps.exif_transpose(img)
        img.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise CoverError("That doesn't look like a usable image.") from exc

    img = img.convert("RGB")
    if aspect is not None:
        img = _crop_to_aspect(img, aspect[0], aspect[1])
    img.thumbnail(max_edge, Image.LANCZOS)
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=88, optimize=True)
    return out.getvalue()


def process_and_save(product_id: int, upload: FileStorage) -> str:
    """Validate and store a full JPEG cover (no crop). Returns public URL."""
    product = db.session.get(Product, int(product_id))
    if product is None:
        raise CoverError("That product was already gone.")
    data = _read_jpeg(upload, label="cover", max_edge=(MAX_EDGE, MAX_EDGE))
    product.cover_data = data
    product.cover_mime = OUTPUT_MIME
    # Best-effort: drop any leftover ephemeral disk file from older deploys
    _unlink_legacy_cover(product.id)
    return public_url(product.id)


def clear(product_id: int) -> None:
    product = db.session.get(Product, int(product_id))
    if product is not None:
        product.cover_data = None
        product.cover_mime = None
    _unlink_legacy_cover(product_id)


def cover_bytes(product_id: int) -> tuple[bytes, str] | None:
    """Return (bytes, mime) for a cover, or None."""
    product = db.session.get(Product, int(product_id))
    if product is not None and product.cover_data:
        return bytes(product.cover_data), (product.cover_mime or OUTPUT_MIME)

    # One-time rescue: import leftover disk file into Postgres if still present
    path = _legacy_cover_path(product_id)
    if path is not None and path.is_file():
        data = path.read_bytes()
        if product is not None and data:
            product.cover_data = data
            product.cover_mime = OUTPUT_MIME
            if not (product.cover_url or "").strip():
                product.cover_url = public_url(product.id)
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
            return data, OUTPUT_MIME
        return data, OUTPUT_MIME
    return None


# Kept for older call sites / smoke helpers
def file_for(product_id: int) -> Path | None:
    """Deprecated disk helper — prefer ``cover_bytes``."""
    path = _legacy_cover_path(product_id)
    return path if path is not None and path.is_file() else None


def process_gallery_image(product_id: int, upload: FileStorage) -> str:
    """Validate and store a landscape teaser JPEG in Postgres. Returns public URL."""
    product = db.session.get(Product, int(product_id))
    if product is None:
        raise CoverError("That product was already gone.")
    data = _read_jpeg(
        upload, label="teaser", aspect=(16, 10), max_edge=(1400, 900),
    )
    name = f"{uuid.uuid4().hex[:12]}.jpg"
    row = ProductGalleryImage(
        product_id=product.id,
        filename=name,
        data=data,
        mime=OUTPUT_MIME,
        sort_order=ProductGalleryImage.query.filter_by(product_id=product.id).count(),
    )
    db.session.add(row)
    db.session.flush()
    return gallery_public_url(product.id, name)


def gallery_bytes(product_id: int, filename: str) -> tuple[bytes, str] | None:
    name = Path(filename or "").name
    if not name or name != filename or ".." in name:
        return None
    row = (ProductGalleryImage.query
           .filter_by(product_id=int(product_id), filename=name)
           .first())
    if row is not None and row.data:
        return bytes(row.data), (row.mime or OUTPUT_MIME)

    # Legacy disk rescue
    path = _legacy_gallery_path(product_id, name)
    if path is not None and path.is_file():
        data = path.read_bytes()
        if data:
            product = db.session.get(Product, int(product_id))
            if product is not None:
                existing = (ProductGalleryImage.query
                            .filter_by(product_id=product.id, filename=name)
                            .first())
                if existing is None:
                    db.session.add(ProductGalleryImage(
                        product_id=product.id,
                        filename=name,
                        data=data,
                        mime=OUTPUT_MIME,
                    ))
                    try:
                        db.session.commit()
                    except Exception:
                        db.session.rollback()
            return data, OUTPUT_MIME
    return None


def gallery_file(product_id: int, filename: str) -> Path | None:
    """Deprecated disk helper — prefer ``gallery_bytes``."""
    path = _legacy_gallery_path(product_id, filename)
    return path if path is not None and path.is_file() else None


def clear_gallery_image(product_id: int, filename: str) -> None:
    name = Path(filename or "").name
    if not name or name != filename or ".." in name:
        return
    row = (ProductGalleryImage.query
           .filter_by(product_id=int(product_id), filename=name)
           .first())
    if row is not None:
        db.session.delete(row)
    path = _legacy_gallery_path(product_id, name)
    if path is not None and path.is_file():
        try:
            path.unlink()
        except OSError:
            pass


def clear_all_gallery(product_id: int) -> None:
    (ProductGalleryImage.query
     .filter_by(product_id=int(product_id))
     .delete(synchronize_session=False))
    root = _legacy_gallery_dir(product_id)
    if root is not None and root.is_dir():
        for child in root.glob("*"):
            try:
                child.unlink()
            except OSError:
                pass
        try:
            root.rmdir()
        except OSError:
            pass


# --- ephemeral disk paths (legacy only) -------------------------------------

def _legacy_cover_path(product_id: int) -> Path | None:
    try:
        root = Path(current_app.instance_path) / "product_covers"
        return root / f"{int(product_id)}.jpg"
    except Exception:
        return None


def _legacy_gallery_dir(product_id: int) -> Path | None:
    try:
        return (Path(current_app.instance_path) / "product_galleries"
                / str(int(product_id)))
    except Exception:
        return None


def _legacy_gallery_path(product_id: int, filename: str) -> Path | None:
    name = Path(filename or "").name
    if not name or name != filename or ".." in name:
        return None
    root = _legacy_gallery_dir(product_id)
    if root is None:
        return None
    return root / name


def _unlink_legacy_cover(product_id: int) -> None:
    path = _legacy_cover_path(product_id)
    if path is not None and path.is_file():
        try:
            path.unlink()
        except OSError:
            pass
