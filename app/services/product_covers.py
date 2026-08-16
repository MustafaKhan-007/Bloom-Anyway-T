"""Product card cover images (optional upload; flower default when unset)."""
from __future__ import annotations

import io
from pathlib import Path

from flask import current_app
from PIL import Image, ImageOps, UnidentifiedImageError
from werkzeug.datastructures import FileStorage

MAX_UPLOAD_BYTES = 8 * 1024 * 1024
MAX_EDGE = 1200
# Tall cover used on Courses / My space library cards
ASPECT = (3, 4)


class CoverError(ValueError):
    pass


def storage_dir() -> Path:
    root = Path(current_app.instance_path) / "product_covers"
    root.mkdir(parents=True, exist_ok=True)
    return root


def cover_path(product_id: int) -> Path:
    return storage_dir() / f"{int(product_id)}.jpg"


def public_url(product_id: int) -> str:
    return f"/media/product-cover/{int(product_id)}"


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


def process_and_save(product_id: int, upload: FileStorage) -> str:
    """Validate, crop to 3:4, store JPEG. Returns the public URL."""
    if not upload or not getattr(upload, "filename", None):
        raise CoverError("Choose a cover image first.")
    raw = upload.read(MAX_UPLOAD_BYTES + 1)
    if not raw:
        raise CoverError("That file was empty.")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise CoverError("Keep cover images under 8 MB.")
    try:
        img = Image.open(io.BytesIO(raw))
        img = ImageOps.exif_transpose(img)
        img.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise CoverError("That doesn't look like a usable image.") from exc

    img = img.convert("RGB")
    img = _crop_to_aspect(img, ASPECT[0], ASPECT[1])
    img.thumbnail((MAX_EDGE, MAX_EDGE), Image.LANCZOS)
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=88, optimize=True)
    path = cover_path(product_id)
    path.write_bytes(out.getvalue())
    return public_url(product_id)


def clear(product_id: int) -> None:
    path = cover_path(product_id)
    if path.is_file():
        try:
            path.unlink()
        except OSError:
            pass


def file_for(product_id: int) -> Path | None:
    path = cover_path(product_id)
    return path if path.is_file() else None
