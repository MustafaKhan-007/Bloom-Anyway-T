"""Static + optional live checks for Turnstile Spin wiring."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITEKEY = "0x4AAAAAAEAGFowmHgyFM5Kf"
SITEVERIFY = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


def check(name: str, ok: bool, detail: str = "") -> bool:
    mark = "PASS" if ok else "FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"[{mark}] {name}{suffix}")
    return ok


def main() -> int:
    captcha = (ROOT / "app/services/captcha.py").read_text(encoding="utf-8")
    partial = (ROOT / "app/templates/partials/captcha.html").read_text(encoding="utf-8")
    register = (ROOT / "app/templates/auth/register.html").read_text(encoding="utf-8")
    config = (ROOT / "app/config.py").read_text(encoding="utf-8")
    render = (ROOT / "render.yaml").read_text(encoding="utf-8")

    ok = True
    ok &= check("canonical siteverify URL", SITEVERIFY in captcha)
    ok &= check("reads TURNSTILE_SECRET from env",
                'os.environ.get("TURNSTILE_SECRET")' in captcha)
    ok &= check("sends remoteip", '"remoteip"' in captcha or "'remoteip'" in captcha)
    ok &= check("requires success is True", "data.get(\"success\") is True" in captcha)
    ok &= check("fail-closed when secret missing", "TURNSTILE_SECRET is not configured" in captcha)
    ok &= check("widget site key in config", SITEKEY in config)
    ok &= check("data-action=turnstile-spin-v2", 'data-action="turnstile-spin-v2"' in partial)
    ok &= check("cf-turnstile widget class", 'class="cf-turnstile"' in partial)
    ok &= check("register includes captcha partial", "partials/captcha.html" in register)
    ok &= check("token reset on submit", "turnstile.reset" in partial)
    ok &= check("render.yaml uses TURNSTILE_SECRET", "TURNSTILE_SECRET" in render)

    # Live dummy-token check (same contract as Spin validate.sh).
    secret = (os.environ.get("TURNSTILE_SECRET")
              or os.environ.get("TURNSTILE_SECRET_KEY")
              or "").strip()
    if not secret:
        print("[SKIP] dummy siteverify — set TURNSTILE_SECRET in this shell to run live check")
        return 0 if ok else 1

    try:
        import requests
        resp = requests.post(
            SITEVERIFY,
            data={"secret": secret, "response": "XXXX.DUMMY.TOKEN.XXXX"},
            timeout=15,
        )
        data = resp.json()
    except Exception as exc:
        return 0 if check("dummy siteverify network", False, str(exc)) else 1

    codes = data.get("error-codes") or []
    if data.get("success") is True:
        ok &= check("dummy siteverify", False, "unexpected success:true")
    elif "invalid-input-secret" in codes:
        ok &= check("dummy siteverify", False, "invalid-input-secret (secret does not match widget)")
    elif "invalid-input-response" in codes:
        ok &= check("dummy siteverify", True, "secret accepted; dummy token rejected as expected")
    else:
        ok &= check("dummy siteverify", False, f"unexpected codes={codes}")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
