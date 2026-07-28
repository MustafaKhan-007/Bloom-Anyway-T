"""Cloudflare Turnstile captcha for signup.

Uses the official Turnstile widget (Cloudflare-hosted) on register only.
Sign-in has no captcha. Verification is a server-side call to Cloudflare's
siteverify endpoint.
"""
from __future__ import annotations

import logging
import os

import requests
from flask import current_app, request

log = logging.getLogger(__name__)

SITEVERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"

# Widget created in the Cloudflare dashboard (do not recreate).
WIDGET_SITE_KEY = "0x4AAAAAAEAGFowmHgyFM5Kf"

# Cloudflare's published always-pass test keys (for local/dev/smoke only).
TEST_SITE_KEY = "1x00000000000000000000AA"
TEST_SECRET_KEY = "1x0000000000000000000000000000000AA"


def site_key() -> str:
    return (os.environ.get("TURNSTILE_SITE_KEY")
            or current_app.config.get("TURNSTILE_SITE_KEY")
            or WIDGET_SITE_KEY
            or "").strip()


def secret_key() -> str:
    """Read the Turnstile secret from the environment.

    Prefer ``TURNSTILE_SECRET`` (Spin / dashboard recovery naming). Fall back to
    ``TURNSTILE_SECRET_KEY`` for older Render env names.
    """
    return (os.environ.get("TURNSTILE_SECRET")
            or os.environ.get("TURNSTILE_SECRET_KEY")
            or current_app.config.get("TURNSTILE_SECRET")
            or current_app.config.get("TURNSTILE_SECRET_KEY")
            or "").strip()


def captcha_challenge() -> dict:
    """Template context for the Turnstile widget."""
    return {"site_key": site_key()}


def issue_captcha() -> dict:
    """No-op for Turnstile (challenge is rendered by Cloudflare)."""
    return captcha_challenge()


def captcha_question() -> str:
    """Back-compat stub for older call sites / smoke patches."""
    return "turnstile"


def _client_ip() -> str | None:
    # Prefer Cloudflare / proxy-forwarded IP when present.
    forwarded = (request.headers.get("CF-Connecting-IP")
                 or request.headers.get("X-Forwarded-For")
                 or "").strip()
    if forwarded:
        return forwarded.split(",")[0].strip() or None
    return request.remote_addr


def verify_captcha(token=None) -> bool:
    """Verify a Turnstile response token with Cloudflare.

    Canonical siteverify: POST secret + response (+ remoteip) to
    challenges.cloudflare.com; require ``success === true``.
    """
    if token is None or isinstance(token, (list, tuple)):
        token = request.form.get("cf-turnstile-response")
    token = (token or "").strip()
    secret = secret_key()
    if not secret:
        # Widget is shown when a site key exists — fail closed without a secret.
        log.warning("TURNSTILE_SECRET is not configured; rejecting captcha")
        return False
    if not token:
        return False

    payload = {
        "secret": secret,
        "response": token,
    }
    remote = _client_ip()
    if remote:
        payload["remoteip"] = remote

    try:
        resp = requests.post(SITEVERIFY_URL, data=payload, timeout=10)
        if not resp.ok:
            log.warning("Turnstile siteverify HTTP %s", resp.status_code)
            return False
        data = resp.json()
    except Exception:
        log.exception("Turnstile siteverify request failed")
        return False

    ok = data.get("success") is True
    if not ok:
        log.info("Turnstile rejected: %s", data.get("error-codes") or data)
    return ok
