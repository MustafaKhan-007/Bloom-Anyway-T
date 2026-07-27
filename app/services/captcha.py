"""Image-identification captcha for auth forms (no third-party dependency).

Shows a small grid of drawn icons; the visitor must select every tile that
matches the prompted shape. Challenge + answers live in the session.
"""
from __future__ import annotations

import io
import math
import random
import secrets

from flask import session
from PIL import Image, ImageDraw, ImageFilter

# Prompted shapes and how we describe them to humans.
SHAPES = ("flower", "star", "heart", "sun", "moon", "leaf")
SHAPE_LABELS = {
    "flower": "a flower",
    "star": "a star",
    "heart": "a heart",
    "sun": "a sun",
    "moon": "a crescent moon",
    "leaf": "a leaf",
}

GRID_SIZE = 6
TILE_PX = 96
_BG = (250, 245, 238)
_INK = (43, 38, 34)
_PLUM = (122, 46, 98)
_ROSE = (224, 138, 109)
_GOLD = (239, 167, 51)
_LEAF = (95, 122, 99)


def issue_captcha() -> dict:
    """Create a fresh challenge and store it in the session."""
    target = random.choice(SHAPES)
    # 2 or 3 matching tiles so the task is unambiguous but not trivial.
    n_match = random.randint(2, 3)
    tiles = [target] * n_match
    others = [s for s in SHAPES if s != target]
    while len(tiles) < GRID_SIZE:
        tiles.append(random.choice(others))
    random.shuffle(tiles)

    session["captcha_tiles"] = tiles
    session["captcha_target"] = target
    session["captcha_answers"] = [i for i, s in enumerate(tiles) if s == target]
    session["captcha_token"] = secrets.token_hex(8)
    # Drop legacy math-captcha keys if present.
    session.pop("captcha_answer", None)
    session.pop("captcha_question", None)
    return captcha_challenge()


def captcha_challenge() -> dict:
    """Return the current challenge for the template, issuing one if needed."""
    tiles = session.get("captcha_tiles")
    target = session.get("captcha_target")
    answers = session.get("captcha_answers")
    token = session.get("captcha_token")
    if (not tiles or not target or answers is None or not token
            or len(tiles) != GRID_SIZE):
        return issue_captcha()
    return {
        "prompt": f"Select all images with {SHAPE_LABELS.get(target, target)}",
        "token": token,
        "count": len(tiles),
        "target": target,
    }


def captcha_question() -> str:
    """Back-compat helper used by older call sites / smoke stubs."""
    return captcha_challenge()["prompt"]


def verify_captcha(answers) -> bool:
    """Check selected tile indices and always rotate the challenge afterward."""
    expected = session.pop("captcha_answers", None)
    session.pop("captcha_tiles", None)
    session.pop("captcha_target", None)
    session.pop("captcha_token", None)
    session.pop("captcha_answer", None)
    session.pop("captcha_question", None)

    if expected is None:
        issue_captcha()
        return False

    if answers is None:
        picked: set[int] = set()
    elif isinstance(answers, (list, tuple, set)):
        picked = set()
        for a in answers:
            try:
                picked.add(int(a))
            except (TypeError, ValueError):
                continue
    else:
        try:
            picked = {int(answers)}
        except (TypeError, ValueError):
            picked = set()

    ok = picked == set(int(i) for i in expected)
    issue_captcha()
    return ok


def render_tile(index: int) -> bytes | None:
    """PNG bytes for one challenge tile, or None if the index is invalid."""
    tiles = session.get("captcha_tiles") or []
    if index < 0 or index >= len(tiles):
        return None
    return _draw_tile(tiles[index])


# --------------------------- drawing helpers ---------------------------------

def _draw_tile(shape: str) -> bytes:
    img = Image.new("RGB", (TILE_PX, TILE_PX), _BG)
    draw = ImageDraw.Draw(img)
    # Soft tile plate
    draw.rounded_rectangle(
        (4, 4, TILE_PX - 5, TILE_PX - 5),
        radius=16, fill=(255, 255, 255), outline=(243, 233, 218), width=2)

    cx = cy = TILE_PX / 2
    jitter = random.uniform(-4, 4)
    cx += jitter
    cy += random.uniform(-3, 3)
    scale = random.uniform(0.92, 1.08)
    angle = random.uniform(-18, 18)

    icon = Image.new("RGBA", (TILE_PX, TILE_PX), (0, 0, 0, 0))
    idraw = ImageDraw.Draw(icon)
    _SHAPE_DRAW[shape](idraw, cx, cy, scale)
    if abs(angle) > 0.5:
        icon = icon.rotate(angle, resample=Image.BICUBIC, center=(cx, cy))
    img = Image.alpha_composite(img.convert("RGBA"), icon).convert("RGB")

    # Light grain so naive pixel-matching bots struggle a bit more.
    pixels = img.load()
    for _ in range(80):
        x = random.randint(8, TILE_PX - 9)
        y = random.randint(8, TILE_PX - 9)
        r, g, b = pixels[x, y]
        d = random.randint(-12, 12)
        pixels[x, y] = (max(0, min(255, r + d)),
                        max(0, min(255, g + d)),
                        max(0, min(255, b + d)))
    img = img.filter(ImageFilter.SMOOTH)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _draw_flower(draw: ImageDraw.ImageDraw, cx: float, cy: float, scale: float):
    r = 14 * scale
    for deg in range(0, 360, 60):
        rad = math.radians(deg)
        px = cx + math.cos(rad) * r
        py = cy + math.sin(rad) * r
        draw.ellipse((px - 10, py - 10, px + 10, py + 10), fill=_ROSE + (255,))
    draw.ellipse((cx - 8, cy - 8, cx + 8, cy + 8), fill=_GOLD + (255,))


def _draw_star(draw: ImageDraw.ImageDraw, cx: float, cy: float, scale: float):
    outer, inner = 26 * scale, 11 * scale
    pts = []
    for i in range(10):
        rad = math.radians(-90 + i * 36)
        r = outer if i % 2 == 0 else inner
        pts.append((cx + math.cos(rad) * r, cy + math.sin(rad) * r))
    draw.polygon(pts, fill=_GOLD + (255,))


def _draw_heart(draw: ImageDraw.ImageDraw, cx: float, cy: float, scale: float):
    s = 18 * scale
    draw.ellipse((cx - s - 4, cy - s, cx - 2, cy + 4), fill=_PLUM + (255,))
    draw.ellipse((cx + 2, cy - s, cx + s + 4, cy + 4), fill=_PLUM + (255,))
    draw.polygon([
        (cx - s - 2, cy - 2),
        (cx + s + 2, cy - 2),
        (cx, cy + s + 6),
    ], fill=_PLUM + (255,))


def _draw_sun(draw: ImageDraw.ImageDraw, cx: float, cy: float, scale: float):
    r = 14 * scale
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=_GOLD + (255,))
    for deg in range(0, 360, 45):
        rad = math.radians(deg)
        x1 = cx + math.cos(rad) * (r + 4)
        y1 = cy + math.sin(rad) * (r + 4)
        x2 = cx + math.cos(rad) * (r + 14)
        y2 = cy + math.sin(rad) * (r + 14)
        draw.line((x1, y1, x2, y2), fill=_GOLD + (255,), width=3)


def _draw_moon(draw: ImageDraw.ImageDraw, cx: float, cy: float, scale: float):
    r = 20 * scale
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=_PLUM + (255,))
    draw.ellipse((cx - r + 10, cy - r + 2, cx + r + 6, cy + r - 2),
                 fill=(255, 255, 255, 255))


def _draw_leaf(draw: ImageDraw.ImageDraw, cx: float, cy: float, scale: float):
    s = 22 * scale
    draw.ellipse((cx - s * 0.55, cy - s, cx + s * 0.55, cy + s),
                 fill=_LEAF + (255,))
    draw.line((cx, cy + s - 2, cx, cy - s + 4), fill=(255, 255, 255, 220), width=2)


_SHAPE_DRAW = {
    "flower": _draw_flower,
    "star": _draw_star,
    "heart": _draw_heart,
    "sun": _draw_sun,
    "moon": _draw_moon,
    "leaf": _draw_leaf,
}
