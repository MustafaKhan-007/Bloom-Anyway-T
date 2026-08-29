"""Instagram helpers for profile links and home-page reel embeds."""
import re

#: domain fragment -> nice platform label. First match wins.
PLATFORMS = [
    ("instagram.com", "Instagram"),
    ("tiktok.com", "TikTok"),
    ("youtube.com", "YouTube"),
    ("youtu.be", "YouTube"),
    ("facebook.com", "Facebook"),
    ("fb.com", "Facebook"),
    ("snapchat.com", "Snapchat"),
    ("x.com", "X"),
    ("twitter.com", "X"),
    ("pinterest.com", "Pinterest"),
    ("threads.net", "Threads"),
    ("linkedin.com", "LinkedIn"),
    ("twitch.tv", "Twitch"),
]


def platform_for(url: str):
    """Return the platform label for a URL, or None if it isn't a known social."""
    host = re.sub(r"^https?://", "", (url or "").strip().lower()).split("/")[0]
    host = host.split("@")[-1]  # ignore any user:pass@
    for frag, label in PLATFORMS:
        if host == frag or host.endswith("." + frag) or host == "www." + frag:
            return label
    return None


def instagram_embed_url(url: str):
    """Turn an Instagram reel/post URL into its /embed iframe src, or None."""
    if not url:
        return None
    m = re.search(r"instagram\.com/(?:reel|reels|p|tv)/([A-Za-z0-9_-]+)", url)
    if not m:
        return None
    return f"https://www.instagram.com/reel/{m.group(1)}/embed/"


_HANDLE_RE = re.compile(r"^[A-Za-z0-9._]{1,30}$")


def instagram_handle(raw: str) -> str:
    """Pull a clean @handle out of a pasted handle or full Instagram URL.

    Strips query strings (``?igsh=…``) and fragments so the public card never
    shows a messy share-link.
    """
    text = (raw or "").strip()
    if not text:
        return ""
    # bare handle
    if text.startswith("@"):
        text = text[1:]
    # full URL / path
    if "instagram.com" in text.lower():
        text = re.sub(r"^https?://(www\.)?", "", text, flags=re.I)
        text = re.sub(r"^instagram\.com/", "", text, flags=re.I)
        text = text.split("/")[0]
    # drop ?igsh=… / #fragments / trailing junk
    text = text.split("?", 1)[0].split("#", 1)[0].strip().strip("/")
    text = text.lstrip("@")
    if not _HANDLE_RE.match(text):
        # keep whatever's left before illegal chars (best effort)
        text = re.sub(r"[^A-Za-z0-9._]", "", text)[:30]
    return text


def instagram_profile_url(handle: str) -> str:
    """Canonical profile URL for a clean handle."""
    h = instagram_handle(handle)
    return f"https://www.instagram.com/{h}/" if h else ""


def instagram_from_links(links) -> str:
    """Return a clean Instagram handle from a profile links list, or ''."""
    for link in links or []:
        url = (link.get("url") if isinstance(link, dict) else "") or ""
        if platform_for(url) == "Instagram":
            return instagram_handle(url)
    return ""


def upsert_instagram_link(links, raw: str, *, limit: int = 6) -> list:
    """Set or clear the Instagram entry in a links list. Returns a new list."""
    existing = [ln for ln in (links or [])
                if isinstance(ln, dict) and platform_for(ln.get("url") or "") != "Instagram"]
    handle = instagram_handle(raw or "")
    if handle:
        existing.insert(0, {
            "label": "Instagram",
            "url": instagram_profile_url(handle)[:300],
        })
    return existing[:limit]


#: handle -> (fetched_at_monotonic, result). Instagram rarely gives us anything
#: and the request costs seconds, so don't ask twice for the same person.
_PREVIEW_CACHE: dict[str, tuple[float, dict]] = {}
_PREVIEW_TTL_SEC = 60 * 60


def fetch_instagram_preview(handle: str) -> dict:
    """Best-effort public preview for a profile (photo + a short blurb).

    Instagram often walls this off, so callers must treat an empty result as
    normal — the owner can always paste a bio/photo by hand in Studio. This
    blocks a Studio save, so it's cached and skipped entirely under test.
    """
    import logging
    import time

    import requests
    from html import unescape

    h = instagram_handle(handle)
    if not h:
        return {}

    try:
        from flask import current_app
        if current_app.config.get("TESTING"):
            return {}
    except Exception:
        pass

    now = time.monotonic()
    hit = _PREVIEW_CACHE.get(h)
    if hit and (now - hit[0]) < _PREVIEW_TTL_SEC:
        return dict(hit[1])

    url = instagram_profile_url(h)
    try:
        resp = requests.get(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (compatible; BloomAnywayBot/1.0; "
                    "+https://bloomanyway.com)"
                ),
                "Accept": "text/html",
            },
            timeout=4,
            allow_redirects=True,
        )
        if resp.status_code != 200 or not resp.text:
            _PREVIEW_CACHE[h] = (now, {})
            return {}
        html = resp.text
    except requests.RequestException:
        logging.getLogger(__name__).info(
            "instagram preview: could not reach %s", h)
        _PREVIEW_CACHE[h] = (now, {})
        return {}

    def _meta(prop):
        m = re.search(
            rf'<meta[^>]+(?:property|name)=["\']{prop}["\'][^>]+content=["\']([^"\']+)["\']',
            html, re.I)
        if not m:
            m = re.search(
                rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']{prop}["\']',
                html, re.I)
        return unescape(m.group(1)).strip() if m else ""

    image = _meta("og:image") or _meta("twitter:image")
    desc = _meta("og:description") or _meta("description")
    # Instagram's og:description is usually "X Followers, Y Following…" — keep
    # it only when it looks like a real bio (has letters beyond counts).
    blurb = ""
    if desc and not re.match(r"^[\d.,\s]+Followers", desc, re.I):
        blurb = desc[:280]
    out = {}
    if image and image.startswith("http"):
        out["image"] = image
    if blurb:
        out["blurb"] = blurb
    _PREVIEW_CACHE[h] = (now, out)
    return dict(out)
