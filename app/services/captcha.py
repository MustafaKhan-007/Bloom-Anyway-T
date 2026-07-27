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

# Cloudflare's published always-pass test keys (for local/dev/smoke only).
TEST_SITE_KEY = "1x00000000000000000000AA"
TEST_SECRET_KEY = "1x0000000000000000000000000000000AA"


def site_key() -> str:
    return (os.environ.get("TURNSTILE_SITE_KEY")
            or current_app.config.get("TURNSTILE_SITE_KEY")
            or "").strip()


def secret_key() -> str:
    return (os.environ.get("TURNSTILE_SECRET_KEY")
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


def verify_captcha(token=None) -> bool:
    """Verify a Turnstile response token with Cloudflare.

    ``token`` may be the raw string, or ignored when reading the standard
    ``cf-turnstile-response`` form field.
    """
    if token is None or isinstance(token, (list, tuple)):
        token = request.form.get("cf-turnstile-response")
    token = (token or "").strip()
    secret = secret_key()
    if not secret:
        # Keys not configured yet — allow signup so deploys aren't blocked.
        # Sign-in never uses captcha. Set TURNSTILE_* to enable Cloudflare on signup.
        log.warning("TURNSTILE_SECRET_KEY is not configured; skipping captcha check")
        return True
    if not token:
        return False

    payload = {
        "secret": secret,
        "response": token,
    }
    remote = request.headers.get("CF-Connecting-IP") or request.remote_addr
    if remote:
        payload["remoteip"] = remote

    try:
        resp = requests.post(SITEVERIFY_URL, data=payload, timeout=10)
        data = resp.json() if resp.ok else {}
    except Exception:
        log.exception("Turnstile siteverify request failed")
        return False

    ok = bool(data.get("success"))
    if not ok:
        log.info("Turnstile rejected: %s", data.get("error-codes") or data)
    return ok
