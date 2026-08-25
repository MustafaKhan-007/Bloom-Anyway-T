"""Configuration classes, read from environment variables.

Local development works with zero configuration (SQLite + console email).
Production (APP_ENV=production) refuses to boot with missing secrets.
"""
import os
from datetime import timedelta


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        return "sqlite:///firstlight-dev.db"
    # Render (and Heroku) hand out postgres:// which SQLAlchemy 2.x rejects.
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url


class Config:
    # Optional: if unset, a persistent key is generated and stored in the
    # database on first boot (see app factory), so it survives restarts
    # without needing an env var.
    SECRET_KEY = os.environ.get("SECRET_KEY", "").strip()

    SQLALCHEMY_DATABASE_URI = _database_url()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # Managed Postgres (e.g. Render) drops idle connections; without pre-ping the
    # first request after an idle spell hits a dead connection and 500s
    # ("something went sideways"). Pre-ping + recycle keeps the pool healthy.
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_recycle": 280,
    }

    # Video uploads are streamed to a directory on disk (a mounted persistent
    # disk in production, the instance folder locally) instead of the database,
    # so they can be large without exhausting worker memory. MAX_VIDEO_MB is the
    # per-file cap; MAX_CONTENT_LENGTH sits just above it (+ headroom for the
    # thumbnail and several 25 MB course files) and rejects absurd bodies fast.
    MAX_VIDEO_MB = int(os.environ.get("MAX_VIDEO_MB", "1024") or 1024)
    # Reel-review raw uploads stream to VIDEO_STORAGE_DIR (like Content Hub
    # videos). Keep the cap modest so weekly draw files stay manageable.
    REEL_RAW_MAX_MB = int(os.environ.get("REEL_RAW_MAX_MB", "100") or 100)
    VIDEO_STORAGE_DIR = os.environ.get("VIDEO_STORAGE_DIR", "").strip()
    MAX_CONTENT_LENGTH = (MAX_VIDEO_MB + 32) * 1024 * 1024

    # Sessions / auth
    SESSION_COOKIE_NAME = "firstlight_session"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_NAME = "firstlight_remember"
    REMEMBER_COOKIE_DURATION = timedelta(days=30)
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"
    CODE_MAX_AGE_MINUTES = 15
    # Admin panel uses a sliding "idle" timeout instead of a hard daily re-login:
    # each admin action refreshes the clock, and re-auth is only required after
    # this many days of no admin activity. The session cookie must outlive it.
    ADMIN_IDLE_DAYS = 14
    PERMANENT_SESSION_LIFETIME = timedelta(days=30)

    # Email — two transports, first configured one wins:
    # 1. BREVO_API_KEY: HTTP API (works on hosts that block SMTP, e.g. Render)
    # 2. SMTP_*: classic SMTP relay (optional fallback)
    BREVO_API_KEY = os.environ.get("BREVO_API_KEY", "").strip()
    # Transactional template IDs (Brevo → Transactional → Templates, number after #).
    # General (#10): shared layout — SUBJECT, PREVIEW, HEADER, TITLE, BODY,
    # BUTTON_TEXT, BUTTON_URL. Used for welcome/receipt/membership/cancel/etc.
    # Confirm (#3) stays separate (needs the CODE field).
    BREVO_TEMPLATE_GENERAL = int(
        os.environ.get("BREVO_TEMPLATE_GENERAL", "10") or 0
    )
    # Welcome: sent once after email is verified. Confirm: 6-digit signup code email.
    BREVO_TEMPLATE_WELCOME = int(
        os.environ.get("BREVO_TEMPLATE_WELCOME")
        or os.environ.get("BREVO_TEMPLATE_CONFIRM_LEGACY", "0")
        or 0
    )
    BREVO_TEMPLATE_CONFIRM = int(
        os.environ.get("BREVO_TEMPLATE_CONFIRM", "3") or 0
    )
    BREVO_TEMPLATE_RECEIPT = int(
        os.environ.get("BREVO_TEMPLATE_RECEIPT", "0") or 0
    )
    BREVO_TEMPLATE_HEALING = int(
        os.environ.get("BREVO_TEMPLATE_HEALING", "0") or 0
    )
    BREVO_TEMPLATE_CREATOR = int(
        os.environ.get("BREVO_TEMPLATE_CREATOR", "0") or 0
    )
    BREVO_TEMPLATE_CARD_DECLINED = int(
        os.environ.get("BREVO_TEMPLATE_CARD_DECLINED", "0") or 0
    )
    BREVO_TEMPLATE_CANCEL = int(
        os.environ.get("BREVO_TEMPLATE_CANCEL", "0") or 0
    )
    BREVO_TEMPLATE_NEWSLETTER = int(
        os.environ.get("BREVO_TEMPLATE_NEWSLETTER", "0") or 0
    )
    # Optional absolute site origin for email CTAs when no request context.
    PUBLIC_BASE_URL = (
        os.environ.get("PUBLIC_BASE_URL", "").strip()
        or "https://www.bloomanyway.online"
    )
    # Days of access kept after a failed membership renewal charge.
    MEMBERSHIP_GRACE_DAYS = int(
        os.environ.get("MEMBERSHIP_GRACE_DAYS", "3") or 3
    )
    SMTP_HOST = os.environ.get("SMTP_HOST", "").strip()
    SMTP_PORT = int(os.environ.get("SMTP_PORT", "587") or 587)
    SMTP_USER = os.environ.get("SMTP_USER", "")
    SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
    MAIL_FROM = os.environ.get("MAIL_FROM", "Bloom Anyway <hello@localhost>")

    # Cloudflare Turnstile (signup only). Prefer TURNSTILE_SECRET (Spin naming);
    # TURNSTILE_SECRET_KEY is accepted as a legacy alias.
    TURNSTILE_SITE_KEY = (
        os.environ.get("TURNSTILE_SITE_KEY", "").strip()
        or "0x4AAAAAAEAGFowmHgyFM5Kf"
    )
    TURNSTILE_SECRET = (
        os.environ.get("TURNSTILE_SECRET", "").strip()
        or os.environ.get("TURNSTILE_SECRET_KEY", "").strip()
    )
    TURNSTILE_SECRET_KEY = TURNSTILE_SECRET  # legacy alias

    # Stripe (courses, guides, memberships). Secret key + webhook signing secret.
    STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "").strip()
    STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "").strip()
    # Legacy Lemon env (ignored; kept so old Render vars don't crash imports).
    LEMONSQUEEZY_WEBHOOK_SECRET = os.environ.get("LEMONSQUEEZY_WEBHOOK_SECRET", "")
    # Optional shared secret for /cron/* jobs (e.g. support-group reminders).
    CRON_SECRET = os.environ.get("CRON_SECRET", "").strip()
    # Optional self-hosted digital files for ShopPurchase.file_key
    SHOP_FILES_DIR = os.environ.get("SHOP_FILES_DIR", "").strip()

    # Daily.co (embedded support-group rooms).
    # API key from https://dashboard.daily.co/developers
    DAILY_API_KEY = os.environ.get("DAILY_API_KEY", "").strip()
    # Optional subdomain label used only for stub URLs in tests (e.g. bloomanyway).
    DAILY_DOMAIN = os.environ.get("DAILY_DOMAIN", "bloomanyway").strip() or "bloomanyway"
    DAILY_MEETING_DURATION = int(os.environ.get("DAILY_MEETING_DURATION", "30") or 30)
    # Force stub rooms without calling Daily (tests); auto-on when TESTING
    # and DAILY_API_KEY is unset.
    DAILY_STUB = os.environ.get("DAILY_STUB", "").strip().lower() in (
        "1", "true", "yes", "on",
    )

    # Legacy Zoom env (ignored for new sessions; kept so old Render vars don't crash).
    ZOOM_ACCOUNT_ID = os.environ.get("ZOOM_ACCOUNT_ID", "").strip()
    ZOOM_CLIENT_ID = os.environ.get("ZOOM_CLIENT_ID", "").strip()
    ZOOM_CLIENT_SECRET = os.environ.get("ZOOM_CLIENT_SECRET", "").strip()
    ZOOM_HOST_EMAIL = os.environ.get("ZOOM_HOST_EMAIL", "").strip()
    ZOOM_MEETING_DURATION = int(os.environ.get("ZOOM_MEETING_DURATION", "90") or 90)
    ZOOM_STUB = os.environ.get("ZOOM_STUB", "").strip().lower() in (
        "1", "true", "yes", "on",
    )

    # Flask-Limiter: in-memory storage. Fine at this scale; counters reset on
    # deploy/restart (noted in README).
    RATELIMIT_STORAGE_URI = "memory://"

    # PRELAUNCH: set PRELAUNCH_LOCK=0 on the host to open the site at launch.
    # Default off here; ProdConfig turns it on. See app/services/prelaunch.py.
    PRELAUNCH_LOCK = os.environ.get("PRELAUNCH_LOCK", "").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _strip_config_quotes(value: str) -> str:
    v = (value or "").strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        v = v[1:-1].strip()
    return v


# Normalize env pastes once at import (Render/dashboard often wrap in quotes).
Config.BREVO_API_KEY = _strip_config_quotes(Config.BREVO_API_KEY)
Config.MAIL_FROM = _strip_config_quotes(Config.MAIL_FROM)
Config.TURNSTILE_SITE_KEY = _strip_config_quotes(Config.TURNSTILE_SITE_KEY)
Config.TURNSTILE_SECRET = _strip_config_quotes(Config.TURNSTILE_SECRET)
Config.TURNSTILE_SECRET_KEY = Config.TURNSTILE_SECRET
Config.DAILY_API_KEY = _strip_config_quotes(Config.DAILY_API_KEY)
Config.DAILY_DOMAIN = _strip_config_quotes(Config.DAILY_DOMAIN) or "bloomanyway"
Config.ZOOM_ACCOUNT_ID = _strip_config_quotes(Config.ZOOM_ACCOUNT_ID)
Config.ZOOM_CLIENT_ID = _strip_config_quotes(Config.ZOOM_CLIENT_ID)
Config.ZOOM_CLIENT_SECRET = _strip_config_quotes(Config.ZOOM_CLIENT_SECRET)
Config.ZOOM_HOST_EMAIL = _strip_config_quotes(Config.ZOOM_HOST_EMAIL)


class DevConfig(Config):
    DEBUG = True
    SESSION_COOKIE_SECURE = False
    REMEMBER_COOKIE_SECURE = False
    # Local/smoke: lock off unless you explicitly set PRELAUNCH_LOCK=1.
    PRELAUNCH_LOCK = os.environ.get("PRELAUNCH_LOCK", "0").strip().lower() in (
        "1", "true", "yes", "on",
    )
    # Zero-config local dev: a fixed dev key unless one is provided.
    SECRET_KEY = os.environ.get("SECRET_KEY", "").strip() or "dev-only-not-secret"
    # Cloudflare always-pass test keys when no real secret is set (Turnstile docs).
    TURNSTILE_SITE_KEY = (
        os.environ.get("TURNSTILE_SITE_KEY", "").strip()
        or "1x00000000000000000000AA"
    )
    TURNSTILE_SECRET = (
        os.environ.get("TURNSTILE_SECRET", "").strip()
        or os.environ.get("TURNSTILE_SECRET_KEY", "").strip()
        or "1x0000000000000000000000000000000AA"
    )
    TURNSTILE_SECRET_KEY = TURNSTILE_SECRET

class ProdConfig(Config):
    DEBUG = False
    PREFERRED_URL_SCHEME = "https"
    SESSION_COOKIE_SECURE = True
    REMEMBER_COOKIE_SECURE = True
    # Prelaunch default ON — set PRELAUNCH_LOCK=0 (or false) to open at launch.
    PRELAUNCH_LOCK = os.environ.get("PRELAUNCH_LOCK", "1").strip().lower() not in (
        "0", "false", "no", "off", "",
    )

    #: the only env vars that must be present in prod (everything else is
    #: optional or auto-managed)
    REQUIRED_ENV = (
        "DATABASE_URL",
        "MAIL_FROM",
    )
    #: at least one email transport must be configured
    SMTP_ENV = ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD")

    @classmethod
    def validate(cls) -> None:
        def unset(name):
            return os.environ.get(name, "").strip() == ""

        def strip_quotes(value: str) -> str:
            v = (value or "").strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1].strip()
            return v

        missing = [name for name in cls.REQUIRED_ENV if unset(name)]
        if unset("BREVO_API_KEY") and any(unset(name) for name in cls.SMTP_ENV):
            missing.append("BREVO_API_KEY or all of SMTP_HOST/SMTP_PORT/SMTP_USER/SMTP_PASSWORD")
        # Turnstile: site key defaults to the dashboard widget; set TURNSTILE_SECRET
        # on the host so signup siteverify can succeed.
        mail_from = strip_quotes(os.environ.get("MAIL_FROM", ""))
        if mail_from and ("@" not in mail_from or mail_from.lower().endswith("@localhost")):
            missing.append("MAIL_FROM (must be a real verified sender, not @localhost)")
        if missing:
            raise RuntimeError(
                "Refusing to start in production. Missing/placeholder env vars: "
                + ", ".join(missing)
            )
        # A SQLite database in production lives on an ephemeral disk (wiped on
        # every restart/deploy), which silently loses the owner account, orders,
        # etc. Force a real, persistent database.
        if cls.SQLALCHEMY_DATABASE_URI.startswith("sqlite"):
            raise RuntimeError(
                "Refusing to start in production with a SQLite database — it is "
                "not persistent. Attach a managed Postgres database and set "
                "DATABASE_URL to its connection string."
            )


def get_config():
    env = os.environ.get("APP_ENV", "").lower()
    # Render sets RENDER=true on every service. If APP_ENV wasn't set explicitly
    # we still force production there, so the app uses the managed (persistent)
    # Postgres via DATABASE_URL instead of ephemeral SQLite — otherwise the disk
    # is wiped on every restart/deploy and the owner account "resets".
    if not env and os.environ.get("RENDER"):
        env = "production"
    if not env:
        env = "development"
    if env == "production":
        ProdConfig.validate()
        return ProdConfig
    return DevConfig
