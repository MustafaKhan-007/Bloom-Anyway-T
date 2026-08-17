"""Traffic-source attribution from UTM params and HTTP referrers."""
from __future__ import annotations

import hashlib
import re
from urllib.parse import urlparse

from flask import has_request_context, request, session
from flask_login import current_user

from ..extensions import db
from ..models import VisitEvent, utcnow

SESSION_KEY = "_ba_visit_src"
SESSION_RECORDED = "_ba_visit_recorded"

# Hosts → friendly source labels
_HOST_MAP = (
    (re.compile(r"(^|\.)(facebook\.com|fb\.com|fb\.me|m\.facebook\.com)$", re.I), "Facebook"),
    (re.compile(r"(^|\.)(instagram\.com|l\.instagram\.com)$", re.I), "Instagram"),
    (re.compile(r"(^|\.)(tiktok\.com)$", re.I), "TikTok"),
    (re.compile(r"(^|\.)(twitter\.com|x\.com|t\.co)$", re.I), "X / Twitter"),
    (re.compile(r"(^|\.)(linkedin\.com|lnkd\.in)$", re.I), "LinkedIn"),
    (re.compile(r"(^|\.)(youtube\.com|youtu\.be)$", re.I), "YouTube"),
    (re.compile(r"(^|\.)(pinterest\.com)$", re.I), "Pinterest"),
    (re.compile(r"(^|\.)(reddit\.com)$", re.I), "Reddit"),
    (re.compile(r"(^|\.)(google\.[a-z.]+|bing\.com|duckduckgo\.com|yahoo\.com|baidu\.com)$", re.I),
     "Organic search"),
)

_UTM_LABELS = {
    "facebook": "Facebook",
    "fb": "Facebook",
    "fb-ads": "Facebook",
    "meta": "Facebook",
    "instagram": "Instagram",
    "ig": "Instagram",
    "tiktok": "TikTok",
    "twitter": "X / Twitter",
    "x": "X / Twitter",
    "linkedin": "LinkedIn",
    "youtube": "YouTube",
    "google": "Google Ads",
    "googleads": "Google Ads",
    "cpc": "Paid search",
    "ppc": "Paid search",
    "email": "Email",
    "newsletter": "Email",
    "sms": "SMS",
}


def classify_source(
    *,
    utm_source: str | None = None,
    utm_medium: str | None = None,
    referrer: str | None = None,
) -> str:
    src = (utm_source or "").strip().lower()
    medium = (utm_medium or "").strip().lower()
    if src in _UTM_LABELS:
        return _UTM_LABELS[src]
    if medium in ("cpc", "ppc", "paid", "paidsearch", "paid_social"):
        if src:
            return _UTM_LABELS.get(src, f"Paid ({src})")
        return "Paid traffic"
    if medium in ("email", "e-mail"):
        return "Email"
    if medium in ("organic", "seo"):
        return "Organic search"
    if src:
        return src.replace("-", " ").replace("_", " ").title()[:80]

    host = ""
    if referrer:
        try:
            host = (urlparse(referrer).hostname or "").lower()
        except Exception:
            host = ""
    if host:
        for pattern, label in _HOST_MAP:
            if pattern.search(host):
                return label
        # Same-site referrer → not a new acquisition source
        return "Referral"
    return "Direct / unknown"


def _session_fingerprint() -> str:
    raw = session.get("_id") or session.get("csrf_token") or ""
    ua = (request.headers.get("User-Agent") or "")[:120]
    seed = f"{raw}|{ua}|{request.remote_addr or ''}"
    return hashlib.sha256(seed.encode()).hexdigest()[:32]


def maybe_record_visit() -> VisitEvent | None:
    """Record one attribution event per browser session when source is known.

    Called from after_request on HTML GETs. Skips same-site only traffic unless
    UTM params are present.
    """
    if not has_request_context():
        return None
    if request.method != "GET":
        return None

    utm_source = (request.args.get("utm_source") or "").strip()[:120] or None
    utm_medium = (request.args.get("utm_medium") or "").strip()[:120] or None
    utm_campaign = (request.args.get("utm_campaign") or "").strip()[:160] or None
    referrer = (request.referrer or "").strip()[:500] or None

    # Only persist when we have UTM or an external referrer (or first Direct hit).
    has_utm = bool(utm_source or utm_medium or utm_campaign)
    external_ref = False
    if referrer:
        try:
            ref_host = (urlparse(referrer).hostname or "").lower()
            here = (request.host or "").split(":")[0].lower()
            external_ref = bool(ref_host and ref_host != here and not ref_host.endswith("." + here))
        except Exception:
            external_ref = False

    source = classify_source(
        utm_source=utm_source, utm_medium=utm_medium, referrer=referrer if external_ref else None,
    )

    # Remember first non-direct source for the session (used in activity copy).
    if source != "Direct / unknown" or has_utm:
        session[SESSION_KEY] = source

    # One DB row per session unless new UTM arrives.
    already = session.get(SESSION_RECORDED)
    if already and not has_utm:
        return None
    if source == "Direct / unknown" and not has_utm and not external_ref:
        # Still record one direct landing so Studio sees volume.
        if already:
            return None

    path = (request.path or "/")[:300]
    sk = _session_fingerprint()
    user_id = None
    if getattr(current_user, "is_authenticated", False):
        user_id = current_user.id

    event = VisitEvent(
        created_at=utcnow(),
        path=path,
        source=source,
        referrer=referrer if external_ref else None,
        utm_source=utm_source,
        utm_medium=utm_medium,
        utm_campaign=utm_campaign,
        session_key=sk,
        user_id=user_id,
    )
    db.session.add(event)
    session[SESSION_RECORDED] = source
    return event
