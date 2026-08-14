"""Upload helpers for on-site course/guide files (ProductAsset)."""
from __future__ import annotations

import os
import zipfile
from io import BytesIO

from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

from ..extensions import db
from ..models import Product, ProductAsset

# Keep uploads bounded so the DB / request stay responsive.
MAX_BYTES = 45 * 1024 * 1024

_MIME_BY_EXT = {
    ".pdf": "application/pdf",
    ".h5p": "application/zip",
    ".zip": "application/zip",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".m4a": "audio/mp4",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".html": "text/html",
    ".htm": "text/html",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".epub": "application/epub+zip",
}

_KIND_BY_EXT = {
    ".pdf": "pdf",
    ".h5p": "h5p",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".gif": "image",
    ".webp": "image",
    ".mp4": "video",
    ".webm": "video",
    ".mp3": "audio",
    ".wav": "audio",
    ".m4a": "audio",
    ".txt": "text",
    ".md": "text",
    ".html": "html",
    ".htm": "html",
    ".doc": "doc",
    ".docx": "docx",
    ".epub": "other",
    ".zip": "other",
}


class AssetError(ValueError):
    pass


def detect_kind(filename: str, mime: str | None = None) -> str:
    ext = os.path.splitext(filename or "")[1].lower()
    if ext in _KIND_BY_EXT:
        return _KIND_BY_EXT[ext]
    mime = (mime or "").lower()
    if "pdf" in mime:
        return "pdf"
    if mime.startswith("image/"):
        return "image"
    if mime.startswith("video/"):
        return "video"
    if mime.startswith("audio/"):
        return "audio"
    if "html" in mime:
        return "html"
    if mime.startswith("text/"):
        return "text"
    return "other"


def _looks_like_h5p(data: bytes, filename: str) -> bool:
    ext = os.path.splitext(filename or "")[1].lower()
    if ext == ".h5p":
        return True
    if ext != ".zip":
        return False
    try:
        with zipfile.ZipFile(BytesIO(data)) as zf:
            names = set(zf.namelist())
            return "h5p.json" in names or any(n.endswith("/h5p.json") for n in names)
    except zipfile.BadZipFile:
        return False


def process_upload(upload: FileStorage, *, title: str | None = None) -> dict:
    """Validate and normalize an uploaded course file. Returns asset fields."""
    if upload is None or not getattr(upload, "filename", None):
        raise AssetError("Choose a file to upload.")
    filename = secure_filename(upload.filename) or "course-file"
    raw = upload.read()
    if not raw:
        raise AssetError("That file was empty.")
    if len(raw) > MAX_BYTES:
        raise AssetError("Files must be under 45 MB so reading stays quick.")

    ext = os.path.splitext(filename)[1].lower()
    mime = (upload.mimetype or "").strip() or _MIME_BY_EXT.get(ext, "application/octet-stream")
    kind = detect_kind(filename, mime)
    if _looks_like_h5p(raw, filename):
        kind = "h5p"
        mime = "application/zip"
        if not filename.lower().endswith(".h5p"):
            filename = os.path.splitext(filename)[0] + ".h5p"

    return {
        "title": (title or "").strip()[:160] or None,
        "filename": filename[:255],
        "mime": mime[:120],
        "kind": kind[:20],
        "size": len(raw),
        "data": raw,
    }


def add_asset(product: Product, upload: FileStorage, *, title: str | None = None) -> ProductAsset:
    fields = process_upload(upload, title=title)
    order = len(product.assets)
    asset = ProductAsset(
        product_id=product.id,
        title=fields["title"],
        filename=fields["filename"],
        mime=fields["mime"],
        kind=fields["kind"],
        size=fields["size"],
        data=fields["data"],
        sort_order=order,
    )
    db.session.add(asset)
    return asset
