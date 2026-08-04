"""Process and store owner-uploaded site images (hero / story teaser)."""
from __future__ import annotations

import io

from PIL import Image, ImageOps, UnidentifiedImageError

from ..extensions import db
from ..models import SITE_IMAGE_KEYS, SiteImage, utcnow

MAX_UPLOAD_BYTES = 8 * 1024 * 1024
MAX_EDGE = 1600
OUTPUT_MIME = "image/jpeg"


class SiteImageError(ValueError):
    pass


def public_path(key: str) -> str:
    return f"/media/site/{key}"


def process_and_save(key: str, file_storage) -> str:
    """Validate, resize, store. Returns the public path to use as the setting URL."""
    if key not in SITE_IMAGE_KEYS:
        raise SiteImageError("Unknown image slot.")
    if not file_storage or not getattr(file_storage, "filename", None):
        raise SiteImageError("Choose an image file first.")
    raw = file_storage.read(MAX_UPLOAD_BYTES + 1)
    if not raw:
        raise SiteImageError("That file was empty.")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise SiteImageError("Keep site images under 8 MB.")
    try:
        img = Image.open(io.BytesIO(raw))
        img = ImageOps.exif_transpose(img)
        img.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise SiteImageError("That doesn't look like a usable image.") from exc

    img = img.convert("RGB")
    img.thumbnail((MAX_EDGE, MAX_EDGE), Image.LANCZOS)
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=88, optimize=True)
    data = out.getvalue()

    row = db.session.get(SiteImage, key)
    if row is None:
        row = SiteImage(key=key, data=data, mime=OUTPUT_MIME, updated_at=utcnow())
        db.session.add(row)
    else:
        row.data = data
        row.mime = OUTPUT_MIME
        row.updated_at = utcnow()
    db.session.commit()
    return public_path(key)


def clear(key: str) -> None:
    if key not in SITE_IMAGE_KEYS:
        return
    row = db.session.get(SiteImage, key)
    if row is not None:
        db.session.delete(row)
        db.session.commit()


def get(key: str) -> SiteImage | None:
    if key not in SITE_IMAGE_KEYS:
        return None
    return db.session.get(SiteImage, key)
