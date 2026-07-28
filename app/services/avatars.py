"""Process uploaded avatar images into small, safe, square images.

Stored in the database (not on disk) so avatars survive Render deploys, which
wipe the ephemeral filesystem. Re-encoding also strips EXIF/metadata and
neutralises most malformed-image tricks.

Static uploads become JPEGs. Animated GIFs keep a resized animated copy for
the public profile page, plus a JPEG still for everywhere else.
"""
from __future__ import annotations

import io

from PIL import Image, ImageOps, ImageSequence, UnidentifiedImageError

MAX_UPLOAD_BYTES = 6 * 1024 * 1024   # 6 MB before decoding
OUTPUT_SIZE = 400                     # square px
OUTPUT_MIME = "image/jpeg"
ANIM_MIME = "image/gif"
# Cap animated payload so a long GIF can't bloat the row too far.
MAX_ANIM_BYTES = 2 * 1024 * 1024


class AvatarError(ValueError):
    pass


def _square_fit(img: Image.Image) -> Image.Image:
    return ImageOps.fit(img, (OUTPUT_SIZE, OUTPUT_SIZE), Image.LANCZOS)


def _jpeg_bytes(img: Image.Image) -> bytes:
    rgb = img.convert("RGB")
    out = io.BytesIO()
    rgb.save(out, format="JPEG", quality=85, optimize=True)
    return out.getvalue()


def _is_animated(img: Image.Image) -> bool:
    return bool(getattr(img, "is_animated", False) and getattr(img, "n_frames", 1) > 1)


def _process_animated_gif(raw: bytes) -> tuple[bytes, str, bytes, str]:
    """Return (still_jpeg, jpeg_mime, anim_gif, gif_mime)."""
    img = Image.open(io.BytesIO(raw))
    # Still = first frame, square-cropped.
    first = img.convert("RGBA")
    still = _jpeg_bytes(_square_fit(first))

    frames: list[Image.Image] = []
    durations: list[int] = []
    for frame in ImageSequence.Iterator(img):
        fr = frame.convert("RGBA")
        frames.append(_square_fit(fr))
        durations.append(int(frame.info.get("duration", 100) or 100))

    if not frames:
        raise AvatarError("That GIF didn't have any frames we could use.")

    anim_out = io.BytesIO()
    frames[0].save(
        anim_out,
        format="GIF",
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=img.info.get("loop", 0),
        optimize=False,
    )
    anim_bytes = anim_out.getvalue()
    if len(anim_bytes) > MAX_ANIM_BYTES:
        # Too heavy after resize — keep the still only.
        return still, OUTPUT_MIME, b"", ""
    return still, OUTPUT_MIME, anim_bytes, ANIM_MIME


def process_avatar(file_storage) -> tuple[bytes, str, bytes | None, str | None]:
    """Return (still_bytes, still_mime, anim_bytes|None, anim_mime|None).

    ``anim_*`` is set only for animated GIFs that stay under the size cap.
    """
    raw = file_storage.read(MAX_UPLOAD_BYTES + 1)
    if not raw:
        raise AvatarError("That file was empty.")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise AvatarError("That image is over 6 MB \u2014 try a smaller one.")

    try:
        probe = Image.open(io.BytesIO(raw))
        probe.verify()
        img = Image.open(io.BytesIO(raw))
    except (UnidentifiedImageError, OSError, ValueError):
        raise AvatarError("That didn't look like an image we could read.")

    fmt = (img.format or "").upper()
    if fmt == "GIF" and _is_animated(img):
        still, still_mime, anim, anim_mime = _process_animated_gif(raw)
        if anim and anim_mime:
            return still, still_mime, anim, anim_mime
        return still, still_mime, None, None

    try:
        img = ImageOps.exif_transpose(img)
        img = img.convert("RGB")
    except (OSError, ValueError):
        raise AvatarError("That didn't look like an image we could read.")

    img = _square_fit(img)
    return _jpeg_bytes(img), OUTPUT_MIME, None, None
