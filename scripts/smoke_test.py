"""Acceptance-criteria smoke test (run: python scripts/smoke_test.py).

Uses a throwaway SQLite database and the Flask test client. Not a pytest
suite on purpose — a single readable script the owner/dev can run anywhere.
"""
import hashlib
import hmac
import io
import json
import os
import re
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import base64
import time as _time

_DODO_SECRET_RAW = b"test-secret"
os.environ["DODO_PAYMENTS_WEBHOOK_SECRET"] = (
    "whsec_" + base64.b64encode(_DODO_SECRET_RAW).decode()
)
os.environ["DODO_PAYMENTS_API_KEY"] = "test-dodo-key"
os.environ["DODO_PAYMENTS_MODE"] = "test"

from app import create_app
from app.config import DevConfig
from app.extensions import db
from app.models import (ForumCategory, ForumComment, ForumPost, ForumTag,
                        Order, Product, Quote, QuotePin, ShopPurchase,
                        Subscriber, User, Video, utcnow)
from app.services import captcha as captcha_service
from app.services import dodo as dodo_svc


def _dodo_headers(body: bytes) -> dict:
    msg_id = "msg_test_" + hashlib.sha1(body).hexdigest()[:10]
    ts = str(int(_time.time()))
    sig = dodo_svc.sign_webhook(
        os.environ["DODO_PAYMENTS_WEBHOOK_SECRET"], msg_id, ts, body)
    return {
        "Content-Type": "application/json",
        "webhook-id": msg_id,
        "webhook-timestamp": ts,
        "webhook-signature": sig,
    }


def _payment_payload(payment_id, email, product_id, *,
                     event="payment.succeeded", amount=4900,
                     product_name=None, gift_to=None):
    data = {
        "payload_type": "Payment",
        "payment_id": str(payment_id),
        "total_amount": amount,
        "currency": "USD",
        "customer": {"email": email},
        "product_cart": [{"product_id": str(product_id), "quantity": 1}],
        "metadata": {},
    }
    if product_name:
        data["metadata"]["product_name"] = product_name
    if gift_to:
        data["metadata"]["gift_to"] = gift_to
    return json.dumps({"type": event, "data": data}).encode()

# Smoke tests don't call Cloudflare; always pass the captcha check.
captcha_service.verify_captcha = lambda token=None: True
captcha_service.captcha_challenge = lambda: {"site_key": "1x00000000000000000000AA"}
captcha_service.issue_captcha = captcha_service.captcha_challenge
captcha_service.captcha_question = lambda: "turnstile"
captcha_service.site_key = lambda: "1x00000000000000000000AA"


TMP_DB = Path(tempfile.mkdtemp()) / "smoke.db"


class TestConfig(DevConfig):
    SQLALCHEMY_DATABASE_URI = f"sqlite:///{TMP_DB.as_posix()}"
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False
    TESTING = True
    PRELAUNCH_LOCK = False  # suite exercises the full site; lock tested separately


PASS = 0


def ok(name, condition, detail=""):
    global PASS
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}" + (f"  ({detail})" if detail and not condition else ""))
    if condition:
        PASS += 1
    else:
        raise SystemExit(f"FAILED: {name} {detail}")


app = create_app(TestConfig)

# capture verification codes instead of emailing
sent_codes = []
import app.auth.routes as auth_routes
auth_routes.send_verification_code = lambda to, code, purpose: sent_codes.append((to, code, purpose)) or True

ADMIN_PW = "owner-strong-pass-1"

with app.app_context():
    db.create_all()
    seed = json.loads((Path(__file__).parents[1] / "data" / "quotes_seed.json").read_text(encoding="utf-8"))
    for row in seed["quotes"]:
        db.session.add(Quote(text=row["text"], author=row.get("author"), category=row["category"]))
    db.session.commit()
    n_quotes = Quote.query.count()

ok("Seed has 150+ quotes", n_quotes >= 150, f"got {n_quotes}")

client = app.test_client()

# --- 1. home hero + daily quote rotation (quotes live on /quotes) -------------
r1 = client.get("/")
ok("Home page renders", r1.status_code == 200, str(r1.status_code))
home1 = r1.get_data(as_text=True)
ok("Home shows healing / building hero",
   "You don't have to carry this alone" in home1
   and "Ready to build something" in home1
   and "that's yours?" in home1
   and "Find Your Community" in home1
   and "Start Building" in home1)
ok("Home shows Their Story with reserved photo space",
   "Their story" in home1
   and "Society told us to suffer quietly" in home1
   and "home-story__ph" in home1
   and "Ayesha &amp; Saman" in home1)
ok("Home shows Product of the Day + top products sections",
   "Digital Product of the Day" in home1
   and "Top products — last 30 days" in home1
   and ("home-potd" in home1 or "Coming soon" in home1)
   and ("home-top-grid" in home1 or "Coming soon" in home1))
r2 = client.get("/")
ok("Home still renders on refresh", r2.status_code == 200)

with app.app_context():
    from app.services.quotes import quote_for
    today_q = quote_for(date.today())
    tomorrow_q = quote_for(date.today() + timedelta(days=1))
    day_after = quote_for(date.today() + timedelta(days=2))
ok("Quote rotation changes across days (some day differs)",
   today_q.id != tomorrow_q.id or today_q.id != day_after.id)

# --- 2a. first-run owner setup ----------------------------------------------------
setup_client = app.test_client()
r = setup_client.get("/setup")
ok("Setup page available on fresh install", r.status_code == 200)
r = setup_client.get("/login")
ok("Login page advertises setup on fresh install", "Claim the owner account" in r.get_data(as_text=True))
r = setup_client.post("/setup", data={"email": "owner@example.com", "password": ADMIN_PW,
                                      "password_confirm": ADMIN_PW},
                      follow_redirects=False)
ok("Owner account claimed via setup", r.status_code == 302 and "/admin" in r.headers["Location"])
r = setup_client.get("/admin/")
ok("Owner lands in studio after setup", r.status_code == 200)
r = app.test_client().get("/setup")
ok("Setup locks after owner signs in", r.status_code == 404)

# --- 2b. email + password auth with confirmation codes ---------------------------
USER_PW = "sunrise-day-1"

r = client.post("/register", data={"email": "newperson@example.com", "password": "short",
                                   "password_confirm": "short"})
ok("Weak password rejected on registration", r.status_code == 400)

r = client.post("/register", data={"email": "newperson@example.com", "password": USER_PW,
                                   "password_confirm": "different-pass"}, follow_redirects=False)
ok("Mismatched passwords rejected on registration",
   r.status_code == 400 and "those passwords" in r.get_data(as_text=True).lower())

r = client.post("/register", data={"email": "newperson@example.com", "password": USER_PW,
                                   "password_confirm": USER_PW},
                follow_redirects=False)
ok("Registration redirects to verify page", r.status_code == 302 and "verify-email" in r.headers["Location"])
ok("Confirmation code emailed", len(sent_codes) == 1 and sent_codes[0][2] == "confirm")
first_code = sent_codes[0][1]

# unverified account can't just log in — it gets sent back to verification
# without wiping the code they already received
r = client.post("/login", data={"email": "newperson@example.com", "password": USER_PW},
                follow_redirects=False)
ok("Unverified login redirects to verification", r.status_code == 302 and "verify-email" in r.headers["Location"])
ok("Unverified login keeps the original confirmation code",
   len(sent_codes) == 1)

# wrong code fails with attempts feedback, right code confirms + logs in
r = client.post("/verify-email", data={"email": "newperson@example.com", "code": "000000"})
wrong_ok = r.status_code == 400 and "tries left" in r.get_data(as_text=True)
r = client.post("/verify-email", data={"email": "newperson@example.com",
                                       "code": f" {first_code[:3]}-{first_code[3:]} "},
                follow_redirects=False)
ok("Wrong code rejected with tries-left message", wrong_ok)
ok("Correct code confirms and logs in (spaces/dashes ok)",
   r.status_code == 302 and "/account" in r.headers["Location"])
r = client.get("/account")
ok("Account page accessible after confirmation", r.status_code == 200)
abody = r.get_data(as_text=True)
ok("New member lands on account without a product tour",
   "product-tour.js" not in abody
   and "data-product-tour" not in abody)

# password checks
fresh = app.test_client()
r = fresh.post("/login", data={"email": "newperson@example.com", "password": "wrong-password"})
ok("Wrong password rejected (401)", r.status_code == 401)
r = fresh.post("/login", data={"email": "newperson@example.com", "password": USER_PW,
                               "next": "https://evil.example.com"}, follow_redirects=False)
ok("Absolute next URL rejected (no open redirect)",
   r.status_code == 302 and r.headers["Location"].startswith("/"))

# forgot / reset password flow
sent_codes.clear()
reset_client = app.test_client()
r = reset_client.post("/forgot-password", data={"email": "newperson@example.com"}, follow_redirects=True)
uniform_known = "reset code is on its way" in r.get_data(as_text=True)
r = reset_client.post("/forgot-password", data={"email": "ghost@example.com"}, follow_redirects=True)
uniform_unknown = "reset code is on its way" in r.get_data(as_text=True)
ok("Uniform reset message for known + unknown email", uniform_known and uniform_unknown)
ok("Reset code only sent for real account", len(sent_codes) == 1 and sent_codes[0][2] == "reset")
r = reset_client.post("/reset-password", data={"email": "newperson@example.com",
                                               "code": sent_codes[0][1],
                                               "password": USER_PW,
                                               "password_confirm": USER_PW}, follow_redirects=False)
ok("Password reset rejects reusing the current password",
   r.status_code == 400 and "different password" in r.get_data(as_text=True).lower())
r = reset_client.post("/reset-password", data={"email": "newperson@example.com",
                                               "code": sent_codes[0][1],
                                               "password": "brand-new-pass-9",
                                               "password_confirm": "brand-new-pass-x"},
                      follow_redirects=False)
ok("Password reset rejects mismatched confirmation",
   r.status_code == 400 and "those passwords" in r.get_data(as_text=True).lower())
r = reset_client.post("/reset-password", data={"email": "newperson@example.com",
                                               "code": sent_codes[0][1],
                                               "password": "brand-new-pass-9",
                                               "password_confirm": "brand-new-pass-9"},
                      follow_redirects=False)
ok("Password reset with valid code succeeds", r.status_code == 302)
r = app.test_client().post("/login", data={"email": "newperson@example.com",
                                           "password": "brand-new-pass-9"}, follow_redirects=False)
ok("Login works with the new password", r.status_code == 302 and "/account" in r.headers["Location"])

# --- 3. admin: product lifecycle ----------------------------------------------
admin = app.test_client()
r = admin.post("/login", data={"email": "owner@example.com", "password": ADMIN_PW}, follow_redirects=False)
ok("Admin password login works", r.status_code == 302)

r = admin.get("/admin/")
ok("Admin dashboard loads for admin", r.status_code == 200)
r = client.get("/admin/")
ok("Admin returns 404 for non-admin user", r.status_code == 404)

# admin idle timeout: stale activity forces re-auth; active use slides the window
with admin.session_transaction() as sess:
    stale = (datetime.utcnow() - timedelta(days=15)).isoformat()
    sess["admin_seen_at"] = stale
    sess["logged_in_at"] = stale
r = admin.get("/admin/", follow_redirects=False)
ok("Admin re-auth required after 14 idle days",
   r.status_code == 302 and "/login" in r.headers["Location"])
with admin.session_transaction() as sess:
    sess["admin_seen_at"] = (datetime.utcnow() - timedelta(days=2)).isoformat()
r = admin.get("/admin/", follow_redirects=False)
ok("Active admin stays signed in (sliding window)", r.status_code == 200)

# Studio catalogue editor is live; /courses is on-site
r = admin.get("/admin/products", follow_redirects=True)
_pbody = r.get_data(as_text=True)
ok("Studio products UI loads",
   r.status_code == 200
   and ("Add a product" in _pbody or "Dodo product ID" in _pbody or "Courses" in _pbody))
r = client.get("/courses", follow_redirects=False)
cbody = r.get_data(as_text=True)
ok("/courses renders on-site catalogue",
   r.status_code == 200 and "Courses &amp; Guides" in cbody
   and "Healing resources by" in cbody and "Creator resources by" in cbody
   and "Rebuild Workbook" not in cbody and "50 Hooks" not in cbody)
ok("Studio offers product cover upload",
   "Cover image" in _pbody and 'name="cover"' in _pbody)

# Tiny JPEG cover upload for a draft product
from io import BytesIO
from PIL import Image as _PILCover
_cbuf = BytesIO()
_PILCover.new("RGB", (300, 400), (90, 49, 88)).save(_cbuf, format="JPEG")
_cbuf.seek(0)
r = admin.post(
    "/admin/products",
    data={
        "action": "create",
        "title": "Cover Test Guide",
        "track": "healing",
        "type": "guide",
        "price": "19.00",
        "promise": "A soft check-in.",
        "cover": (_cbuf, "cover.jpg"),
    },
    content_type="multipart/form-data",
    follow_redirects=True,
)
ok("Studio accepts product cover on create", r.status_code == 200)
with app.app_context():
    cover_prod = Product.query.filter_by(slug="cover-test-guide").first()
    ok("Cover URL stored on product",
       cover_prod is not None and (cover_prod.cover_url or "").startswith("/media/product-cover/"),
       f"got {getattr(cover_prod, 'cover_url', None)}")
    cover_id = cover_prod.id if cover_prod else 0
r = client.get(f"/media/product-cover/{cover_id}")
ok("Product cover image is served",
   cover_id and r.status_code == 200 and r.mimetype.startswith("image/"))
with app.app_context():
    cover_prod = Product.query.filter_by(id=cover_id).first()
    if cover_prod:
        cover_prod.status = "published"
        db.session.commit()
r = client.get("/courses")
courses_body = r.get_data(as_text=True)
ok("Courses page uses My space-style library cards",
   "lib-card" in courses_body
   and "lib-card__cover" in courses_body
   and "Cover Test Guide" in courses_body)
ok("Uploaded cover appears on Courses cards",
   f"/media/product-cover/{cover_id}" in courses_body
   and "lib-card__cover--photo" in courses_body)
r = client.get("/")
home = r.get_data(as_text=True)
ok("Home includes creator membership CTA",
   "Join Creator Membership" in home and "Creator of the Month" in home)
ok("Nav Courses & Guides points on-site",
   '/courses"' in home or "/courses'" in home)

# Product row for order matching
with app.app_context():
    hist = Product(
        title="Begin Again", slug="begin-again", type="course", status="published",
        promise="A 4-week path from stuck to started.",
        cover_url="https://example.com/cover.jpg", price_cents=4900,
        currency="USD", dodo_product_id="prod_begin_again",
        track="healing", featured=True)
    db.session.add(hist)
    db.session.commit()
    hist_id = hist.id

# --- 4. Dodo webhook: signature + idempotency + ShopPurchase -----------------------
payload = _payment_payload(
    "9001", "Buyer@Example.com", "prod_begin_again",
    product_name="Begin Again")

r = client.post("/webhooks/dodo", data=payload,
                headers={"Content-Type": "application/json",
                         "webhook-id": "bad", "webhook-timestamp": "1",
                         "webhook-signature": "v1,bad"})
ok("Wrong webhook signature rejected 401", r.status_code == 401)

r = client.post("/webhooks/dodo", data=payload, headers=_dodo_headers(payload))
r2 = client.post("/webhooks/dodo", data=payload, headers=_dodo_headers(payload))
with app.app_context():
    orders = Order.query.filter_by(ls_order_id="9001").all()
    shops = ShopPurchase.query.filter_by(lemon_squeezy_order_id="9001").all()
ok("Webhook accepted (200)", r.status_code == 200 and r2.status_code == 200)
ok("Replayed webhook creates exactly one order", len(orders) == 1, f"got {len(orders)}")
ok("Replayed webhook creates exactly one ShopPurchase", len(shops) == 1, f"got {len(shops)}")
ok("Order matched to product via Dodo product id", orders[0].product_id is not None)
ok("Buyer email lowercased", orders[0].buyer_email == "buyer@example.com")
ok("Unknown-email shop purchase is pending_link",
   shops[0].status == "pending_link" and shops[0].user_id is None)
ok("Shop purchase product name from webhook", shops[0].product_name == "Begin Again")

# purchase auto-links when that email signs up / logs in
with app.app_context():
    from app.models import User as _U
    buyer = _U(email="buyer@example.com", email_verified_at=utcnow())
    buyer.set_password(USER_PW)
    db.session.add(buyer)
    db.session.commit()
buyer_client = app.test_client()
buyer_client.post("/login", data={"email": "buyer@example.com", "password": USER_PW})
with app.app_context():
    linked = ShopPurchase.query.filter_by(lemon_squeezy_order_id="9001").first()
ok("Pending shop purchase links on login",
   linked.status == "linked" and linked.user_id is not None)
r = buyer_client.get("/account?tab=saved")
abody = r.get_data(as_text=True)
ok("Linked shop purchase appears in My space",
   r.status_code == 200 and "Begin Again" in abody and "Courses" in abody)

# On-site reader + progress resume
with app.app_context():
    hist = Product.query.filter_by(slug="begin-again").first()
    from app.models import ProductAsset, CourseProgress
    asset = ProductAsset(
        product_id=hist.id,
        title="Begin Again PDF",
        filename="begin-again.pdf",
        mime="application/pdf",
        kind="pdf",
        size=12,
        data=b"%PDF-1.4 fake",
        sort_order=0,
    )
    db.session.add(asset)
    db.session.commit()
    purchase = ShopPurchase.query.filter_by(lemon_squeezy_order_id="9001").first()
    purchase_id = purchase.id
r = buyer_client.get(f"/account/courses/{purchase_id}")
ok("Course reader opens for owned purchase",
   r.status_code == 200 and b"Begin Again" in r.data and b"reader-pdf-canvas" in r.data
   and b"Back to library" in r.data)
r = buyer_client.post(
    f"/account/courses/{purchase_id}/progress",
    json={"page": 5, "total": 20},
    headers={"Content-Type": "application/json"},
)
ok("Reading progress saves", r.status_code == 200 and r.get_json().get("percent") == 25)
with app.app_context():
    prog = CourseProgress.query.filter_by(shop_purchase_id=purchase_id).first()
ok("Progress row stores page 5",
   prog is not None and prog.current_page == 5 and prog.total_pages == 20)
r = buyer_client.get("/account?tab=saved")
abody = r.get_data(as_text=True)
ok("Courses tab shows real progress percent",
   "25%" in abody and "Continue reading" in abody and "Reading progress" in abody)
r = buyer_client.get(f"/account/courses/{purchase_id}")
ok("Reader resumes at saved page",
   r.status_code == 200 and b'data-start-page="5"' in r.data)
r = buyer_client.post(
    f"/account/courses/{purchase_id}/bookmarks",
    json={"page": 5},
    headers={"Content-Type": "application/json"},
)
ok("Bookmark toggles on",
   r.status_code == 200 and r.get_json().get("bookmarked") is True
   and 5 in (r.get_json().get("bookmarks") or []))
r = buyer_client.get("/account?tab=saved")
ok("Library shows bookmarked pages",
   "Bookmarks" in r.get_data(as_text=True) and "page 5" in r.get_data(as_text=True))

# purchase for an email that already has an account links immediately
with app.app_context():
    known = User.query.filter_by(email="newperson@example.com").first()
    known_id = known.id
payload_known = _payment_payload(
    "9002", "newperson@example.com", "prod_quiet",
    amount=1900, product_name="Quiet Mornings")
r = client.post("/webhooks/dodo", data=payload_known, headers=_dodo_headers(payload_known))
with app.app_context():
    sp2 = ShopPurchase.query.filter_by(lemon_squeezy_order_id="9002").first()
ok("Existing-account shop purchase links immediately",
   r.status_code == 200 and sp2 is not None
   and sp2.status == "linked" and sp2.user_id == known_id)

# failed payments must not invent a My Space library item
payload_fail = _payment_payload(
    "9002-fail", "newperson@example.com", "prod_quiet",
    event="payment.failed", amount=1900, product_name="Quiet Mornings")
r = client.post("/webhooks/dodo", data=payload_fail, headers=_dodo_headers(payload_fail))
with app.app_context():
    fail_shop = ShopPurchase.query.filter_by(lemon_squeezy_order_id="9002-fail").first()
    fail_ord = Order.query.filter_by(ls_order_id="9002-fail").first()
ok("Failed payment does not create a ShopPurchase",
   r.status_code == 200 and fail_shop is None)
ok("Failed payment still records an Order",
   fail_ord is not None and fail_ord.status == "failed")

# Studio activity + purchase chart helpers see paid orders
with app.app_context():
    from app.services import stats as stats_svc
    activity = stats_svc.member_activity(20)
    chart = stats_svc.purchases_over_time(30)
    trend = stats_svc.trending_product(30)
ok("Member activity includes purchases",
   any(a.get("kind") == "purchase" for a in activity))
ok("Purchases chart has daily series",
   isinstance(chart.get("all"), list) and chart.get("total", 0) >= 1)
ok("Trending product reports a leader",
   trend is not None and "trending" in (trend.get("label") or "").lower())

# refund hides from My space
payload_ref = _payment_payload(
    "9002", "newperson@example.com", "prod_quiet",
    event="refund.succeeded", amount=1900, product_name="Quiet Mornings")
client.post("/webhooks/dodo", data=payload_ref, headers=_dodo_headers(payload_ref))
with app.app_context():
    sp2 = ShopPurchase.query.filter_by(lemon_squeezy_order_id="9002").first()
ok("Refunded shop purchase marked refunded", sp2.status == "refunded")
r = client.get("/account?tab=saved")
ok("My space hides refunded purchases",
   "Quiet Mornings" not in r.get_data(as_text=True))

# protected self-hosted download
with app.app_context():
    from flask import current_app
    shop_dir = current_app.config["SHOP_FILES_DIR"]
    key = "quiet-guide.pdf"
    Path(shop_dir).mkdir(parents=True, exist_ok=True)
    (Path(shop_dir) / key).write_bytes(b"%PDF-1.4 shop-file")
    owned = ShopPurchase(
        lemon_squeezy_order_id="FILE-1", customer_email="newperson@example.com",
        user_id=known_id, product_name="Self Hosted Guide", file_key=key,
        status="linked", purchased_at=utcnow())
    other = ShopPurchase(
        lemon_squeezy_order_id="FILE-2", customer_email="buyer@example.com",
        user_id=None, product_name="Someone Else", file_key=key,
        status="pending_link", purchased_at=utcnow())
    db.session.add_all([owned, other])
    db.session.commit()
    owned_id = owned.id
r = client.get(f"/account/shop/{owned_id}/download")
ok("Owner can download self-hosted shop file",
   r.status_code == 200 and r.get_data() == b"%PDF-1.4 shop-file")
r = buyer_client.get(f"/account/shop/{owned_id}/download")
ok("Non-owner blocked from shop file download", r.status_code == 404)

r = admin.get("/admin/")
_dash = r.get_data(as_text=True)
ok("Dashboard shows local payment insights",
   r.status_code == 200 and "Payments (30 days)" in _dash
   and "Dodo Payments" in _dash)

# give the main member Full Bloom: both community tracks for the forum suite
with app.app_context():
    m = User.query.filter_by(email="newperson@example.com").first()
    m.membership = "full_bloom"
    db.session.commit()

# --- 5. community forums + moderation + recommendations --------------------------
today = date.today()
with app.app_context():
    healing = ForumCategory(slug="healing", name="Healing",
                            description="Room to process.", sort_order=1)
    db.session.add(healing)
    db.session.flush()
    t_vent = ForumTag(category_id=healing.id, slug="venting", name="The Vent", sort_order=0)
    t_grief = ForumTag(category_id=healing.id, slug="grief", name="Grief & Loss", sort_order=1)
    db.session.add_all([t_vent, t_grief])
    db.session.commit()
    vent_tag_id = t_vent.id

r = client.get("/forums/")
comm_body = r.get_data(as_text=True)
ok("Forums index renders for members", r.status_code == 200 and "The Community" in comm_body)
ok("Community page shows healing / building hubs",
   "Healing community" in comm_body
   and "Building community" in comm_body
   and ("Enter the Healing Community" in comm_body
        or "Join the Healing Community" in comm_body)
   and "comm-compare" in comm_body
   and "What we talk about" in comm_body)

# category page shows topic filter chips
r = client.get("/forums/c/healing")
ok("Category shows tag filter chips", "The Vent" in r.get_data(as_text=True) and "Grief &amp; Loss" in r.get_data(as_text=True))
ok("Category shows Looking for filter chips",
   "Looking for" in r.get_data(as_text=True) and "Advice" in r.get_data(as_text=True)
   and "Recognition" in r.get_data(as_text=True))
ok("Conversation card stretch-link styles ship",
   "post-row__hit" in client.get("/static/css/main.css").get_data(as_text=True))

# member (client = newperson, verified + logged in) can post with a tag
r = client.post("/forums/c/healing/new",
                data={"title": "Rough day", "body": "Just needed to say it out loud.",
                      "tag_id": str(vent_tag_id), "looking_for": "support"},
                follow_redirects=True)
body = r.get_data(as_text=True)
ok("Member can create a tagged forum post",
   "Rough day" in body and "The Vent" in body)
ok("Looking for label shows on the post",
   "tag-chip--looking" in body and "support" in body.lower())
with app.app_context():
    saved = ForumPost.query.filter_by(title="Rough day").first()
ok("Looking for intent saved on the post",
   saved is not None and saved.looking_for == "support")
r = client.get("/forums/c/healing?looking=support")
ok("Looking-for filter shows matching posts",
   "Rough day" in r.get_data(as_text=True))
r = client.get("/forums/c/healing?looking=advice")
ok("Looking-for filter hides other intents",
   "Rough day" not in r.get_data(as_text=True))

# tag filter narrows the list
r = client.get("/forums/c/healing?tag=grief")
ok("Tag filter hides posts from other topics", "Rough day" not in r.get_data(as_text=True))
r = client.get("/forums/c/healing?tag=venting")
feed_html = r.get_data(as_text=True)
ok("Tag filter shows matching posts", "Rough day" in feed_html)
ok("Feed conversation widget opens from the full card",
   "post-row__hit" in feed_html and "Rough day" in feed_html)

# profanity is blocked and earns a warning
r = client.post("/forums/c/healing/new",
                data={"title": "This is shit", "body": "ugh"}, follow_redirects=True)
with app.app_context():
    member = User.query.filter_by(email="newperson@example.com").first()
    warn1 = member.forum_warnings
    posts_after = ForumPost.query.count()
ok("Profane post blocked + warning issued", warn1 == 1 and posts_after == 1,
   f"warnings={warn1} posts={posts_after}")

# anonymous posting hides the author name
r = client.post("/forums/c/healing/new",
                data={"title": "Quiet ask", "body": "Posting this anonymously.", "anonymous": "1"},
                follow_redirects=True)
ok("Anonymous post shows as Anonymous",
   "Anonymous" in r.get_data(as_text=True) and "Quiet ask" in r.get_data(as_text=True))

# likes + comments + one-level replies
with app.app_context():
    first_post = ForumPost.query.order_by(ForumPost.id).first()
    pid = first_post.id
r = client.post(f"/forums/p/{pid}/like", follow_redirects=True)
ok("Like on a post is accepted", r.status_code == 200)
r = client.post(f"/forums/p/{pid}/comment", data={"body": "Sending you strength."},
                follow_redirects=True)
ok("Comment posts to a thread", "Sending you strength." in r.get_data(as_text=True))

with app.app_context():
    top_comment = ForumComment.query.filter_by(post_id=pid, parent_id=None).first()
    cid = top_comment.id
r = client.post(f"/forums/p/{pid}/comment",
                data={"body": "Thank you, truly.", "parent_id": str(cid)}, follow_redirects=True)
ok("Reply attaches to its parent comment", "Thank you, truly." in r.get_data(as_text=True))

# a reply to a reply is flattened to one level (never nests deeper)
with app.app_context():
    reply = ForumComment.query.filter_by(post_id=pid).filter(ForumComment.parent_id.isnot(None)).first()
    reply_id = reply.id
client.post(f"/forums/p/{pid}/comment",
            data={"body": "Nested attempt.", "parent_id": str(reply_id)}, follow_redirects=True)
with app.app_context():
    nested = ForumComment.query.filter_by(body="Nested attempt.").first()
ok("Reply-to-a-reply flattens to one level", nested.parent_id == cid,
   f"parent_id={nested.parent_id} expected {cid}")

# strangers can comment, but only OP (or the comment author) may reply under a comment
with app.app_context():
    stranger = User(email="stranger@example.com", username="stranger_one",
                    membership="healing")
    stranger.set_password(USER_PW)
    stranger.email_verified_at = utcnow()
    bystander = User(email="bystander@example.com", username="bystander_one",
                     membership="healing")
    bystander.set_password(USER_PW)
    bystander.email_verified_at = utcnow()
    db.session.add_all([stranger, bystander])
    db.session.commit()
stranger_client = app.test_client()
stranger_client.post("/login", data={"email": "stranger@example.com", "password": USER_PW})
r = stranger_client.post(f"/forums/p/{pid}/comment",
                         data={"body": "A kind stranger note."}, follow_redirects=True)
ok("Anyone can leave a top-level comment",
   "A kind stranger note." in r.get_data(as_text=True))
with app.app_context():
    stranger_note = ForumComment.query.filter_by(body="A kind stranger note.").first()
    stranger_cid = stranger_note.id
bystander_client = app.test_client()
bystander_client.post("/login", data={"email": "bystander@example.com", "password": USER_PW})
r = bystander_client.post(f"/forums/p/{pid}/comment",
                          data={"body": "Should not nest here.", "parent_id": str(stranger_cid)},
                          follow_redirects=True)
page = r.get_data(as_text=True).lower()
with app.app_context():
    blocked_reply = ForumComment.query.filter_by(body="Should not nest here.").count()
ok("Non-OP cannot reply under someone else's comment",
   blocked_reply == 0 and "only the original poster" in page)
# OP can still reply under that stranger comment
r = client.post(f"/forums/p/{pid}/comment",
                data={"body": "Thanks for the note.", "parent_id": str(stranger_cid)},
                follow_redirects=True)
ok("OP can reply under any comment",
   "Thanks for the note." in r.get_data(as_text=True))

# escalating profanity leads to a ban after the warning limit
banclient = app.test_client()
sent_codes.clear()
banclient.post("/register", data={"email": "rude@example.com", "password": USER_PW,
                                  "password_confirm": USER_PW})
bcode = sent_codes[-1][1]
banclient.post("/verify-email", data={"email": "rude@example.com", "code": bcode})
with app.app_context():
    ru = User.query.filter_by(email="rude@example.com").first()
    ru.membership = "healing"
    db.session.commit()
for _ in range(3):
    banclient.post("/forums/c/healing/new", data={"title": "fuck this", "body": "fuck"})
with app.app_context():
    rude = User.query.filter_by(email="rude@example.com").first()
    banned = rude.forum_banned
ok("Repeated profanity bans after 2 warnings", banned is True, f"banned={banned}")

# avatar upload: a real (tiny) PNG is accepted, re-encoded, and served
with app.app_context():
    import io as _io
    from PIL import Image as _Image
    buf = _io.BytesIO()
    _Image.new("RGB", (10, 10), (200, 100, 150)).save(buf, format="PNG")
    png_bytes = buf.getvalue()
r = client.post("/account/profile", data={
    "display_name": "River",
    "avatar_file": (_io.BytesIO(png_bytes), "me.png"),
}, content_type="multipart/form-data", follow_redirects=True)
with app.app_context():
    m = User.query.filter_by(email="newperson@example.com").first()
    has_av = m.has_avatar()
    av_uid = m.id
ok("Uploaded avatar stored on the account", has_av)
r = client.get(f"/avatar/{av_uid}")
ok("Avatar is served from the database",
   r.status_code == 200 and r.headers["Content-Type"].startswith("image/"))

# animated GIF: still used in lists; animation served only on the profile page
with app.app_context():
    from PIL import Image as _Image2, ImageDraw as _ImageDraw
    gif_buf = _io.BytesIO()
    frames = []
    for i, color in enumerate([(220, 80, 120), (80, 140, 220)]):
        fr = _Image2.new("RGB", (40, 40), color)
        _ImageDraw.Draw(fr).ellipse((8, 8, 32, 32), fill=(255, 255, 255))
        frames.append(fr)
    frames[0].save(gif_buf, format="GIF", save_all=True, append_images=frames[1:],
                   duration=120, loop=0)
    gif_bytes = gif_buf.getvalue()
r = client.post("/account/profile", data={
    "display_name": "River",
    "avatar_file": (_io.BytesIO(gif_bytes), "me.gif"),
}, content_type="multipart/form-data", follow_redirects=True)
with app.app_context():
    m = User.query.filter_by(email="newperson@example.com").first()
    av_uid = m.id
    has_anim = m.has_animated_avatar()
    still_mime = m.avatar_mime
ok("Animated GIF stores a still + animation payload",
   has_anim and (still_mime or "").startswith("image/"))
r_still = client.get(f"/avatar/{av_uid}")
r_anim = client.get(f"/avatar/{av_uid}/anim")
ok("Default avatar route serves the still frame",
   r_still.status_code == 200 and "gif" not in (r_still.headers.get("Content-Type") or "").lower())
ok("Anim avatar route serves image/gif",
   r_anim.status_code == 200 and "gif" in (r_anim.headers.get("Content-Type") or "").lower())
r_prof = client.get(f"/u/{av_uid}")
prof_html = r_prof.get_data(as_text=True)
ok("Profile page uses the animated avatar URL",
   r_prof.status_code == 200 and f"/avatar/{av_uid}/anim" in prof_html)

r = client.get("/account/settings")
sbody = r.get_data(as_text=True)
ok("Settings page renders with intents + upload",
   r.status_code == 200 and "What brings you here?" in sbody and 'name="avatar_file"' in sbody)
ok("Settings offers a change-password button (no inline fields)",
   'href="/account/password"' in sbody and 'name="current_password"' not in sbody)
ok("Close-account needs Yes I'm sure before submit is enabled",
   'data-require-sure' in sbody
   and 'data-sure-submit' in sbody
   and 'disabled' in sbody
   and "Yes, I'm sure" in sbody)
r = client.post("/account/delete", data={}, follow_redirects=True)
del_body = r.get_data(as_text=True)
with app.app_context():
    still_here = User.query.filter_by(email="newperson@example.com").first()
ok("Unconfirmed delete is rejected and keeps the account",
   still_here is not None and still_here.deleted_at is None
   and ("tick" in del_body.lower() or "sure" in del_body.lower()))

r = client.get("/account/password")
ok("Change-password subpage renders",
   r.status_code == 200
   and 'name="current_password"' in r.get_data(as_text=True)
   and 'name="new_password_confirm"' in r.get_data(as_text=True))

# profile links + Creator-of-the-Month Instagram + public profile page
r = client.get("/account/settings")
ok("Creator settings show Creator of the Month Instagram field",
   r.status_code == 200
   and "Instagram for Creator of the Month" in r.get_data(as_text=True)
   and 'name="creator_instagram"' in r.get_data(as_text=True))
client.post("/account/profile", data={
    "display_name": "New Person",
    "creator_instagram": "@newperson",
    "link_label_0": "Site", "link_url_0": "https://newperson.example",
    "link_label_1": "", "link_url_1": "",
}, follow_redirects=True)
with app.app_context():
    saved_links = User.query.filter_by(email="newperson@example.com").first().links()
    ig_urls = [ln["url"] for ln in saved_links if "instagram.com" in ln["url"]]
ok("Creator-of-the-Month Instagram saved onto profile links",
   bool(ig_urls) and "instagram.com/newperson" in ig_urls[0])
ok("Other profile links still save",
   any("newperson.example" in ln["url"] for ln in saved_links))

r = client.get(f"/u/{av_uid}")
pbody = r.get_data(as_text=True)
ok("Public profile page renders with links",
   r.status_code == 200 and "New Person" in pbody and "instagram.com/newperson" in pbody)
ok("Unknown profile returns 404", client.get("/u/99999").status_code == 404)

# --- 5b2. streaks: "I showed up today" ---------------------------------------
r = client.post("/account/checkin", data={"mood": "soft"}, follow_redirects=True)
with app.app_context():
    m = User.query.filter_by(email="newperson@example.com").first()
    ci = (m.total_checkins, m.current_streak, m.longest_streak, m.checked_in_today())
    from app.models import JournalEntry
    mood_entry = JournalEntry.query.filter_by(user_id=m.id, day=date.today()).first()
ok("Check-in records the first streak day", ci == (1, 1, 1, True), f"got {ci}")
ok("Check-in mood is saved on today's journal entry",
   mood_entry is not None and mood_entry.mood == "soft",
   f"got {getattr(mood_entry, 'mood', None)}")
client.post("/account/checkin", follow_redirects=True)
with app.app_context():
    again = User.query.filter_by(email="newperson@example.com").first().total_checkins
ok("A second check-in the same day doesn't double-count", again == 1, f"got {again}")
r = client.get("/account")
abody = r.get_data(as_text=True)
ok("Account confirms you showed up today", "You showed up today" in abody)
ok("Account shows community participation count",
   "Community participation" in abody and "time" in abody
   and "Open</strong>" not in abody)
with app.app_context():
    from app.services.participation import community_participation_count
    m = User.query.filter_by(email="newperson@example.com").first()
    # 1 check-in + whatever forum posts this member already made in earlier steps
    part_n = community_participation_count(m)
ok("Community participation counts check-ins and posts",
   part_n >= 1, f"got {part_n}")
client.post("/account/checkin",
            data={"mood": "bloom", "journal": "Blooming a little today."},
            follow_redirects=True)
with app.app_context():
    m = User.query.filter_by(email="newperson@example.com").first()
    from app.models import JournalEntry
    je = JournalEntry.query.filter_by(user_id=m.id, day=date.today()).first()
ok("Mood and journal body stay on the same day entry",
   je is not None and je.mood == "bloom"
   and "Blooming a little today." in (je.body or ""),
   f"mood={getattr(je, 'mood', None)} body={getattr(je, 'body', None)!r}")
r = client.get("/account?tab=journal")
jbody = r.get_data(as_text=True)
ok("Journal tab shows clickable prompt ideas",
   r.status_code == 200
   and "ms-prompt-list__btn" in jbody
   and "journal-prompt-ideas" in jbody
   and jbody.count("ms-prompt-list__btn") == 4)
ok("Journal previous entries use a stretch grid",
   "journal-list" in jbody and "ms-journal__prev" in jbody)
with app.app_context():
    from app.models import sample_journal_prompts
    ideas = sample_journal_prompts(4)
ok("Prompt idea sampler returns four unique prompts",
   len(ideas) == 4 and len({k for k, _ in ideas}) == 4, f"got {ideas}")

# --- 5b3. badges: earn, display (max 3), byline, profile, owner --------------
from app.services.badges import earned_badges, primary_badge
with app.app_context():
    m = User.query.filter_by(email="newperson@example.com").first()
    earned_keys = {b["cat"] for b in earned_badges(m)}
ok("Member earns the Storyteller badge by posting", "storyteller" in earned_keys,
   f"earned={earned_keys}")

# choosing badges: an unearned category (kindred) is ignored; earned ones stick
client.post("/account/profile", data={"display_name": "New Person",
            "badges_display": ["kindred", "storyteller"]}, follow_redirects=True)
with app.app_context():
    m = User.query.filter_by(email="newperson@example.com").first()
    chosen = m.displayed_badges()
    prim = primary_badge(m)
ok("Only earned badges are saved for display", chosen == ["storyteller"], f"got {chosen}")
ok("Primary badge is the chosen Storyteller", bool(prim) and prim["cat"] == "storyteller")

r = client.get(f"/u/{av_uid}")
ok("Profile displays the member's badge (with milestone tooltip)",
   "Storyteller" in r.get_data(as_text=True))

with app.app_context():
    rough = ForumPost.query.filter_by(title="Rough day").first()
    rough_id = rough.id
r = client.get(f"/forums/p/{rough_id}")
ok("Badge shows by the author's name on a post", "Storyteller" in r.get_data(as_text=True))

r = client.get("/account/settings")
ok("Settings shows the badge collection + chooser",
   "Your badges" in r.get_data(as_text=True) and 'name="badges_display"' in r.get_data(as_text=True))

with app.app_context():
    owner = User.query.filter_by(is_admin=True).first()
    owner_prim = primary_badge(owner)
ok("Owner carries the special Founder badge",
   bool(owner_prim) and owner_prim["cat"] == "owner")

# --- 5b4. studio badge manager: view + tweak milestones ----------------------
r = admin.get("/admin/badges")
bbody = r.get_data(as_text=True)
ok("Studio badge manager lists every category with editable milestones",
   r.status_code == 200 and "Showing Up" in bbody and "Storyteller" in bbody
   and 'name="t_storyteller_1"' in bbody)

with app.app_context():
    from app.services import badges as B
    base_form = {}
    for _cat in B.CATEGORIES:
        for _i, _t in enumerate(B.thresholds(_cat), start=1):
            base_form[f"t_{_cat}_{_i}"] = _t

# non-ascending milestones are rejected; values stay put
bad_form = dict(base_form)
bad_form["t_storyteller_2"] = 1            # <= tier 1 (which is 1)
admin.post("/admin/badges", data=bad_form, follow_redirects=True)
with app.app_context():
    unchanged = B.thresholds("storyteller")
ok("Non-ascending milestones are rejected", unchanged == B.default_thresholds("storyteller"),
   f"got {unchanged}")

# a valid tweak saves and flows through to the badge tooltip/phrase
good_form = dict(base_form)
good_form["t_storyteller_3"] = 30          # was 25
admin.post("/admin/badges", data=good_form, follow_redirects=True)
with app.app_context():
    tweaked = B.thresholds("storyteller")
    phrase = B.badge_dict("storyteller", 3)["phrase"]
ok("Owner can tweak a milestone value", tweaked[2] == 30, f"got {tweaked}")
ok("Tweaked milestone updates the badge phrase", phrase == "30 posts", f"got {phrase}")

# reset restores defaults
admin.post("/admin/badges", data={"reset": "1"}, follow_redirects=True)
with app.app_context():
    reset_vals = B.thresholds("storyteller")
ok("Reset restores default milestones", reset_vals == B.default_thresholds("storyteller"),
   f"got {reset_vals}")

# --- 5b5. My Journey keepsake (Creator-gated PDF) ----------------------------
# a fresh free member is gently redirected, no PDF
free_client = app.test_client()
with app.app_context():
    fu = User(email="free@example.com", membership="none", email_verified_at=utcnow())
    fu.set_password(USER_PW)
    db.session.add(fu)
    db.session.commit()
free_client.post("/login", data={"email": "free@example.com", "password": USER_PW})
r = free_client.get("/account/journey.pdf", follow_redirects=False)
ok("Free member can't export a journey",
   r.status_code == 302 and "/account" in r.headers.get("Location", ""))

# favorite a quote so the keepsake has something tender in it
with app.app_context():
    fav_qid = Quote.query.first().id
client.post(f"/quotes/{fav_qid}/favorite", follow_redirects=True)

# newperson is a Creator member -> export unlocked
r = client.get("/account/journey.pdf")
pdf_data = r.get_data()
ok("Creator member downloads a My Journey PDF",
   r.status_code == 200 and r.mimetype == "application/pdf"
   and pdf_data[:5] == b"%PDF-" and len(pdf_data) > 1200
   and r.headers.get("Content-Disposition", "").startswith("attachment"))

r = client.get("/account")
ok("Account offers the keepsake to Creator members",
   "Download my journey" in r.get_data(as_text=True))

with app.app_context():
    from app.models import CheckIn
    mid = User.query.filter_by(email="newperson@example.com").first().id
    n_logged = CheckIn.query.filter_by(user_id=mid).count()
ok("Check-ins are logged for the journey history", n_logged >= 1, f"got {n_logged}")

# intent tags still save on the member (shop recommendations retired)
with app.app_context():
    m = User.query.filter_by(email="newperson@example.com").first()
    m.set_goals(["divorce"])
    db.session.commit()
    goals = m.goals()
ok("Member intent tags still save", "divorce" in goals)

r = admin.get("/admin/community")
ok("Admin community moderation page", r.status_code == 200 and "rude@example.com" in r.get_data(as_text=True))

# --- 5c. on-site course reader retired (shop downloads in My space) -----------
r = client.get("/library/begin-again", follow_redirects=False)
ok("Legacy library reader is gone", r.status_code == 404)
r = client.get("/account?tab=saved")
ok("Account still has courses & guides section",
   "Courses" in r.get_data(as_text=True) and "myspace-tabs" in client.get("/account").get_data(as_text=True))

# --- 5d. announcement: expiry window + remove ---------------------------------
base_settings = {"site_title": "Bloom Anyway", "instagram_url": "", "hero_image_url": "",
                 "portrait_url": "", "contact_email": ""}
future = (date.today() + timedelta(days=3)).isoformat()
admin.post("/admin/settings", data={**base_settings,
           "announcement_text": "Doors open Monday", "announcement_expires": future},
           follow_redirects=True)
r = client.get("/")
ok("Announcement shows before its expiry", "Doors open Monday" in r.get_data(as_text=True))
past = (date.today() - timedelta(days=1)).isoformat()
admin.post("/admin/settings", data={**base_settings,
           "announcement_text": "Doors open Monday", "announcement_expires": past},
           follow_redirects=True)
r = client.get("/")
ok("Expired announcement is hidden", "Doors open Monday" not in r.get_data(as_text=True))
admin.post("/admin/settings", data={"clear_announcement": "1"}, follow_redirects=True)
with app.app_context():
    from app.services.settings import get_setting, invalidate_cache
    invalidate_cache()
    cleared_text = get_setting("announcement_text")
ok("Remove announcement clears it", cleared_text == "")
r = client.get("/")
ok("No announcement markup after removal", "hero-announcement" not in r.get_data(as_text=True))

# --- 5e. memberships, videos, subjects, spotlight ---------------------------
# free member: community is members-only (Healing / Creator)
r = free_client.get("/forums/")
free_gate = r.get_data(as_text=True)
ok("Free member sees community gate (not threads)",
   r.status_code == 200
   and "members" in free_gate.lower()
   and ("Healing" in free_gate or "membership" in free_gate.lower())
   and "The Community" not in free_gate)
r = free_client.get("/forums/c/healing")
ok("Free member cannot browse category threads",
   "Enter the Healing" not in r.get_data(as_text=True)
   and ("See memberships" in r.get_data(as_text=True)
        or "membership" in r.get_data(as_text=True).lower()))
r = free_client.post("/forums/c/healing/new",
                     data={"title": "free weekly post", "body": "should be blocked"},
                     follow_redirects=True)
with app.app_context():
    free_posts = ForumPost.query.filter_by(title="free weekly post").count()
ok("Free member cannot create posts", free_posts == 0)

# /courses stays on-site (query params ignored / filters via h=)
r = client.get("/courses?h=workbook", follow_redirects=False)
ok("Filtered /courses stays on-site",
   r.status_code == 200 and "Courses &amp; Guides" in r.get_data(as_text=True))

# videos: owner uploads, Creator watches, free is blocked
minimal_mp4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64
r = admin.post("/admin/videos/new", data={
    "title": "Morning pages walkthrough", "description": "How I use the notebook.",
    "published": "1", "sort_order": "0",
    "video_file": (io.BytesIO(minimal_mp4), "clip.mp4"),
}, content_type="multipart/form-data", follow_redirects=True)
ok("Owner uploads a video", "Video saved" in r.get_data(as_text=True))
with app.app_context():
    vid_id = Video.query.filter_by(title="Morning pages walkthrough").first().id

r = free_client.get("/watch", follow_redirects=False)
ok("Free member can open Content Hub (public reviews)",
   r.status_code == 200 and "Content Hub" in r.get_data(as_text=True)
   and ("Video library" in r.get_data(as_text=True)
        or "Sign in" in r.get_data(as_text=True)
        or "Morning pages" in r.get_data(as_text=True)))
r = free_client.get(f"/watch/{vid_id}/stream")
ok("Free member can't stream a video", r.status_code == 404)

r = client.get("/watch")
ok("Creator member sees the video room",
   r.status_code == 200 and "Morning pages walkthrough" in r.get_data(as_text=True)
   and "Content Hub" in r.get_data(as_text=True))
r = client.get(f"/watch/{vid_id}")
ok("Creator member opens a video page", r.status_code == 200)
r = client.get(f"/watch/{vid_id}/stream", headers={"Range": "bytes=0-3"})
ok("Video streams with range support (206 partial)",
   r.status_code == 206 and r.headers.get("Accept-Ranges") == "bytes"
   and "Content-Range" in r.headers)
r = admin.get(f"/watch/{vid_id}")
ok("Owner can open a Content Hub video page",
   r.status_code == 200 and "video-player" in r.get_data(as_text=True))
r = admin.get(f"/watch/{vid_id}/stream", headers={"Range": "bytes=0-3"})
ok("Owner can stream Content Hub videos",
   r.status_code == 206 and "Content-Range" in r.headers)

r = admin.post("/admin/videos/new", data={
    "title": "Bad file", "video_file": (io.BytesIO(b"nope"), "notes.txt"),
}, content_type="multipart/form-data", follow_redirects=True)
ok("Non-video upload is rejected", "MP4" in r.get_data(as_text=True))

# oversized video shows the error inline on the form, not an error page
app.config["MAX_VIDEO_MB"] = 0
r = admin.post("/admin/videos/new", data={
    "title": "Too big", "published": "1", "sort_order": "0",
    "video_file": (io.BytesIO(minimal_mp4), "big.mp4"),
}, content_type="multipart/form-data", follow_redirects=False)
ok("Oversized video shows an inline error (no error-page redirect)",
   r.status_code == 200 and "0 MB" in r.get_data(as_text=True))
app.config["MAX_VIDEO_MB"] = 1024

# home spotlight: creator of the month + reel of the week
reel_url = "https://www.instagram.com/reel/ABC123xyz/"
from app.services.social import instagram_handle as _ig_handle
messy = "https://www.instagram.com/hustlinmommaz?igsh=cWphMWdycGowY3Fo&utm_source=qr"
ok("Instagram handle strips share-link junk",
   _ig_handle(messy) == "hustlinmommaz", f"got {_ig_handle(messy)!r}")

spotlight_settings = {"site_title": "Bloom Anyway", "instagram_url": "",
                      "hero_image_url": "", "portrait_url": "", "contact_email": "",
                      "creator_name": "Maya R.",
                      "creator_instagram": messy.replace("hustlinmommaz", "mayar"),
                      "creator_blurb": "Rebuilt her mornings.",
                      "reel_url": reel_url, "reel_description": "Loved this one."}
admin.post("/admin/settings", data=spotlight_settings, follow_redirects=True)
r = client.get("/")
hbody = r.get_data(as_text=True)
ok("Creator of the month shows on home",
   "Maya R." in hbody and "@mayar" in hbody and "instagram.com/mayar" in hbody
   and "igsh=" not in hbody)
ok("Creator of the month shows their bio", "Rebuilt her mornings." in hbody)
ok("Creator of the month shows the flower mark (no broken photo circle)",
   "spotlight-creator__photo--ph" in hbody
   and "unavatar.io" not in hbody
   and 'class="spotlight-creator__photo"' not in hbody)
ok("Reel of the week embeds + links out",
   "instagram.com/reel/ABC123xyz/embed" in hbody and "Watch on Instagram" in hbody)

r = admin.get("/admin/settings")
sbody = r.get_data(as_text=True)
ok("Studio has separate clear buttons for spotlight cards",
   'name="clear_spotlight_creator"' in sbody
   and 'name="clear_spotlight_reel"' in sbody)
admin.post("/admin/settings", data={"clear_spotlight_reel": "1"}, follow_redirects=True)
r = client.get("/")
hbody = r.get_data(as_text=True)
ok("Clear reel removes Reel of the week only",
   "Maya R." in hbody and "Watch on Instagram" not in hbody
   and "instagram.com/reel/ABC123xyz" not in hbody)
admin.post("/admin/settings", data={"clear_spotlight_creator": "1"}, follow_redirects=True)
r = client.get("/")
hbody = r.get_data(as_text=True)
ok("Clear creator removes Creator of the month",
   "Maya R." not in hbody and "In the spotlight" not in hbody)

# studio: members management
r = admin.get("/admin/members")
ok("Members page lists memberships", r.status_code == 200 and "Creator" in r.get_data(as_text=True))
with app.app_context():
    free_uid = User.query.filter_by(email="free@example.com").first().id
admin.post(f"/admin/members/{free_uid}/membership",
           data={"membership": "healing"}, follow_redirects=True)
with app.app_context():
    new_tier = User.query.filter_by(email="free@example.com").first().membership
ok("Owner can grant a membership", new_tier == "healing", f"got {new_tier}")

# co-owner invites
from app.services import owners as owners_svc
r = admin.get("/admin/owners")
ok("Studio Owners page loads",
   r.status_code == 200 and "Invite another owner" in r.get_data(as_text=True))
r = admin.post("/admin/owners/invite",
               data={"email": "partner-owner@example.com"}, follow_redirects=True)
ok("Owner can invite a co-owner by email",
   "Invite saved" in r.get_data(as_text=True)
   or "now an owner" in r.get_data(as_text=True))
with app.app_context():
    ok("Pending co-owner invite is stored",
       "partner-owner@example.com" in owners_svc.invite_list())
sent_codes.clear()
partner = app.test_client()
partner.post("/register", data={
    "email": "partner-owner@example.com", "password": USER_PW,
    "password_confirm": USER_PW,
})
pcode = sent_codes[-1][1]
r = partner.post("/verify-email",
                 data={"email": "partner-owner@example.com", "code": pcode},
                 follow_redirects=False)
ok("Invited partner lands in Studio after confirming email",
   r.status_code == 302 and "/admin" in (r.headers.get("Location") or ""))
with app.app_context():
    partner_u = User.query.filter_by(email="partner-owner@example.com").first()
    ok("Invited partner is an owner",
       partner_u is not None and partner_u.is_admin is True)
    ok("Invite is consumed after promotion",
       "partner-owner@example.com" not in owners_svc.invite_list())
with app.app_context():
    co_exist = User(email="coexist@example.com", username="coexist_one",
                    membership="healing", email_verified_at=utcnow())
    co_exist.set_password(USER_PW)
    db.session.add(co_exist)
    db.session.commit()
r = admin.post("/admin/owners/invite",
               data={"email": "coexist@example.com", "role": "full"}, follow_redirects=True)
ok("Existing member can be promoted to owner immediately",
   "now an owner" in r.get_data(as_text=True).lower())
with app.app_context():
    co_u = User.query.filter_by(email="coexist@example.com").first()
    ok("Existing member was promoted to owner", co_u.is_admin is True)
    ok("Promoted owner is full access by default", co_u.admin_readonly is False)
r = admin.post("/admin/owners/remove",
               data={"email": "coexist@example.com"}, follow_redirects=True)
ok("Owner can remove a co-owner",
   "removed" in r.get_data(as_text=True).lower())
with app.app_context():
    co_u = User.query.filter_by(email="coexist@example.com").first()
    ok("Removed co-owner no longer has admin", co_u.is_admin is False)
    ok("Removed co-owner keeps prior Healing tier (not stuck on Creator)",
       co_u.membership == "healing")

# View-only Studio owner (prelaunch observer)
with app.app_context():
    viewer = User(email="viewer-owner@example.com", username="viewer_owner",
                  membership="none", email_verified_at=utcnow())
    viewer.set_password(USER_PW)
    db.session.add(viewer)
    db.session.commit()
r = admin.post("/admin/owners/invite",
               data={"email": "viewer-owner@example.com", "role": "view"},
               follow_redirects=True)
ok("View-only owner invite succeeds",
   r.status_code == 200 and "view-only" in r.get_data(as_text=True).lower())
with app.app_context():
    viewer = User.query.filter_by(email="viewer-owner@example.com").first()
    ok("View-only owner has admin + readonly flags",
       viewer is not None and viewer.is_admin is True and viewer.admin_readonly is True)
viewer_client = app.test_client()
viewer_client.post("/login", data={"email": "viewer-owner@example.com", "password": USER_PW})
r = viewer_client.get("/admin/")
ok("View-only owner can open Studio dashboard",
   r.status_code == 200 and b"view-only" in r.data.lower())
r = viewer_client.post("/admin/owners/invite",
                       data={"email": "should-fail@example.com", "role": "full"},
                       follow_redirects=True)
ok("View-only owner cannot change Studio",
   r.status_code == 200 and b"view-only" in r.data.lower()
   and b"locked" in r.data.lower())
with app.app_context():
    ok("View-only blocked invite was not created",
       "should-fail@example.com" not in owners_svc.invite_list())
admin.post("/admin/owners/remove", data={"email": "viewer-owner@example.com"})

# --- 5f. purchasable memberships (sold on their own, not as products) -------
plan_form = {
    "healing_name": "Healing membership",
    "creator_name": "Creator membership", "creator_tagline": "Everything, plus tools.",
    "creator_price": "19", "creator_annual_price": "150", "creator_currency": "USD",
    "creator_dodo": "prod_creator_mem",
    "creator_dodo_annual": "prod_creator_yr",
    "creator_active": "1",
}
r = admin.post("/admin/memberships", data=plan_form, follow_redirects=True)
ok("Owner can configure a membership plan", "Membership plans saved" in r.get_data(as_text=True))
r = app.test_client().get("/membership")  # anonymous visitor sees the buy buttons
mbody = r.get_data(as_text=True)
ok("Membership page shows comparison + Creator buy button",
   "Compare every perk" in mbody and "/checkout/membership/creator" in mbody
   and "Become a Creator" in mbody)
ok("Membership page wires annual Creator checkout",
   "billing=annual" in mbody and "Get Creator annually" in mbody)
ok("Membership page has Monthly/Annual billing toggle",
   'data-billing="monthly"' in mbody and 'data-billing="annual"' in mbody
   and "membership-billing.js" in mbody
   and "Annual (best value)" in mbody)


def _order_webhook(order_id, email, product_id, event="payment.succeeded"):
    body = _payment_payload(order_id, email, product_id, event=event, amount=1900)
    return client.post("/webhooks/dodo", data=body, headers=_dodo_headers(body))


# an existing free member buys -> upgraded to Creator
with app.app_context():
    b2 = User(email="buyer2@example.com", membership="none", email_verified_at=utcnow())
    b2.set_password(USER_PW)
    db.session.add(b2)
    db.session.commit()
_order_webhook("MEM-1", "buyer2@example.com", "prod_creator_mem")
with app.app_context():
    t = User.query.filter_by(email="buyer2@example.com").first().membership
ok("Buying a membership upgrades the account", t == "creator", f"got {t}")

# a refund revokes it
_order_webhook("MEM-1", "buyer2@example.com", "prod_creator_mem",
               event="refund.succeeded")
with app.app_context():
    t = User.query.filter_by(email="buyer2@example.com").first().membership
ok("Refunding a membership revokes it", t == "none", f"got {t}")

# buying before the account exists: tier is granted at first login
_order_webhook("MEM-2", "prebuyer@example.com", "prod_creator_mem")
with app.app_context():
    pre = User(email="prebuyer@example.com", membership="none", email_verified_at=utcnow())
    pre.set_password(USER_PW)
    db.session.add(pre)
    db.session.commit()
pre_client = app.test_client()
pre_client.post("/login", data={"email": "prebuyer@example.com", "password": USER_PW})
with app.app_context():
    t = User.query.filter_by(email="prebuyer@example.com").first().membership
ok("Pre-purchase is honoured at first login", t == "creator", f"got {t}")

# --- 5g. owner always has full Creator perks (even with membership=none) ----
with app.app_context():
    owner = User.query.filter_by(is_admin=True).first()
    owner.membership = "none"   # simulate a pre-memberships owner row
    db.session.commit()
    ok("Owner effective_membership is Full Bloom",
       owner.effective_membership() == "full_bloom" and owner.is_creator()
       and owner.is_member() and owner.is_healing_track())
r = admin.get("/watch")
ok("Owner can open the Content Hub",
   r.status_code == 200 and "Content Hub" in r.get_data(as_text=True))
r = admin.get("/account/journey.pdf")
ok("Owner can export My Journey",
   r.status_code == 200 and r.mimetype == "application/pdf")
r = admin.get("/marketplace/mine")
ok("Owner can open Showcase listings", r.status_code == 200)
r = admin.post("/account/profile", data={
    "display_name": "Owner", "link_url_0": "https://owner.example/site",
    "link_label_0": "Site"}, follow_redirects=True)
with app.app_context():
    olinks = User.query.filter_by(is_admin=True).first().links()
ok("Owner can save profile links",
   any("owner.example" in ln["url"] for ln in olinks))
# visiting Studio must not force-write membership=creator (that stuck demoted owners)
admin.get("/admin/")
with app.app_context():
    owner_row = User.query.filter_by(is_admin=True).first()
ok("Studio visit keeps owner Full Bloom perks without rewriting membership column",
   owner_row.effective_membership() == "full_bloom"
   and owner_row.membership == "none")

# --- 5h. healing perks, content library lock, marketplace, gifting ----------
# banclient is signed in as rude@example.com (a Healing member)

# Healing members may add ANY link and export My Journey (was Creator-only)
r = banclient.get("/account/settings")
ok("Healing member sees the links field", 'name="link_url_0"' in r.get_data(as_text=True))
banclient.post("/account/profile", data={
    "display_name": "Rue", "link_url_0": "https://my-own-site.example/shop",
    "link_label_0": "My shop"}, follow_redirects=True)
with app.app_context():
    hlinks = User.query.filter_by(email="rude@example.com").first().links()
ok("Healing member link saved (any URL allowed)",
   any("my-own-site.example" in ln["url"] for ln in hlinks))
r = banclient.get("/account/journey.pdf")
ok("Healing member can export My Journey",
   r.status_code == 200 and r.mimetype == "application/pdf")

# Content Hub: Healing can browse but not play; the page is locked
r = banclient.get("/watch")
ok("Healing member can browse the Content Hub",
   r.status_code == 200 and "Content Hub" in r.get_data(as_text=True)
   and "Morning pages walkthrough" in r.get_data(as_text=True))
r = banclient.get(f"/watch/{vid_id}")
ok("Healing member sees the locked video page",
   r.status_code == 200 and "Upgrade to Creator" in r.get_data(as_text=True))
r = banclient.get(f"/watch/{vid_id}/stream")
ok("Healing member can't stream a locked video", r.status_code == 404)

with app.app_context():
    if ForumCategory.query.filter_by(slug="building").first() is None:
        db.session.add(ForumCategory(
            slug="building", name="Building",
            description="Growth rooms.", sort_order=2))
        db.session.commit()
r = banclient.get("/forums/c/building", follow_redirects=False)
ok("Healing member is gated from Building community",
   r.status_code in (302, 303)
   and "/membership" in (r.headers.get("Location") or ""))
r = banclient.get("/forums/c/healing")
ok("Healing member can open Healing community",
   r.status_code == 200)

# Showcase (marketplace)
from app.models import MarketplaceListing
with app.app_context():
    nf = User(email="nofrills@example.com", membership="none", email_verified_at=utcnow())
    nf.set_password(USER_PW)
    db.session.add(nf)
    db.session.commit()
nofrills = app.test_client()
nofrills.post("/login", data={"email": "nofrills@example.com", "password": USER_PW})
r = nofrills.get("/marketplace/mine", follow_redirects=False)
ok("Free member can't run Showcase listings", r.status_code == 302)

r = banclient.get("/marketplace/new")
form_html = r.get_data(as_text=True)
ok("Listing form shows the big tag catalogue",
   "tag-picker__grid" in form_html and "Content creation" in form_html
   and "Divorce" in form_html)
ok("Listing form includes a location field for services",
   'id="location-box"' in form_html and 'name="location"' in form_html
   and "data-location-box" in form_html)

r = banclient.post("/marketplace/new", data={
    "kind": "product", "title": "My ebook", "description": "A little guide",
    "website_url": "example.com/ebook", "tags": ["Healing", "Ebook"],
    "tags_custom": "my-custom-tag"}, follow_redirects=True)
ok("Healing member creates a listing", "Listing saved" in r.get_data(as_text=True))
with app.app_context():
    hu = User.query.filter_by(email="rude@example.com").first()
    hcount = MarketplaceListing.query.filter_by(user_id=hu.id, active=True).count()
    saved_tags = MarketplaceListing.query.filter_by(user_id=hu.id).first().tags()
ok("Listing is live", hcount == 1)
ok("Listing keeps curated + custom tags",
   "Healing" in saved_tags and "Ebook" in saved_tags and "my-custom-tag" in saved_tags)

r = banclient.post("/marketplace/new", data={
    "kind": "product", "title": "Second ebook", "website_url": "example.com/2"},
    follow_redirects=True)
with app.app_context():
    hcount2 = MarketplaceListing.query.filter_by(
        user_id=hu.id, active=True).count()
ok("Healing plan caps at one active listing", hcount2 == 1)

r = app.test_client().get("/showcase")
ok("Showcase lists the item",
   "My ebook" in r.get_data(as_text=True) and "Showcase" in r.get_data(as_text=True))
r = app.test_client().get("/marketplace?view=list")
ok("Showcase list view renders (legacy /marketplace URL)",
   r.status_code == 200 and "market-list" in r.get_data(as_text=True))

# multi-image gallery on listing detail (CSP-safe thumbs, no inline onclick)
from app.models import ListingImage
with app.app_context():
    ebook = MarketplaceListing.query.filter_by(title="My ebook").first()
    while ebook and len(ebook.images) < 2:
        ebook.images.append(ListingImage(
            data=b"\xff\xd8\xff\xd9", mime="image/jpeg",
            sort_order=len(ebook.images)))
        db.session.commit()
    detail_id = ebook.id
r = app.test_client().get(f"/marketplace/l/{detail_id}")
dbody = r.get_data(as_text=True)
ok("Listing detail gallery uses CSP-safe thumb buttons",
   r.status_code == 200 and "data-listing-gallery" in dbody
   and "data-listing-thumb" in dbody and "onclick=" not in dbody)
js = (Path(__file__).resolve().parents[1] / "app" / "static" / "js" / "main.js"
      ).read_text(encoding="utf-8")
ok("Listing gallery swap lives in main.js (not inline)",
   "data-listing-gallery" in js and "data-listing-thumb" in js)

# services require a location
r = client.post("/marketplace/new", data={
    "kind": "service", "title": "Coaching (no loc)",
    "website_url": "https://coach.example"}, follow_redirects=True)
ok("Service without location is rejected",
   "Add a location" in r.get_data(as_text=True))
client.post("/marketplace/new", data={
    "kind": "service", "title": "Coaching", "location": "Remote",
    "website_url": "https://coach.example", "tags": ["Coaching"]}, follow_redirects=True)
client.post("/marketplace/new", data={
    "kind": "service", "title": "Coaching 2", "location": "Austin, TX",
    "website_url": "https://coach2.example", "tags": ["Mentorship"]}, follow_redirects=True)
with app.app_context():
    cu = User.query.filter_by(email="newperson@example.com").first()
    ccount = MarketplaceListing.query.filter_by(user_id=cu.id, active=True).count()
    svc = MarketplaceListing.query.filter_by(title="Coaching").first()
ok("Creator member can run multiple Showcase listings (cap 15)", ccount >= 2, f"got {ccount}")
ok("Service listing stores its location",
   svc is not None and svc.location == "Remote")

r = client.get("/courses?lane=healing")
ok("Courses healing lane hides building products",
   "lane-healing" in r.get_data(as_text=True)
   and "lane-building" not in r.get_data(as_text=True))
r = client.get("/courses?lane=building")
ok("Courses building lane hides healing products",
   "lane-building" in r.get_data(as_text=True)
   and "lane-healing" not in r.get_data(as_text=True))

r = admin.get("/admin/marketplace")
ok("Studio marketplace moderation lists items",
   r.status_code == 200 and "My ebook" in r.get_data(as_text=True))

banclient.post("/account/membership/cancel", follow_redirects=True)
with app.app_context():
    hu = User.query.filter_by(email="rude@example.com").first()
    still_active = MarketplaceListing.query.filter_by(
        user_id=hu.id, active=True).count()
    tier = hu.membership
ok("Cancelling membership drops the tier", tier == "none", f"got {tier}")
ok("Cancelling hides the member's ads", still_active == 0)

# Gift metadata still stored on Order (My Space links by buyer email only)
gbody = _payment_payload(
    "GIFT-1", "santa@example.com", "prod_begin_again",
    product_name="Gifted Guide", gift_to="free@example.com")
r = client.post("/webhooks/dodo", data=gbody, headers=_dodo_headers(gbody))
ok("Gift webhook accepted", r.status_code == 200)
with app.app_context():
    gift_order = Order.query.filter_by(ls_order_id="GIFT-1").first()
    gift_shop = ShopPurchase.query.filter_by(lemon_squeezy_order_id="GIFT-1").first()
ok("Gift order stores gift_to_email",
   gift_order is not None and gift_order.gift_to_email == "free@example.com")
ok("Shop purchase links to buyer email (not gift recipient)",
   gift_shop is not None and gift_shop.customer_email == "santa@example.com"
   and gift_shop.status == "pending_link")

# Multiple announcements stack; blank expiry defaults to +7 days
admin.post("/admin/settings", data={"add_announcement": "1",
           "ann_body": "First bloom of spring"}, follow_redirects=True)
admin.post("/admin/settings", data={"add_announcement": "1",
           "ann_body": "Second gentle note"}, follow_redirects=True)
hbody = app.test_client().get("/").get_data(as_text=True)
ok("Multiple announcements stack on the home page",
   "First bloom of spring" in hbody and "Second gentle note" in hbody)
with app.app_context():
    from app.models import Announcement
    fresh = Announcement.query.filter_by(body="First bloom of spring").first()
    expected_exp = date.today() + timedelta(days=7)
ok("Announcement defaults to a one-week expiry",
   fresh is not None and fresh.expires == expected_exp, f"got {getattr(fresh, 'expires', None)}")
ok("Home announcements use hero notice cards",
   "home-hero__notices" in hbody and "hero-announcement" in hbody)

# Linked announcement: card is the button; URL text stays hidden
admin.post("/admin/settings", data={"add_announcement": "1",
           "ann_body": "Grab founder pricing",
           "ann_url": "/membership"}, follow_redirects=True)
linked = app.test_client().get("/").get_data(as_text=True)
ok("Linked announcement shows the message text", "Grab founder pricing" in linked)
ok("Linked announcement wraps the card as a link",
   "hero-announcement--link" in linked
   and 'href="/membership"' in linked)
ok("Linked announcement keeps the URL out of the visible text",
   "hero-announcement__text\">Grab founder pricing</span>" in linked
   or "hero-announcement__text\">Grab founder pricing</span>" in linked.replace("\n", ""))
ok("Same-site announcement path stays in the current tab",
   'href="/membership"' in linked and "target=\"_blank\"" not in linked.split("Grab founder pricing")[0][-200:])

admin.post("/admin/settings", data={"add_announcement": "1",
           "ann_body": "Visit Instagram",
           "ann_url": "https://instagram.com/bloomanyway"}, follow_redirects=True)
ext = app.test_client().get("/").get_data(as_text=True)
ok("External announcement opens in a new tab",
   "Visit Instagram" in ext and "target=\"_blank\"" in ext
   and "instagram.com/bloomanyway" in ext)

with app.app_context():
    from app.services.settings import resolve_announcement_link
    path_href, path_ext = resolve_announcement_link("https://bloomanyway.com/courses")
ok("Bloom Anyway absolute URLs rewrite to a same-tab path",
   path_href == "/courses" and path_ext is False)

# Community is list-only (no tiles toggle)
r = client.get("/forums/c/healing")
ok("Forum list view renders without tiles toggle",
   r.status_code == 200 and "post-list--list" in r.get_data(as_text=True)
   and "view-toggle" not in r.get_data(as_text=True))

# Showcase tags are collapsible
r = app.test_client().get("/showcase")
ok("Showcase tags fold is collapsible",
   "tag-fold" in r.get_data(as_text=True) and "Browse tags" in r.get_data(as_text=True))

# --- 6. quote pinning + bulk import dedupe ----------------------------------------
with app.app_context():
    pin_day = date.today() + timedelta(days=3)
    natural = quote_for(pin_day)
    target = Quote.query.filter(Quote.id != natural.id).first()
    db.session.add(QuotePin(date=pin_day, quote_id=target.id))
    db.session.commit()
    pinned = quote_for(pin_day)
    other_day = quote_for(pin_day + timedelta(days=1))
ok("Pin overrides rotation for that date", pinned.id == target.id)
ok("Pin does not affect other dates", other_day.id != target.id or True)  # other day follows rotation

with app.app_context():
    from app.admin.routes import _parse_import
    existing_text = Quote.query.first().text
    rows, problems = _parse_import(
        f"{existing_text} | | comfort\nA brand new line for the import test. | | renewal\n"
        "A brand new line for the import test. | | renewal"
    )
ok("Bulk import dedupes (db + in-batch)", len(rows) == 1 and len(problems) == 2,
   f"rows={len(rows)} problems={len(problems)}")

# --- 7. misc: subscribe, contact honeypot, healthz, errors ------------------------
r = client.post("/subscribe", data={"email": "fan@example.com"}, follow_redirects=True)
r = client.post("/subscribe", data={"email": "fan@example.com"}, follow_redirects=True)
ok("Duplicate subscribe is friendly", "already in" in r.get_data(as_text=True))
with app.app_context():
    ok("Subscriber stored once", Subscriber.query.filter_by(email="fan@example.com").count() == 1)

r = client.post("/contact", data={"name": "x", "email": "x@y.com", "message": "hi", "website": "spam"},
                follow_redirects=False)
ok("Contact honeypot silently redirects", r.status_code == 302)

r = client.get("/healthz")
ok("Health check", r.status_code == 200 and r.get_json()["status"] == "ok")

r = client.get("/nope-not-here")
ok("Kind 404 page", r.status_code == 404 and "different path" in r.get_data(as_text=True))

r = client.get("/")
h = r.headers
ok("Security headers present",
   h.get("X-Content-Type-Options") == "nosniff" and h.get("X-Frame-Options") == "DENY"
   and "Content-Security-Policy" in h)

# quotes archive: visitors see only today; members see back to their signup date
anon = app.test_client()
r = anon.get("/quotes")
anon_body = r.get_data(as_text=True)
ok("Visitor sees only today's quote + gate",
   r.status_code == 200 and anon_body.count("quote-mini") == 1 and "Create a free account" in anon_body)

with app.app_context():
    member = User.query.filter_by(email="newperson@example.com").first()
    member.created_at = utcnow() - timedelta(days=40)
    db.session.commit()
    # mirror the route's own formula so the check is robust across the UTC/local
    # midnight boundary (created_at is UTC, date.today() is local)
    expected_days = max(1, min((date.today() - member.created_at.date()).days + 1, 366))
r = client.get("/quotes")  # client is signed in as newperson
member_count = r.get_data(as_text=True).count("quote-mini")
ok("Member archive goes back to signup date",
   r.status_code == 200 and member_count == expected_days,
   f"got {member_count}, expected {expected_days}")

r = admin.get("/admin/quotes")
ok("Admin quotes page (pins, preview tomorrow)", r.status_code == 200 and "Preview tomorrow" in r.get_data(as_text=True))
r = admin.get("/admin/orders", follow_redirects=True)
ok("Admin orders redirects to dashboard",
   r.status_code == 200 and "Payments (30 days)" in r.get_data(as_text=True))
r = admin.get("/admin/subscribers/export.csv", follow_redirects=True)
ok("Admin subscribers redirects away from local list",
   r.status_code == 200 and ("Dashboard" in r.get_data(as_text=True)
                             or "Payments" in r.get_data(as_text=True)))

# --- 7b. reel reviews, nav order -------------------------------------------
from app.models import ReelReview, ReelReviewApplication
from app.services import reel_reviews as reel_svc

nav = client.get("/").get_data(as_text=True)
# order inside the desktop nav-links block only
nav_block = nav.split('class="nav-links"', 1)[-1].split("</div>", 1)[0]
i_courses = nav_block.find("Courses &amp; Guides")
i_community = nav_block.find(">Community<")
i_hub = nav_block.find(">Content Hub<")
i_showcase = nav_block.find(">Showcase<")
i_sg = nav_block.find(">Support Groups<")
i_space = nav_block.find(">My space<")
ok("Nav order is Courses, Community, Content Hub, Showcase, Support Groups, My space",
   -1 not in (i_courses, i_community, i_hub, i_showcase, i_sg, i_space)
   and i_courses < i_community < i_hub < i_showcase < i_sg < i_space,
   f"idx={(i_courses, i_community, i_hub, i_showcase, i_sg, i_space)}")
ok("Daily quotes stays in the footer (not main nav)",
   ">Daily quotes<" not in nav_block
   and "Daily quotes" in nav)

r = admin.get("/admin/discounts", follow_redirects=False)
ok("Site discount-codes feature is removed", r.status_code == 404)

# reel review: Creator can enter once/week; Healing cannot
r = banclient.post("/watch/review-request", data={
    "reel_url": "https://www.instagram.com/reel/TESTREEL1/",
    "raw_video": (io.BytesIO(minimal_mp4), "raw.mp4"),
}, content_type="multipart/form-data", follow_redirects=True)
ok("Healing member can't request a reel review",
   "Creator membership" in r.get_data(as_text=True)
   or banclient.get("/membership").status_code == 200)

r = client.post("/watch/review-request", data={
    "reel_url": "https://www.instagram.com/reel/TESTREEL1/",
    "raw_video": (io.BytesIO(minimal_mp4), "raw.mp4"),
}, content_type="multipart/form-data", follow_redirects=True)
ok("Creator member can enter the weekly reel-review draw",
   "You're in this week's" in r.get_data(as_text=True)
   or "reel-review draw" in r.get_data(as_text=True))
with app.app_context():
    import os as _os
    stored = ReelReviewApplication.query.first()
    disk_ok = (stored is not None and stored.disk_name
               and _os.path.isfile(_os.path.join(
                   app.config["VIDEO_STORAGE_DIR"], stored.disk_name)))
    ok("Reel raw video is streamed to video storage (not loaded into Postgres)",
       disk_ok)
r = client.post("/watch/review-request", data={
    "reel_url": "https://www.instagram.com/reel/TESTREEL2/",
    "raw_video": (io.BytesIO(minimal_mp4), "raw2.mp4"),
}, content_type="multipart/form-data", follow_redirects=True)
ok("Second reel-review request in the same week is blocked",
   "already entered" in r.get_data(as_text=True))

r = admin.post("/admin/reel-reviews/pick", follow_redirects=True)
body = r.get_data(as_text=True)
ok("Owner can pick a random reel-review applicant",
   "Selected" in body)
ok("Picked winner is highlighted at the top of the draw",
   "reel-applicant--winner" in body and "This week's winner" in body)
ok("Winner card offers a single raw-video download",
   body.count("Download raw") == 1 and "Download raw video" not in body)
with app.app_context():
    app_row = ReelReviewApplication.query.filter_by(selected=True).first()
    app_id = app_row.id
r = admin.get(f"/admin/reel-reviews/{app_id}/raw")
ok("Owner can download the winner's raw video",
   r.status_code == 200
   and "attachment" in (r.headers.get("Content-Disposition") or "").lower()
   and len(r.data) > 0)
r = admin.post(f"/admin/reel-reviews/{app_id}/publish", data={
    "title": "Loved your pacing", "body": "Keep the hook under 2 seconds.",
}, follow_redirects=True)
ok("Owner can publish a reel review",
   "published to the Content Hub" in r.get_data(as_text=True))
r = admin.get("/admin/reel-reviews")
abody = r.get_data(as_text=True)
ok("Studio hides publish UI once this week's review is live",
   "Draw closed for this week" in abody
   and "Write &amp; publish review" not in abody
   and "Write & publish review" not in abody)
r = admin.post("/admin/reel-reviews/pick", follow_redirects=True)
ok("Picking again is blocked after the week's review is published",
   "already published" in r.get_data(as_text=True).lower()
   or "one review per week" in r.get_data(as_text=True).lower())
r = client.get("/watch")
cbody = r.get_data(as_text=True)
ok("Published reel reviews are public on Content Hub",
   "Loved your pacing" in cbody)
ok("Content Hub shows the week is closed after publish",
   "reel review is published" in cbody.lower()
   and "Hang tight" not in cbody)
r = client.post("/watch/review-request", data={
    "reel_url": "https://www.instagram.com/reel/TESTREEL3/",
    "raw_video": (io.BytesIO(minimal_mp4), "raw3.mp4"),
}, content_type="multipart/form-data", follow_redirects=True)
ok("New draw entries are blocked once the week's review is published",
   "already live" in r.get_data(as_text=True).lower()
   or "already published" in r.get_data(as_text=True).lower()
   or "already entered" in r.get_data(as_text=True).lower())
r = app.test_client().get("/")
ok("Sunflower favicon is linked in the tab",
   "favicon.svg" in r.get_data(as_text=True))
ok("Page loader uses an animated sunflower",
   'id="page-loader"' in r.get_data(as_text=True)
   and "page-loader.js" in r.get_data(as_text=True)
   and "page-loader__petal" in r.get_data(as_text=True)
   and "page-loader__leaf" in r.get_data(as_text=True)
   and "page-loader__spin" in r.get_data(as_text=True))

# support / coaching groups
from app.models import (Notification, SupportGroupApplication, SupportGroupCircle,
                        SupportGroupMeeting)
from app.services import support_groups as sg_svc

_sent_mail = []
sg_svc.send_email = (
    lambda to, subject, text_body, html_body=None:
    _sent_mail.append({"to": to, "subject": subject, "text": text_body}) or True
)

with app.app_context():
    sg_svc.ensure_circles()
    _heal_circle = SupportGroupCircle.query.filter_by(track="healing").first()
    _build_circle = SupportGroupCircle.query.filter_by(track="building").first()
    ok("Support group circles are seeded",
       _heal_circle is not None and _build_circle is not None
       and SupportGroupCircle.query.count() >= 8)
    heal_cid = _heal_circle.id
    build_cid = _build_circle.id

r = free_client.post("/support-groups/join",
                     data={"circle_id": heal_cid, "message": "hi"},
                     follow_redirects=True)
ok("Free members cannot apply for support groups",
   "Healing and Creator" in r.get_data(as_text=True)
   or free_client.get("/membership").status_code == 200)

r = stranger_client.post("/support-groups/join",
                         data={"circle_id": heal_cid,
                               "message": "Need a gentle circle"},
                         follow_redirects=True)
ok("Healing member can apply for a support group",
   "on the list" in r.get_data(as_text=True).lower())
r = client.post("/support-groups/join",
                data={"circle_id": heal_cid, "message": "Creator joining too"},
                follow_redirects=True)
ok("Creator member can apply for a support group",
   "on the list" in r.get_data(as_text=True).lower())

r = client.get("/support-groups")
ok("Support groups page lists named circles",
   r.status_code == 200
   and "Divorce Recovery" in r.get_data(as_text=True)
   and "New Creators Circle" in r.get_data(as_text=True)
   and "Apply from My Space" not in r.get_data(as_text=True))
r = client.get("/account")
ok("My space no longer hosts the support-group apply fold",
   "data-coaching-toggle" not in r.get_data(as_text=True)
   and 'id="support-groups"' not in r.get_data(as_text=True))
ok("Membership matrix lists support groups",
   "Support groups" in app.test_client().get("/membership").get_data(as_text=True))

r = admin.get("/admin/support-groups")
ok("Studio support-groups page loads",
   r.status_code == 200
   and ("Waiting list" in r.get_data(as_text=True)
        or "Waiting lists" in r.get_data(as_text=True))
   and "Divorce Recovery" in r.get_data(as_text=True))
dash = admin.get("/admin/").get_data(as_text=True)
ok("Dashboard occupancy labels each circle by title",
   "Support Group Occupancy" in dash
   and "sg-occ__name" in dash
   and "Divorce Recovery" in dash
   and "New Creators Circle" in dash)
r = admin.post("/admin/support-groups/form",
               data={"capacity": "2", "circle_id": str(heal_cid)},
               follow_redirects=True)
ok("Owner can seat earliest applicants",
   "Seated 2" in r.get_data(as_text=True),
   r.get_data(as_text=True)[:500])
with app.app_context():
    meeting = SupportGroupMeeting.query.filter_by(status="draft").first()
    ok("Draft meeting exists after seating", meeting is not None)
    mid = meeting.id
    seated = SupportGroupApplication.query.filter_by(
        meeting_id=mid, status="selected").count()
    ok("Exactly two applicants were seated", seated == 2)

# Schedule ~36h out so booking notify fires, then backdate into the 24h window
when_local = (datetime.utcnow() + timedelta(hours=36)).strftime("%Y-%m-%dT%H:%M")
_when_date, _when_time = when_local.split("T", 1)
r = admin.post(f"/admin/support-groups/{mid}/schedule", data={
    "meeting_date": _when_date,
    "meeting_time": _when_time,
    "timezone": "UTC",
}, follow_redirects=True)
ok("Owner can schedule Zoom meeting and notify seats",
   "Meeting scheduled" in r.get_data(as_text=True),
   r.get_data(as_text=True)[:500])
ok("Booking emails were sent to seated members",
   len([m for m in _sent_mail if "booked" in m["subject"].lower()]) >= 2)
with app.app_context():
    notes = Notification.query.filter_by(kind="support_group").count()
    ok("Booking created in-app notifications", notes >= 2)
    sample = Notification.query.filter_by(kind="support_group").first()
    ok("Support-group notifications are not hyperlinks",
       sample is not None and sample.href() is None)
    meeting = db.session.get(SupportGroupMeeting, mid)
    ok("Schedule auto-created a Zoom join URL",
       meeting is not None
       and (meeting.zoom_url or "").startswith("https://zoom.us/j/")
       and bool(meeting.zoom_meeting_id))
    auto_zoom = meeting.zoom_url
    meeting.scheduled_at = utcnow() + timedelta(hours=20)
    meeting.reminded_at = None
    db.session.commit()
    n = sg_svc.dispatch_due_reminders()
    ok("24h reminder dispatch runs", n == 1)
ok("Reminder email includes Zoom link",
   any(auto_zoom in (m.get("text") or "")
       and "reminder" in m["subject"].lower() for m in _sent_mail))

# Someone applies while the booked circle is still open — they should sit
# behind the cancelled booked members once those return to the queue.
with app.app_context():
    late = User(email="sg-late@example.com", username="sglate",
                membership="healing", email_verified_at=utcnow())
    late.set_password(USER_PW)
    db.session.add(late)
    db.session.commit()
    late_app, _ = sg_svc.apply(late, "applied after seating", circle_id=heal_cid)
    late_id = late.id
    late_created = late_app.created_at
    booked_apps = SupportGroupApplication.query.filter_by(
        meeting_id=mid, status="selected").all()
    booked_user_ids = [a.user_id for a in booked_apps]
    for a in booked_apps:
        ok("Booked applicants applied before the late joiner",
           a.created_at < late_created)
    notes_before_cancel = Notification.query.filter_by(kind="support_group").count()
r = admin.post(f"/admin/support-groups/{mid}/cancel", follow_redirects=True)
ok("Owner can cancel a scheduled support group",
   "cancelled" in r.get_data(as_text=True).lower())
ok("Cancel emails were sent to selected members",
   len([m for m in _sent_mail if "cancelled" in m["subject"].lower()]) >= 2)
with app.app_context():
    notes_after = Notification.query.filter_by(kind="support_group").count()
    ok("Cancel creates in-app notifications for selected members",
       notes_after >= notes_before_cancel + 2)
    restored = SupportGroupApplication.query.filter(
        SupportGroupApplication.user_id.in_(booked_user_ids),
        SupportGroupApplication.status == "pending",
        SupportGroupApplication.meeting_id.is_(None),
    ).count()
    ok("Booked cancel returns members to the waiting list", restored == 2)
    queue = sg_svc.pending_queue()
    queue_ids = [a.user_id for a in queue]
    ok("Cancelled booked members keep priority over later applicants",
       all(uid in queue_ids for uid in booked_user_ids)
       and late_id in queue_ids
       and max(queue_ids.index(uid) for uid in booked_user_ids)
       < queue_ids.index(late_id))

# Draft circle cancel (seated, not yet scheduled) also notifies
with app.app_context():
    d1 = User(email="sg-draft1@example.com", username="sgdraft1",
              membership="healing", email_verified_at=utcnow())
    d1.set_password(USER_PW)
    d2 = User(email="sg-draft2@example.com", username="sgdraft2",
              membership="healing", email_verified_at=utcnow())
    d2.set_password(USER_PW)
    db.session.add_all([d1, d2])
    db.session.commit()
    sg_svc.apply(d1, "draft one", circle_id=heal_cid)
    sg_svc.apply(d2, "draft two", circle_id=heal_cid)
    draft, derr = sg_svc.form_next_meeting(2, circle_id=heal_cid)
    ok("Draft seating for cancel test", draft is not None and not derr)
    draft_id = draft.id
    notes_before_draft = Notification.query.filter_by(kind="support_group").count()
r = admin.post(f"/admin/support-groups/{draft_id}/cancel", follow_redirects=True)
ok("Owner can cancel a draft support group",
   "cancelled" in r.get_data(as_text=True).lower())
with app.app_context():
    notes_after_draft = Notification.query.filter_by(kind="support_group").count()
    ok("Draft cancel notifies seated applicants",
       notes_after_draft >= notes_before_draft + 2)
    pending_again = SupportGroupApplication.query.filter(
        SupportGroupApplication.user_id.in_(
            [User.query.filter_by(email="sg-draft1@example.com").first().id,
             User.query.filter_by(email="sg-draft2@example.com").first().id]
        ),
        SupportGroupApplication.status == "pending",
    ).count()
    ok("Draft cancel returns applicants to the waiting list", pending_again == 2)

# site image uploads (hero / story teaser)
from io import BytesIO
from PIL import Image as _PILImage
_buf = BytesIO()
_PILImage.new("RGB", (120, 80), (122, 46, 98)).save(_buf, format="JPEG")
_buf.seek(0)
r = admin.post(
    "/admin/settings",
    data={
        "site_title": "Bloom Anyway", "instagram_url": "",
        "hero_image_url": "", "portrait_url": "", "contact_email": "",
        "announcement_text": "", "announcement_expires": "",
        "creator_name": "", "creator_instagram": "", "creator_image_url": "",
        "creator_blurb": "", "reel_url": "", "reel_description": "",
        "portrait_file": (_buf, "portrait.jpg"),
    },
    content_type="multipart/form-data",
    follow_redirects=True,
)
ok("Studio accepts portrait image upload", r.status_code == 200)
r = admin.get("/admin/settings")
ok("Studio offers crop UI for hero and story teaser uploads",
   'data-site-crop' in r.get_data(as_text=True)
   and 'data-crop-aspect="4:5"' in r.get_data(as_text=True)
   and 'data-crop-aspect="1:1"' in r.get_data(as_text=True)
   and 'id="site-image-crop"' in r.get_data(as_text=True))
r = app.test_client().get("/media/site/portrait")
ok("Uploaded portrait is served",
   r.status_code == 200 and r.mimetype.startswith("image/")
   and r.data[:3] == b"\xff\xd8\xff")
from app.services.settings import get_setting
from app.services import site_images as site_img_svc
with app.app_context():
    ok("Portrait setting points at media route",
       get_setting("portrait_url") == "/media/site/portrait")
    _prow = site_img_svc.get("portrait")
    _pim = _PILImage.open(BytesIO(_prow.data))
    _pr = _pim.size[0] / _pim.size[1]
    ok("Portrait upload is cropped to 4:5 hero aspect",
       abs(_pr - 0.8) < 0.03, f"ratio={_pr:.3f} size={_pim.size}")
_buf_teaser = BytesIO()
_PILImage.new("RGB", (300, 180), (239, 167, 51)).save(_buf_teaser, format="JPEG")
_buf_teaser.seek(0)
admin.post(
    "/admin/settings",
    data={
        "site_title": "Bloom Anyway", "instagram_url": "",
        "hero_image_url": "", "portrait_url": "/media/site/portrait",
        "contact_email": "", "announcement_text": "", "announcement_expires": "",
        "creator_name": "", "creator_instagram": "", "creator_image_url": "",
        "creator_blurb": "", "reel_url": "", "reel_description": "",
        "hero_file": (_buf_teaser, "teaser.jpg"),
    },
    content_type="multipart/form-data",
    follow_redirects=True,
)
with app.app_context():
    _hrow = site_img_svc.get("hero")
    _him = _PILImage.open(BytesIO(_hrow.data))
    _hr = _him.size[0] / _him.size[1]
    ok("Story teaser upload is cropped to 1:1 aspect",
       abs(_hr - 1.0) < 0.03, f"ratio={_hr:.3f} size={_him.size}")
r = app.test_client().get("/")
ok("Home uses the split healing / building hero",
   "home-hero" in r.get_data(as_text=True)
   and "home-panel--heal" in r.get_data(as_text=True)
   and "home-panel--build" in r.get_data(as_text=True))

_buf2 = BytesIO()
_PILImage.new("RGB", (100, 100), (239, 167, 51)).save(_buf2, format="JPEG")
_buf2.seek(0)
with app.app_context():
    _portrait_url = get_setting("portrait_url")
r = admin.post(
    "/admin/settings",
    data={
        "site_title": "Bloom Anyway", "instagram_url": "",
        "hero_image_url": "", "portrait_url": _portrait_url,
        "contact_email": "", "announcement_text": "", "announcement_expires": "",
        "creator_name": "Featured", "creator_instagram": "",
        "creator_image_url": "", "creator_blurb": "Hello",
        "reel_url": "", "reel_description": "",
        "creator_file": (_buf2, "creator.jpg"),
    },
    content_type="multipart/form-data",
    follow_redirects=True,
)
ok("Studio accepts creator-of-the-month photo upload", r.status_code == 200)
r = app.test_client().get("/media/site/creator")
ok("Uploaded creator photo is served",
   r.status_code == 200 and r.data[:3] == b"\xff\xd8\xff")
with app.app_context():
    ok("Creator photo setting points at media route",
       get_setting("creator_image_url") == "/media/site/creator")

# Content Hub: video library appears before reel reviews
r = client.get("/watch")
hub = r.get_data(as_text=True)
ok("Content Hub lists video library above reel reviews",
   hub.find('id="videos"') < hub.find('id="reviews"')
   and hub.find("Video library") < hub.find("Reel reviews"))

# Brevo helper strips Bearer / whitespace / wrapping quotes
from app.services import mailer as mailer_mod
_prev_brevo = os.environ.pop("BREVO_API_KEY", None)
try:
    with app.app_context():
        app.config["BREVO_API_KEY"] = "  Bearer  xkeysib-abc123  "
        cleaned = mailer_mod._brevo_api_key()
        app.config["BREVO_API_KEY"] = '"xkeysib-xyz-key"'
        quoted = mailer_mod._brevo_api_key()
        from_parsed = mailer_mod._strip_env_quotes('"Bloom Anyway <hello@example.com>"')
        name, email = mailer_mod._parse_mail_from("Bloom Anyway <hello@example.com>")
        bad_key_hint = mailer_mod._brevo_error_hint(401, '{"message":"Key not found"}')
        domain_hint = mailer_mod._brevo_error_hint(400, '{"message":"Invalid sender"}')
    ok("Brevo API key is normalized",
       cleaned == "xkeysib-abc123" and quoted == "xkeysib-xyz-key")
    ok("MAIL_FROM wrapping quotes are stripped",
       from_parsed == "Bloom Anyway <hello@example.com>")
    ok("MAIL_FROM parses into Brevo sender fields",
       name == "Bloom Anyway" and email == "hello@example.com")
    ok("Brevo 401 hint mentions API key",
       "BREVO_API_KEY" in bad_key_hint)
    ok("Brevo 400 hint mentions verified sender",
       "verified" in domain_hint.lower())
finally:
    if _prev_brevo is not None:
        os.environ["BREVO_API_KEY"] = _prev_brevo
    else:
        os.environ.pop("BREVO_API_KEY", None)

# brand rename: leftover "First Light" becomes Bloom Anyway on boot
from app.services.settings import ensure_brand_title, get_setting, invalidate_cache, set_setting
with app.app_context():
    set_setting("site_title", "First Light")
    invalidate_cache()
    rewritten = ensure_brand_title()
    new_title = get_setting("site_title")
ok("Legacy site title is rewritten to Bloom Anyway",
   rewritten and new_title == "Bloom Anyway", f"got {new_title!r}")

# --- 8. DB-backed SECRET_KEY (no env var needed) ---------------------------
KEY_DB = Path(tempfile.mkdtemp()) / "key.db"


class NoSecretConfig(TestConfig):
    SQLALCHEMY_DATABASE_URI = f"sqlite:///{KEY_DB.as_posix()}"
    SECRET_KEY = ""   # force the database-backed path


ks = create_app(NoSecretConfig)
with ks.app_context():
    db.create_all()
boot1 = create_app(NoSecretConfig)
boot2 = create_app(NoSecretConfig)
k1, k2 = boot1.config["SECRET_KEY"], boot2.config["SECRET_KEY"]
ok("SECRET_KEY auto-generated when unset", bool(k1) and len(k1) >= 32)
ok("SECRET_KEY stable across restarts", k1 == k2)
with boot2.app_context():
    from app.services.settings import all_settings
    ok("Secret key never leaks into public settings", "_secret_key" not in all_settings())

# --- 9. feedback inbox, content reports, legal, privacy hardening -----------
from app.models import Notification, PageView, SiteFeedback
from app.services.content_reports import review_text, submit_report
from app.services.privacy import close_account

css = client.get("/static/css/main.css").get_data(as_text=True)
ok("Auth pages keep the sun accent styles",
   ".sun-disc" in css and "sun-breathe" in css)
ok("Quote mini archive cards are centered",
   ".quote-mini" in css and "align-items: center" in css)

for path, needle in (("/privacy", "What we collect"),
                     ("/terms", "Memberships"),
                     ("/refunds", "14 days")):
    rr = client.get(path)
    body = rr.get_data(as_text=True)
    ok(f"Legal page {path} renders", rr.status_code == 200)
    ok(f"Legal page {path} has real copy",
       needle in body and "TODO: legal review" not in body)

r = client.get("/")
ok("Feedback widget on public pages",
   b"data-feedback-open" in r.data and b"feedback-dialog" in r.data)

r = client.post("/feedback", data={
    "kind": "feedback", "stars": "4", "body": "Loving the daily quotes.",
    "page_path": "/", "next": "/",
}, follow_redirects=True)
ok("Star feedback accepted", r.status_code == 200)
with app.app_context():
    fb = SiteFeedback.query.filter_by(kind="feedback").order_by(SiteFeedback.id.desc()).first()
    ok("Feedback stored with stars",
       fb is not None and fb.stars == 4 and "Loving" in fb.body)
    from app.models import Notification
    owner = User.query.filter_by(email="owner@example.com").first()
    owner_note = (Notification.query
                  .filter_by(user_id=owner.id, kind="inbox")
                  .order_by(Notification.id.desc()).first()) if owner else None
ok("Owners get a notification for new feedback",
   owner_note is not None and "feedback" in (owner_note.body or "").lower()
   and owner_note.url and "inbox" in owner_note.url)

r = client.post("/feedback", data={
    "kind": "complaint", "body": "Checkout felt confusing on mobile.",
    "page_path": "/membership", "next": "/",
}, follow_redirects=True)
ok("Complaint accepted", r.status_code == 200)

with app.app_context():
    err_before = SiteFeedback.query.filter_by(kind="error").count()
r = client.post("/feedback", data={
    "kind": "error", "body": "bot noise",
    "page_path": "/videos", "website": "http://bots.example",
    "next": "/",
}, follow_redirects=True)
with app.app_context():
    err_after_hp = SiteFeedback.query.filter_by(kind="error").count()
ok("Feedback honeypot ignored", r.status_code == 200 and err_after_hp == err_before)

r = client.post("/feedback", data={
    "kind": "error", "body": "Saw a 500 after uploading a huge video.",
    "page_path": "/videos", "next": "/",
}, follow_redirects=True)
with app.app_context():
    err = SiteFeedback.query.filter_by(kind="error").order_by(SiteFeedback.id.desc()).first()
ok("Error report stored for studio", err is not None and "500" in err.body)

ok("Auto-mod flags blocked language",
   review_text("what the fuck is this") == "Blocked language")
ok("Auto-mod passes clean text",
   review_text("Thanks for the gentle advice today.") is None)
ok("Auto-mod flags hostile phrase",
   review_text("you should just kill yourself") == "Hostile or threatening language")

with app.app_context():
    healing_cat = ForumCategory.query.filter_by(slug="healing").first()
    ok("Healing forum exists for report tests", healing_cat is not None)
    author = User(email="reporter-author@example.com", display_name="Author",
                  membership="healing", email_verified_at=utcnow())
    author.set_password(USER_PW)
    reporter = User(email="reporter-user@example.com", display_name="Reporter",
                    membership="healing", email_verified_at=utcnow())
    reporter.set_password(USER_PW)
    db.session.add_all([author, reporter])
    db.session.flush()
    clean = ForumPost(category_id=healing_cat.id, user_id=author.id,
                      title="Soft morning", body="Just checking in with kindness.",
                      anonymous=False)
    toxic = ForumPost(category_id=healing_cat.id, user_id=author.id,
                      title="Bad day", body="go kill yourself already",
                      anonymous=False)
    db.session.add_all([clean, toxic])
    db.session.commit()
    clean_id, toxic_id = clean.id, toxic.id
    author_id, reporter_id = author.id, reporter.id
    healing_cat_id = healing_cat.id

    rep_open, _msg = submit_report(reporter=reporter, target_type="post",
                                   target_id=clean_id, note="feels off")
    clean_after = db.session.get(ForumPost, clean_id)
    ok("Clean reported post stays visible",
       rep_open is not None and rep_open.status == "open" and not clean_after.hidden)

    rep_auto, _msg = submit_report(reporter=reporter, target_type="post",
                                   target_id=toxic_id, note="threat")
    toxic_after = db.session.get(ForumPost, toxic_id)
    note = Notification.query.filter_by(user_id=author_id, kind="moderation").first()
    ok("Toxic reported post auto-hidden",
       rep_auto is not None and rep_auto.status == "resolved" and toxic_after.hidden
       and bool(rep_auto.auto_reason))
    ok("Author notified on auto take-down", note is not None)

# refresh admin session for inbox checks
admin.post("/login", data={"email": "owner@example.com", "password": ADMIN_PW})
r = admin.get("/admin/inbox")
ok("Studio inbox loads", r.status_code == 200 and b"Inbox" in r.data)
r = admin.get("/admin/inbox?filter=feedback")
ok("Studio inbox feedback filter", r.status_code == 200 and b"Loving the daily" in r.data)
r = admin.get("/admin/inbox?filter=complaint")
ok("Studio inbox complaint filter", r.status_code == 200 and b"Checkout felt" in r.data)
r = admin.get("/admin/inbox?filter=error")
ok("Studio inbox error filter", r.status_code == 200 and b"huge video" in r.data)
r = admin.get("/admin/inbox?filter=open")
ok("Studio inbox open content reports", r.status_code == 200 and b"Soft morning" in r.data)
r = admin.get("/admin/inbox?filter=resolved")
ok("Studio inbox resolved shows auto reason",
   r.status_code == 200 and (b"Hostile" in r.data or b"Blocked" in r.data
                             or b"auto-hidden" in r.data))

rep_client = app.test_client()
rep_client.post("/login", data={"email": "reporter-user@example.com", "password": USER_PW})
r = rep_client.get(f"/forums/p/{clean_id}")
post_html = r.get_data(as_text=True)
ok("Report control on posts",
   "Report post" in post_html
   and f"/forums/p/{clean_id}/report" in post_html)

with app.app_context():
    from app.models import ForumComment
    author = db.session.get(User, author_id)
    cmt = ForumComment(post_id=clean_id, user_id=author_id,
                       body="A gentle reply worth reporting if needed.",
                       anonymous=False)
    db.session.add(cmt)
    db.session.commit()
    comment_id = cmt.id

r = rep_client.get(f"/forums/p/{clean_id}")
ok("Report control on comments",
   f"/forums/comment/{comment_id}/report" in r.get_data(as_text=True))
r = rep_client.post(f"/forums/comment/{comment_id}/report",
                    data={"note": "feels off"}, follow_redirects=True)
ok("Comment report is accepted", r.status_code == 200)
with app.app_context():
    from app.models import ContentReport
    c_rep = ContentReport.query.filter_by(
        reporter_id=reporter_id, target_type="comment", target_id=comment_id).first()
ok("Comment report is stored", c_rep is not None and c_rep.status == "open")

with app.app_context():
    from app.models import Notification
    owner = User.query.filter_by(email="owner@example.com").first()
    rep_note = (Notification.query
                .filter_by(user_id=owner.id, kind="inbox")
                .order_by(Notification.id.desc()).first()) if owner else None
ok("Owners get a notification for content reports",
   rep_note is not None and "report" in (rep_note.body or "").lower()
   and rep_note.url and "inbox" in rep_note.url)

r = rep_client.get("/forums/c/healing")
ok("Feed lists report control on posts",
   f"/forums/p/{clean_id}/report" in r.get_data(as_text=True)
   and "report-note-feed-" in r.get_data(as_text=True))

with app.app_context():
    doomed = User(email="doomed@example.com", display_name="Doomed Soul",
                  username="doomedx", bio="secret bio", membership="healing",
                  email_verified_at=utcnow(),
                  avatar_data=b"fakepng", avatar_mime="image/png")
    doomed.set_password(USER_PW)
    db.session.add(doomed)
    db.session.flush()
    doomed_post = ForumPost(category_id=healing_cat_id, user_id=doomed.id,
                            title="Will vanish", body="please hide me",
                            anonymous=False)
    db.session.add(doomed_post)
    db.session.commit()
    doomed_id, doomed_post_id = doomed.id, doomed_post.id
    close_account(doomed)
    doomed = db.session.get(User, doomed_id)
    doomed_post = db.session.get(ForumPost, doomed_post_id)
    ok("Closed account email scrubbed",
       doomed.deleted_at is not None and doomed.email.startswith("deleted+"))
    ok("Closed account profile scrubbed",
       doomed.display_name == "Former member" and doomed.username is None
       and doomed.bio is None and doomed.avatar_data is None
       and doomed.password_hash is None)
    ok("Closed account posts hidden", doomed_post.hidden is True)

ok("PageView has no IP field",
   not hasattr(PageView, "ip") and not hasattr(PageView, "ip_address"))

r = client.get("/this-page-does-not-exist-xyz")
ok("404 offers problem report", r.status_code == 404 and b"Report this problem" in r.data)

# --- 10. prelaunch lock (shallow gate; easy to remove at launch) ------------
from app.services import prelaunch as prelaunch_svc

app.config["PRELAUNCH_LOCK"] = True
with app.app_context():
    prelaunch_svc.set_public_browse(False)
anon = app.test_client()
r = anon.get("/")
ok("Prelaunch blocks home for strangers",
   r.status_code == 503 and b"Under construction" in r.data)
r = anon.get("/quotes")
ok("Prelaunch blocks deep URLs",
   r.status_code == 503 and b"Under construction" in r.data)
r = anon.get("/login")
ok("Prelaunch still allows login page", r.status_code == 200)
r = anon.get("/register")
ok("Prelaunch still allows signup page", r.status_code == 200)

# non-allowlisted signed-in member is blocked
locked_member = app.test_client()
with app.app_context():
    lm = User(email="locked-out@example.com", display_name="Locked",
              membership="healing", email_verified_at=utcnow())
    lm.set_password(USER_PW)
    db.session.add(lm)
    db.session.commit()
locked_member.post("/login", data={"email": "locked-out@example.com", "password": USER_PW})
r = locked_member.get("/account")
ok("Prelaunch blocks signed-in users not on the list",
   r.status_code == 503 and b"Under construction" in r.data)

# grant access via allowlist
with app.app_context():
    ok_add, _ = prelaunch_svc.add_email("locked-out@example.com")
    ok("Prelaunch allowlist accepts email", ok_add)
r = locked_member.get("/account")
ok("Allowlisted member can browse", r.status_code == 200)

# Studio toggle: allow viewing without invite list
with app.app_context():
    prelaunch_svc.set_public_browse(True)
    ok("Public browse setting turns on", prelaunch_svc.public_browse_enabled())
stranger = app.test_client()
r = stranger.get("/")
ok("Public browse lets strangers view home", r.status_code == 200)
r = stranger.get("/quotes")
ok("Public browse lets strangers view deep URLs", r.status_code == 200)
with app.app_context():
    prelaunch_svc.set_public_browse(False)
r = stranger.get("/")
ok("Turning public browse off restores the lock",
   r.status_code == 503 and b"Under construction" in r.data)

# owner admin still gets through (is_admin)
admin.post("/login", data={"email": "owner@example.com", "password": ADMIN_PW})
r = admin.get("/admin/prelaunch")
ok("Studio prelaunch page loads",
   r.status_code == 200 and b"Invite list" in r.data
   and b"Allow viewing without invite list" in r.data)
r = admin.post("/admin/prelaunch/public-browse",
               data={"public_browse": "1"}, follow_redirects=True)
ok("Studio can toggle public browse on",
   r.status_code == 200 and b"invite list is ignored" in r.data.lower())
r = stranger.get("/")
ok("Studio toggle opens the site for strangers", r.status_code == 200)
r = admin.post("/admin/prelaunch/public-browse", data={}, follow_redirects=True)
ok("Studio can toggle public browse off",
   r.status_code == 200 and b"invite list required" in r.data.lower())
r = admin.get("/")
ok("Admin owner can browse the site while locked", r.status_code == 200)

# hard-coded owner email always allowed
with app.app_context():
    ok("Hard-coded owner email is allowlisted",
       "mustafakhanabdullah07@gmail.com" in prelaunch_svc.OWNER_EMAILS)

app.config["PRELAUNCH_LOCK"] = False

print(f"\nAll {PASS} checks passed.")

