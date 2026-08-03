"""Admin panel. Every route requires is_admin + recent admin activity.

Freshness is a *sliding* idle timeout: each admin action pushes the clock
forward, so day-to-day use never nags. Re-authentication is only required after
``ADMIN_IDLE_DAYS`` of no admin activity.
"""
import io
import logging
import os
from datetime import date, datetime, timedelta
from functools import wraps

from flask import (abort, current_app, flash, redirect,
                   render_template, request, send_file, send_from_directory,
                   session, url_for)
from flask_login import current_user
from sqlalchemy import func
from sqlalchemy.orm import joinedload

from ..extensions import db
from ..models import (Announcement, CoachingRequest, ContentReport, FaqItem,
                      ForumComment, ForumPost, MEMBERSHIPS, MarketplaceListing,
                      MembershipPlan, Page, Product, Quote, QuoteFavorite,
                      QuotePin, ReelReview, ReelReviewApplication, SiteFeedback,
                      Testimonial, User, Video, QUOTE_CATEGORIES)
from ..services import badges as badges_service
from ..services import quotes as quotes_service
from ..services import reel_reviews as reel_svc
from ..services import stats
from ..services.mailer import last_send_error, send_email
from ..services.settings import DEFAULTS as SETTING_DEFAULTS
from ..services.settings import all_settings, set_setting
from ..services.social import (fetch_instagram_preview, instagram_handle,
                               instagram_profile_url, platform_for)
from ..services.videos import (VideoError, delete_stored, process_thumb,
                               process_video)
from . import bp

log = logging.getLogger(__name__)


def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        # 404 (not 403) so the panel's existence isn't revealed
        if not current_user.is_authenticated or not current_user.is_admin:
            abort(404)
        now = datetime.utcnow()
        idle_max = timedelta(days=current_app.config["ADMIN_IDLE_DAYS"])
        # last admin activity, falling back to the original sign-in time
        seen_at = session.get("admin_seen_at") or session.get("logged_in_at")
        try:
            active = seen_at and (now - datetime.fromisoformat(seen_at)) < idle_max
        except ValueError:
            active = False
        if not active:
            flash("It's been a while \u2014 please sign in again to open the studio.", "info")
            return redirect(url_for("auth.login", next=request.path))
        # slide the window forward on every admin action
        session.permanent = True
        session["admin_seen_at"] = now.isoformat()
        # keep the owner's stored tier at Creator so member-gated pages match
        if current_user.membership != "creator":
            current_user.membership = "creator"
            db.session.commit()
        return f(*args, **kwargs)
    return wrapper


def _spotlight_candidates():
    """Creator members (and the owner) with an Instagram link — pick-list for
    Creator of the Month / Reel of the Week."""
    creators = (User.query.filter(
                    User.deleted_at.is_(None),
                    db.or_(User.membership == "creator", User.is_admin.is_(True)))
                .order_by(User.display_name).all())
    out = []
    for u in creators:
        handle = None
        for link in u.links():
            if platform_for(link["url"]) == "Instagram":
                handle = instagram_handle(link["url"]) or link["url"]
                break
        out.append({"name": u.public_name(), "email": u.email,
                    "instagram": f"@{handle}" if handle and not str(handle).startswith("http") else handle,
                    "profile_url": instagram_profile_url(handle) if handle else None})
    return out


# =============================== DASHBOARD ===================================

@bp.route("/")
@admin_required
def dashboard():
    today = date.today()
    return render_template(
        "admin/dashboard.html",
        today_quote=quotes_service.quote_for(today),
        tomorrow_quote=quotes_service.quote_for(today + timedelta(days=1)),
        cards=stats.dashboard_cards(),
        chart_signups=stats.signups_by_week(12),
        most_visited=stats.most_visited(7),
        memberships=stats.membership_breakdown(),
        video_count=stats.video_count(),
        marketplace=stats.marketplace_counts(),
    )


# =============================== PRODUCTS ====================================
# Courses & guides are sold on shop.bloomanyway.online. The Product / ProductAsset
# tables remain for historical orders, testimonials, and dashboard filters — but
# Studio no longer publishes an on-site catalog.

@bp.route("/products")
@bp.route("/products/new")
@bp.route("/products/<int:product_id>/edit")
@bp.route("/products/<int:product_id>/delete", methods=["POST"])
@bp.route("/products/reorder", methods=["POST"])
@admin_required
def products(product_id=None):
    flash("Courses & guides are managed on the Lemon Squeezy shop "
          "(shop.bloomanyway.online), not in Studio.", "info")
    return redirect(url_for("admin.dashboard"))


# ================================ QUOTES =====================================

@bp.route("/quotes")
@admin_required
def quotes():
    items = Quote.query.order_by(Quote.id.desc()).all()
    fav_counts = dict(
        db.session.query(QuoteFavorite.quote_id, func.count(QuoteFavorite.id))
        .group_by(QuoteFavorite.quote_id).all()
    )
    pins = QuotePin.query.filter(QuotePin.date >= date.today()).order_by(QuotePin.date).all()
    tomorrow = date.today() + timedelta(days=1)
    return render_template("admin/quotes.html", quotes=items, fav_counts=fav_counts,
                           pins=pins, tomorrow=tomorrow,
                           tomorrow_quote=quotes_service.quote_for(tomorrow),
                           categories=QUOTE_CATEGORIES)


@bp.route("/quotes/save", methods=["POST"])
@bp.route("/quotes/<int:quote_id>/save", methods=["POST"])
@admin_required
def quote_save(quote_id=None):
    quote = db.session.get(Quote, quote_id) if quote_id else Quote()
    if quote_id and quote is None:
        abort(404)
    text = (request.form.get("text") or "").strip()
    category = request.form.get("category")
    if not text or len(text) > 240:
        flash("Quote text is required (240 characters max).", "error")
        return redirect(url_for("admin.quotes"))
    if category not in QUOTE_CATEGORIES:
        flash("Pick a category.", "error")
        return redirect(url_for("admin.quotes"))
    quote.text = text
    quote.author = (request.form.get("author") or "").strip() or None
    quote.category = category
    quote.active = bool(request.form.get("active", quote_id is None))
    if quote.id is None:
        db.session.add(quote)
    db.session.commit()
    flash("Quote saved.", "success")
    return redirect(url_for("admin.quotes"))


@bp.route("/quotes/<int:quote_id>/toggle", methods=["POST"])
@admin_required
def quote_toggle(quote_id):
    quote = db.session.get(Quote, quote_id) or abort(404)
    quote.active = not quote.active
    db.session.commit()
    return redirect(url_for("admin.quotes"))


@bp.route("/quotes/<int:quote_id>/delete", methods=["POST"])
@admin_required
def quote_delete(quote_id):
    quote = db.session.get(Quote, quote_id) or abort(404)
    QuotePin.query.filter_by(quote_id=quote.id).delete()
    db.session.delete(quote)
    db.session.commit()
    flash("Quote deleted.", "success")
    return redirect(url_for("admin.quotes"))


@bp.route("/quotes/pin", methods=["POST"])
@admin_required
def quote_pin():
    try:
        pin_date = date.fromisoformat(request.form.get("date", ""))
        quote_id = int(request.form.get("quote_id", ""))
    except (ValueError, TypeError):
        flash("Pick a date and a quote to pin.", "error")
        return redirect(url_for("admin.quotes"))
    if db.session.get(Quote, quote_id) is None:
        abort(404)
    pin = QuotePin.query.filter_by(date=pin_date).first()
    if pin:
        pin.quote_id = quote_id
    else:
        db.session.add(QuotePin(date=pin_date, quote_id=quote_id))
    db.session.commit()
    flash(f"Pinned for {pin_date.isoformat()}.", "success")
    return redirect(url_for("admin.quotes"))


@bp.route("/quotes/pin/<int:pin_id>/delete", methods=["POST"])
@admin_required
def quote_unpin(pin_id):
    pin = db.session.get(QuotePin, pin_id) or abort(404)
    db.session.delete(pin)
    db.session.commit()
    flash("Pin removed \u2014 that day goes back to rotation.", "success")
    return redirect(url_for("admin.quotes"))


def _parse_import(raw: str):
    """`text | author | category` per line -> (rows, problems)."""
    rows, problems = [], []
    existing = {q.text.strip().lower() for q in Quote.query.all()}
    seen_in_batch = set()
    for i, line in enumerate(raw.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split("|")]
        text = parts[0] if parts else ""
        author = parts[1] if len(parts) > 1 and parts[1] else None
        category = (parts[2].lower() if len(parts) > 2 else "comfort")
        if not text or len(text) > 240:
            problems.append(f"Line {i}: text missing or over 240 chars \u2014 skipped.")
            continue
        if category not in QUOTE_CATEGORIES:
            problems.append(f'Line {i}: unknown category "{category}" \u2014 using comfort.')
            category = "comfort"
        key = text.lower()
        if key in existing or key in seen_in_batch:
            problems.append(f"Line {i}: duplicate \u2014 skipped.")
            continue
        seen_in_batch.add(key)
        rows.append({"text": text, "author": author, "category": category})
    return rows, problems


@bp.route("/quotes/import", methods=["POST"])
@admin_required
def quote_import():
    raw = request.form.get("bulk") or ""
    rows, problems = _parse_import(raw)
    if request.form.get("confirm") == "yes":
        for row in rows:
            db.session.add(Quote(**row))
        db.session.commit()
        flash(f"Imported {len(rows)} quotes." + (f" ({len(problems)} lines skipped.)" if problems else ""), "success")
        return redirect(url_for("admin.quotes"))
    return render_template("admin/quote_import_preview.html", rows=rows,
                           problems=problems, raw=raw)


# ============================ TESTIMONIALS ===================================

@bp.route("/testimonials")
@admin_required
def testimonials():
    items = Testimonial.query.order_by(Testimonial.sort_order).all()
    products = Product.query.order_by(Product.title).all()
    return render_template("admin/testimonials.html", items=items, products=products)


@bp.route("/testimonials/save", methods=["POST"])
@bp.route("/testimonials/<int:item_id>/save", methods=["POST"])
@admin_required
def testimonial_save(item_id=None):
    item = db.session.get(Testimonial, item_id) if item_id else Testimonial()
    if item_id and item is None:
        abort(404)
    quote = (request.form.get("quote") or "").strip()
    first_name = (request.form.get("first_name") or "").strip()[:60]
    if not quote or not first_name:
        flash("A testimonial needs both a quote and a first name.", "error")
        return redirect(url_for("admin.testimonials"))
    item.quote = quote
    item.first_name = first_name
    item.product_id = int(request.form["product_id"]) if request.form.get("product_id") else None
    item.show_on_home = bool(request.form.get("show_on_home"))
    try:
        item.sort_order = int(request.form.get("sort_order") or 0)
    except ValueError:
        item.sort_order = 0
    if item.id is None:
        db.session.add(item)
    db.session.commit()
    flash("Testimonial saved.", "success")
    return redirect(url_for("admin.testimonials"))


@bp.route("/testimonials/<int:item_id>/delete", methods=["POST"])
@admin_required
def testimonial_delete(item_id):
    item = db.session.get(Testimonial, item_id) or abort(404)
    db.session.delete(item)
    db.session.commit()
    flash("Testimonial deleted.", "success")
    return redirect(url_for("admin.testimonials"))


# ================================= FAQ =======================================

@bp.route("/faq")
@admin_required
def faq():
    items = FaqItem.query.order_by(FaqItem.sort_order).all()
    return render_template("admin/faq.html", items=items)


@bp.route("/faq/save", methods=["POST"])
@bp.route("/faq/<int:item_id>/save", methods=["POST"])
@admin_required
def faq_save(item_id=None):
    item = db.session.get(FaqItem, item_id) if item_id else FaqItem()
    if item_id and item is None:
        abort(404)
    question = (request.form.get("question") or "").strip()[:240]
    answer = (request.form.get("answer_md") or "").strip()
    if not question or not answer:
        flash("A FAQ item needs both a question and an answer.", "error")
        return redirect(url_for("admin.faq"))
    item.question = question
    item.answer_md = answer
    try:
        item.sort_order = int(request.form.get("sort_order") or 0)
    except ValueError:
        item.sort_order = 0
    if item.id is None:
        db.session.add(item)
    db.session.commit()
    flash("FAQ saved.", "success")
    return redirect(url_for("admin.faq"))


@bp.route("/faq/<int:item_id>/delete", methods=["POST"])
@admin_required
def faq_delete(item_id):
    item = db.session.get(FaqItem, item_id) or abort(404)
    db.session.delete(item)
    db.session.commit()
    flash("FAQ item deleted.", "success")
    return redirect(url_for("admin.faq"))


# ================================ PAGES ======================================

EDITABLE_PAGES = (
    ("about", "Her Story (About page)"),
    ("privacy", "Privacy Policy"),
    ("terms", "Terms of Service"),
    ("refunds", "Refund Policy"),
)


@bp.route("/pages")
@admin_required
def pages():
    existing = {p.slug: p for p in Page.query.all()}
    return render_template("admin/pages.html", editable=EDITABLE_PAGES, existing=existing)


@bp.route("/pages/<slug>", methods=["GET", "POST"])
@admin_required
def page_edit(slug):
    labels = dict(EDITABLE_PAGES)
    if slug not in labels:
        abort(404)
    page = Page.query.filter_by(slug=slug).first()
    if request.method == "POST":
        title = (request.form.get("title") or labels[slug]).strip()[:160]
        body = request.form.get("body_md") or ""
        if page is None:
            page = Page(slug=slug, title=title, body_md=body)
            db.session.add(page)
        else:
            page.title = title
            page.body_md = body
        db.session.commit()
        flash("Page saved.", "success")
        return redirect(url_for("admin.pages"))
    return render_template("admin/page_form.html", page=page, slug=slug, label=labels[slug])


# ============================= SUBSCRIBERS ===================================
# Email list / checkout analytics live in Lemon Squeezy — Studio no longer mirrors them.

@bp.route("/subscribers")
@bp.route("/subscribers/export.csv")
@admin_required
def subscribers():
    flash("Subscriber lists and sales live in Lemon Squeezy.", "info")
    return redirect(url_for("admin.dashboard"))


@bp.route("/subscribers/<int:sub_id>/delete", methods=["POST"])
@admin_required
def subscriber_delete(sub_id):
    return redirect(url_for("admin.dashboard"))


# ================================ ORDERS =====================================
# Order history lives in Lemon Squeezy — Studio no longer mirrors the sales list.

@bp.route("/orders")
@bp.route("/orders/export.csv")
@admin_required
def orders():
    flash("Orders and revenue live in Lemon Squeezy.", "info")
    return redirect(url_for("admin.dashboard"))


# =============================== SETTINGS ====================================

@bp.route("/settings/test-email", methods=["POST"])
@admin_required
def settings_test_email():
    """Send a one-off test via the live Brevo/SMTP config (Studio only)."""
    to = (current_user.email or "").strip()
    if not to:
        flash("Your owner account has no email address.", "error")
        return redirect(url_for("admin.settings"))
    ok = send_email(
        to,
        "Bloom Anyway — test email",
        "If you received this, email sending from the site is working.\n\n"
        "— Bloom Anyway",
    )
    if ok:
        flash(f"Test email sent to {to}. Check inbox and spam.", "success")
    else:
        hint = last_send_error() or "Unknown email error — check Render logs for Brevo."
        flash(f"Test email failed. {hint}", "error")
    return redirect(url_for("admin.settings"))


@bp.route("/settings", methods=["GET", "POST"])
@admin_required
def settings():
    if request.method == "POST":
        if request.form.get("clear_announcement"):
            set_setting("announcement_text", "")
            set_setting("announcement_expires", "")
            flash("Announcement removed.", "success")
            return redirect(url_for("admin.settings"))
        if request.form.get("add_announcement"):
            body = (request.form.get("ann_body") or "").strip()[:300]
            if body:
                expires = date.today() + timedelta(days=1)  # default: 1 day
                raw = (request.form.get("ann_expires") or "").strip()
                if raw:
                    try:
                        expires = date.fromisoformat(raw)
                    except ValueError:
                        pass
                db.session.add(Announcement(body=body, expires=expires))
                from ..services.social_graph import notify_everyone
                notify_everyone(
                    kind="announcement",
                    body=f"Site update: {body[:120]}",
                    url=url_for("main.index"),
                    actor_id=current_user.id,
                    exclude_id=current_user.id,
                )
                db.session.commit()
                flash("Announcement added.", "success")
            else:
                flash("Write something first.", "error")
            return redirect(url_for("admin.settings"))
        remove_id = request.form.get("remove_announcement")
        if remove_id and remove_id.isdigit():
            ann = db.session.get(Announcement, int(remove_id))
            if ann:
                db.session.delete(ann)
                db.session.commit()
            flash("Announcement removed.", "success")
            return redirect(url_for("admin.settings"))
        values = {key: (request.form.get(key) or "").strip()
                  for key in SETTING_DEFAULTS}
        # store a clean Instagram handle (never a share-link with ?igsh=…)
        handle = instagram_handle(values.get("creator_instagram") or "")
        values["creator_instagram"] = handle
        # if photo/bio were left blank, try a public Instagram preview
        if handle and (not values.get("creator_image_url")
                       or not values.get("creator_blurb")):
            preview = fetch_instagram_preview(handle)
            if preview.get("image") and not values.get("creator_image_url"):
                values["creator_image_url"] = preview["image"]
            if preview.get("blurb") and not values.get("creator_blurb"):
                values["creator_blurb"] = preview["blurb"]
        # quick announcement: blank expiry defaults to tomorrow
        if values.get("announcement_text") and not values.get("announcement_expires"):
            values["announcement_expires"] = (date.today() + timedelta(days=1)).isoformat()
        for key, val in values.items():
            set_setting(key, val)
        flash("Settings saved.", "success")
        return redirect(url_for("admin.settings"))
    values = all_settings()
    # show a friendly @handle in the form even if an old full URL is stored
    if values.get("creator_instagram"):
        h = instagram_handle(values["creator_instagram"])
        values["creator_instagram"] = f"@{h}" if h else values["creator_instagram"]
    announcements = (Announcement.query
                     .order_by(Announcement.sort_order, Announcement.created_at.desc()).all())
    default_expires = (date.today() + timedelta(days=1)).isoformat()
    return render_template("admin/settings.html", values=values,
                           spotlight=_spotlight_candidates(),
                           announcements=announcements, today=date.today(),
                           default_expires=default_expires)


# ============================ MARKETPLACE ====================================

@bp.route("/marketplace")
@admin_required
def marketplace():
    listings = (MarketplaceListing.query
                .options(joinedload(MarketplaceListing.author))
                .order_by(MarketplaceListing.active.desc(),
                          MarketplaceListing.created_at.desc()).all())
    return render_template("admin/marketplace.html", listings=listings)


@bp.route("/marketplace/<int:listing_id>/toggle", methods=["POST"])
@admin_required
def marketplace_toggle(listing_id):
    ln = db.session.get(MarketplaceListing, listing_id) or abort(404)
    ln.active = not ln.active
    db.session.commit()
    flash("Listing hidden." if not ln.active else "Listing restored.", "success")
    return redirect(url_for("admin.marketplace"))


@bp.route("/marketplace/<int:listing_id>/delete", methods=["POST"])
@admin_required
def marketplace_delete(listing_id):
    ln = db.session.get(MarketplaceListing, listing_id) or abort(404)
    db.session.delete(ln)
    db.session.commit()
    flash("Listing deleted.", "success")
    return redirect(url_for("admin.marketplace"))


# =============================== VIDEOS ======================================

@bp.route("/videos")
@admin_required
def videos():
    items = Video.query.order_by(Video.sort_order, Video.created_at.desc()).all()
    return render_template("admin/videos.html", videos=items)


@bp.route("/videos/new", methods=["GET", "POST"])
@bp.route("/videos/<int:video_id>/edit", methods=["GET", "POST"])
@admin_required
def video_form(video_id=None):
    video = db.session.get(Video, video_id) if video_id else None
    if video_id and video is None:
        abort(404)

    if request.method == "POST":
        title = (request.form.get("title") or "").strip()[:160]
        description = (request.form.get("description") or "").strip() or None
        published = bool(request.form.get("published"))
        free_access = bool(request.form.get("free_access"))
        try:
            sort_order = int(request.form.get("sort_order") or 0)
        except ValueError:
            sort_order = 0

        errors = []
        if not title:
            errors.append("A title is required.")

        new_video = None
        upload = request.files.get("video_file")
        if upload and upload.filename:
            try:
                new_video = process_video(
                    upload, current_app.config["VIDEO_STORAGE_DIR"],
                    current_app.config["MAX_VIDEO_MB"] * 1024 * 1024)
            except VideoError as exc:
                errors.append(str(exc))
        elif video is None:
            errors.append("Please choose a video file to upload.")

        new_thumb = None
        thumb = request.files.get("thumb_file")
        if thumb and thumb.filename:
            try:
                new_thumb = process_thumb(thumb)
            except VideoError as exc:
                errors.append(str(exc))

        if errors:
            for e in errors:
                flash(e, "error")
        else:
            old_disk = None
            was_live = bool(video and video.published)
            try:
                if video is None:
                    video = Video(mime="video/mp4")
                    db.session.add(video)
                video.title = title
                video.description = description
                video.published = published
                video.free_access = free_access
                video.sort_order = sort_order
                if new_video:
                    disk_name, mime, fname, size = new_video
                    old_disk = video.disk_name  # replaced file, delete after commit
                    video.disk_name, video.mime, video.filename = disk_name, mime, fname
                    video.size = size
                    video.data = None
                if new_thumb:
                    video.thumb_data, video.thumb_mime = new_thumb
                if request.form.get("remove_thumb"):
                    video.thumb_data = None
                    video.thumb_mime = None
                db.session.flush()
                if published and not was_live:
                    from ..services.social_graph import notify_everyone
                    notify_everyone(
                        kind="content_hub",
                        body=f"New on Content Hub: “{title[:80]}”",
                        url=url_for("main.watch", video_id=video.id),
                        actor_id=current_user.id,
                        exclude_id=current_user.id,
                    )
                db.session.commit()
            except Exception:
                db.session.rollback()
                log.exception("video upload failed")
                # a brand-new file we just wrote is now orphaned; clean it up
                if new_video:
                    delete_stored(current_app.config["VIDEO_STORAGE_DIR"], new_video[0])
                flash("We couldn't save that video just now \u2014 please try again.",
                      "error")
            else:
                if old_disk:
                    delete_stored(current_app.config["VIDEO_STORAGE_DIR"], old_disk)
                flash("Video saved.", "success")
                return redirect(url_for("admin.videos"))

    return render_template("admin/video_form.html", video=video,
                           max_mb=current_app.config["MAX_VIDEO_MB"])


@bp.route("/videos/<int:video_id>/delete", methods=["POST"])
@admin_required
def video_delete(video_id):
    video = db.session.get(Video, video_id) or abort(404)
    disk_name = video.disk_name
    db.session.delete(video)
    db.session.commit()
    delete_stored(current_app.config["VIDEO_STORAGE_DIR"], disk_name)
    flash("Video deleted.", "success")
    return redirect(url_for("admin.videos"))


# =============================== MEMBERS =====================================

@bp.route("/members")
@admin_required
def members():
    q = (request.args.get("q") or "").strip()
    query = User.query.filter(User.deleted_at.is_(None))
    if q:
        like = f"%{q}%"
        query = query.filter(db.or_(User.email.ilike(like),
                                    User.display_name.ilike(like)))
    people = query.order_by(User.created_at.desc()).limit(200).all()
    counts = dict(db.session.query(User.membership, func.count(User.id))
                  .filter(User.deleted_at.is_(None)).group_by(User.membership).all())
    return render_template("admin/members.html", people=people, counts=counts,
                           memberships=MEMBERSHIPS, q=q,
                           spotlight=_spotlight_candidates())


@bp.route("/members/<int:user_id>/membership", methods=["POST"])
@admin_required
def set_membership(user_id):
    member = db.session.get(User, user_id) or abort(404)
    if member.is_admin:
        flash("The owner account always keeps Creator access.", "info")
        return redirect(request.form.get("next") or url_for("admin.members"))
    tier = request.form.get("membership")
    if tier in MEMBERSHIPS:
        member.membership = tier
        from ..services.listings import enforce_listing_limits
        enforce_listing_limits(member)
        db.session.commit()
        flash(f"{member.public_name()} \u2192 {member.membership_label()}.", "success")
    return redirect(request.form.get("next") or url_for("admin.members"))


# ============================ MEMBERSHIP PLANS ===============================

_PLAN_DEFAULTS = {
    "healing": {"name": "Healing membership",
                "tagline": "Belong to the whole community.", "sort_order": 1},
    "creator": {"name": "Creator membership",
                "tagline": "Everything, plus the tools to be seen.", "sort_order": 2},
}


def _get_plans():
    """Return the two membership plans, creating any that are missing."""
    plans = {p.tier: p for p in MembershipPlan.query.all()}
    changed = False
    for tier, d in _PLAN_DEFAULTS.items():
        if tier not in plans:
            plan = MembershipPlan(tier=tier, name=d["name"], tagline=d["tagline"],
                                  sort_order=d["sort_order"])
            db.session.add(plan)
            plans[tier] = plan
            changed = True
    if changed:
        db.session.commit()
    return [plans["healing"], plans["creator"]]


@bp.route("/memberships", methods=["GET", "POST"])
@admin_required
def membership_plans():
    plans = _get_plans()
    if request.method == "POST":
        for plan in plans:
            p = plan.tier
            plan.name = (request.form.get(f"{p}_name") or plan.name).strip()
            plan.tagline = (request.form.get(f"{p}_tagline") or "").strip() or None
            plan.currency = (request.form.get(f"{p}_currency") or "USD").strip().upper()[:3]
            plan.period = request.form.get(f"{p}_period") or "month"
            plan.ls_variant_id = (request.form.get(f"{p}_variant") or "").strip() or None
            plan.ls_checkout_url = (request.form.get(f"{p}_checkout") or "").strip() or None
            plan.active = bool(request.form.get(f"{p}_active"))
            raw = (request.form.get(f"{p}_price") or "").strip().replace(",", "")
            try:
                plan.price_cents = round(float(raw) * 100) if raw else None
            except ValueError:
                plan.price_cents = plan.price_cents
        db.session.commit()
        flash("Membership plans saved.", "success")
        return redirect(url_for("admin.membership_plans"))
    return render_template("admin/membership_plans.html", plans=plans)


# ================================ BADGES =====================================

@bp.route("/badges", methods=["GET", "POST"])
@admin_required
def badges():
    if request.method == "POST":
        if request.form.get("reset"):
            badges_service.reset_thresholds()
            flash("Milestones reset to their defaults.", "success")
            return redirect(url_for("admin.badges"))

        mapping, errors = {}, []
        for cat_key, cat in badges_service.CATEGORIES.items():
            values = []
            for level in range(1, len(cat["tiers"]) + 1):
                raw = (request.form.get(f"t_{cat_key}_{level}") or "").strip()
                try:
                    n = int(raw)
                except ValueError:
                    errors.append(f"{cat['name']}: milestone {level} must be a whole number.")
                    break
                if n < 1:
                    errors.append(f"{cat['name']}: milestones must be at least 1.")
                    break
                if values and n <= values[-1]:
                    errors.append(f"{cat['name']}: each milestone must be higher than the one before.")
                    break
                values.append(n)
            if len(values) == len(cat["tiers"]):
                mapping[cat_key] = values

        if errors:
            for msg in errors:
                flash(msg, "error")
            return redirect(url_for("admin.badges"))

        badges_service.set_thresholds(mapping)
        flash("Milestones saved.", "success")
        return redirect(url_for("admin.badges"))

    return render_template("admin/badges.html",
                           overview=badges_service.all_badges_overview(),
                           owner_badge=badges_service.OWNER_BADGE)


# ======================= PRELAUNCH ACCESS (remove at launch) =================

@bp.route("/prelaunch")
@admin_required
def prelaunch():
    from ..services import prelaunch as prelaunch_svc
    return render_template(
        "admin/prelaunch.html",
        emails=prelaunch_svc.allowlist(),
        owner_emails=sorted(prelaunch_svc.OWNER_EMAILS),
        lock_on=bool(current_app.config.get("PRELAUNCH_LOCK")),
    )


@bp.route("/prelaunch/add", methods=["POST"])
@admin_required
def prelaunch_add():
    from ..services import prelaunch as prelaunch_svc
    ok, msg = prelaunch_svc.add_email(request.form.get("email") or "")
    flash(msg, "success" if ok else "error")
    return redirect(url_for("admin.prelaunch"))


@bp.route("/prelaunch/remove", methods=["POST"])
@admin_required
def prelaunch_remove():
    from ..services import prelaunch as prelaunch_svc
    ok, msg = prelaunch_svc.remove_email(request.form.get("email") or "")
    flash(msg, "success" if ok else "error")
    return redirect(url_for("admin.prelaunch"))


# ============================ FEEDBACK INBOX =================================

@bp.route("/inbox")
@admin_required
def inbox():
    """Unified inbox: star feedback, complaints, error reports, content reports."""
    filt = (request.args.get("filter") or "all").strip().lower()
    allowed = {"all", "feedback", "complaint", "error", "reports", "open", "resolved"}
    if filt not in allowed:
        filt = "all"

    feedback_q = (SiteFeedback.query.options(joinedload(SiteFeedback.author))
                  .order_by(SiteFeedback.created_at.desc()))
    reports_q = (ContentReport.query.options(joinedload(ContentReport.reporter))
                 .order_by(ContentReport.created_at.desc()))

    show_feedback = filt in ("all", "feedback", "complaint", "error")
    show_reports = filt in ("all", "reports", "open", "resolved")

    feedback_rows = []
    if show_feedback:
        q = feedback_q
        if filt in ("feedback", "complaint", "error"):
            q = q.filter_by(kind=filt)
        feedback_rows = q.limit(100).all()

    report_rows = []
    if show_reports:
        q = reports_q
        if filt == "open":
            q = q.filter_by(status="open")
        elif filt == "resolved":
            q = q.filter(ContentReport.status.in_(("resolved", "dismissed")))
        report_rows = q.limit(100).all()

    # Attach target snippets for studio display
    enriched = []
    for r in report_rows:
        target = None
        snippet = ""
        if r.target_type == "post":
            target = db.session.get(ForumPost, r.target_id)
            if target:
                snippet = f"{target.title}: {(target.body or '')[:160]}"
        else:
            target = db.session.get(ForumComment, r.target_id)
            if target:
                snippet = (target.body or "")[:200]
        enriched.append({"report": r, "target": target, "snippet": snippet})

    counts = {
        "feedback": SiteFeedback.query.filter_by(kind="feedback").count(),
        "complaint": SiteFeedback.query.filter_by(kind="complaint").count(),
        "error": SiteFeedback.query.filter_by(kind="error").count(),
        "reports_open": ContentReport.query.filter_by(status="open").count(),
        "reports_resolved": ContentReport.query.filter(
            ContentReport.status.in_(("resolved", "dismissed"))).count(),
    }
    return render_template(
        "admin/inbox.html", filter=filt, feedback_rows=feedback_rows,
        report_rows=enriched, counts=counts,
    )


@bp.route("/inbox/feedback/<int:item_id>/reviewed", methods=["POST"])
@admin_required
def inbox_feedback_reviewed(item_id):
    from ..services.feedback import mark_reviewed
    row = db.session.get(SiteFeedback, item_id) or abort(404)
    mark_reviewed(row)
    flash("Marked reviewed.", "success")
    return redirect(url_for("admin.inbox", filter=request.form.get("filter") or "all"))


@bp.route("/inbox/reports/<int:report_id>/hide", methods=["POST"])
@admin_required
def inbox_report_hide(report_id):
    from ..services.content_reports import hide_target
    report = db.session.get(ContentReport, report_id) or abort(404)
    hide_target(report, owner_note=request.form.get("owner_note") or "")
    flash("Content hidden and reporter case resolved.", "success")
    return redirect(url_for("admin.inbox", filter=request.form.get("filter") or "reports"))


@bp.route("/inbox/reports/<int:report_id>/dismiss", methods=["POST"])
@admin_required
def inbox_report_dismiss(report_id):
    from ..services.content_reports import dismiss_report
    report = db.session.get(ContentReport, report_id) or abort(404)
    dismiss_report(report, owner_note=request.form.get("owner_note") or "")
    flash("Report dismissed — no take-down.", "success")
    return redirect(url_for("admin.inbox", filter=request.form.get("filter") or "reports"))


# =============================== COMMUNITY ===================================

@bp.route("/community")
@admin_required
def community():
    posts = (ForumPost.query.options(joinedload(ForumPost.category),
                                     joinedload(ForumPost.author))
             .order_by(ForumPost.created_at.desc()).limit(100).all())
    flagged = (User.query.filter((User.forum_warnings > 0) | (User.forum_banned.is_(True)))
               .order_by(User.forum_banned.desc(), User.forum_warnings.desc()).all())
    return render_template("admin/community.html", posts=posts, flagged=flagged)


@bp.route("/community/post/<int:post_id>/delete", methods=["POST"])
@admin_required
def community_delete_post(post_id):
    post = db.session.get(ForumPost, post_id) or abort(404)
    db.session.delete(post)
    db.session.commit()
    flash("Post removed.", "success")
    return redirect(url_for("admin.community"))


@bp.route("/community/comment/<int:comment_id>/delete", methods=["POST"])
@admin_required
def community_delete_comment(comment_id):
    comment = db.session.get(ForumComment, comment_id) or abort(404)
    db.session.delete(comment)
    db.session.commit()
    flash("Comment removed.", "success")
    return redirect(url_for("admin.community"))


@bp.route("/community/member/<int:user_id>/reset", methods=["POST"])
@admin_required
def community_reset_member(user_id):
    member = db.session.get(User, user_id) or abort(404)
    member.forum_warnings = 0
    member.forum_banned = False
    db.session.commit()
    flash("Fresh start given \u2014 warnings cleared and posting restored.", "success")
    return redirect(url_for("admin.community"))


# ============================ REEL REVIEWS ===================================

@bp.route("/reel-reviews")
@admin_required
def reel_reviews():
    week = reel_svc.current_week_key()
    applicants = reel_svc.week_applicants(week)
    week_review = reel_svc.published_review_for_week(week)
    published = (ReelReview.query
                 .order_by(ReelReview.created_at.desc()).limit(40).all())
    return render_template("admin/reel_reviews.html", week_key=week,
                           applicants=applicants, reviews=published,
                           week_review=week_review,
                           week_closed=week_review is not None,
                           max_mb=current_app.config["MAX_VIDEO_MB"])


@bp.route("/reel-reviews/pick", methods=["POST"])
@admin_required
def reel_reviews_pick():
    if reel_svc.week_is_closed():
        flash("This week's review is already published — one review per week. "
              "A new draw opens next Monday.", "info")
        return redirect(url_for("admin.reel_reviews"))
    chosen = reel_svc.pick_random_applicant()
    if chosen is None:
        flash("No applicants in this week's draw yet.", "error")
    else:
        flash(f"Selected {chosen.author.public_name()} for this week's review.",
              "success")
    return redirect(url_for("admin.reel_reviews"))


@bp.route("/reel-reviews/<int:app_id>/raw")
@admin_required
def reel_reviews_raw_download(app_id):
    """Download the applicant's raw unedited video (Studio only)."""
    application = db.session.get(ReelReviewApplication, app_id) or abort(404)
    name = application.filename or "raw-reel.mp4"
    mime = application.mime or "application/octet-stream"

    # Prefer on-disk file (streamed uploads). Fall back to legacy DB bytes.
    disk_name = os.path.basename(application.disk_name or "")
    if disk_name:
        directory = os.path.abspath(current_app.config["VIDEO_STORAGE_DIR"])
        path = os.path.join(directory, disk_name)
        if os.path.isfile(path):
            resp = send_from_directory(
                directory, disk_name,
                mimetype=mime,
                as_attachment=True,
                download_name=name,
                max_age=0,
            )
            resp.headers["Cache-Control"] = "private, no-store"
            return resp

    if application.data:
        resp = send_file(
            io.BytesIO(bytes(application.data)),
            mimetype=mime,
            as_attachment=True,
            download_name=name,
            max_age=0,
        )
        resp.headers["Cache-Control"] = "private, no-store"
        return resp

    flash("That entry has no raw video upload. Ask them to re-enter "
          "this week's draw with a fresh file.", "error")
    return redirect(url_for("admin.reel_reviews"))


@bp.route("/reel-reviews/<int:app_id>/publish", methods=["POST"])
@admin_required
def reel_reviews_publish(app_id):
    application = db.session.get(ReelReviewApplication, app_id) or abort(404)
    existing = reel_svc.published_review_for_week(application.week_key)
    if existing and (application.review is None or existing.id != application.review.id):
        flash("This week's review is already published — one review per week. "
              "Unpublish it first if you need to replace it.", "error")
        return redirect(url_for("admin.reel_reviews"))
    title = (request.form.get("title") or "").strip()[:160]
    body = (request.form.get("body") or "").strip()
    if not title:
        flash("Give the review a title.", "error")
        return redirect(url_for("admin.reel_reviews"))
    review = application.review or ReelReview(application_id=application.id)
    if application.review is None:
        db.session.add(review)
    review.title = title
    review.body = body or ""
    review.published = True
    upload = request.files.get("review_video")
    if upload and upload.filename:
        try:
            disk_name, mime, fname, _size = process_video(
                upload, current_app.config["VIDEO_STORAGE_DIR"],
                current_app.config["MAX_VIDEO_MB"] * 1024 * 1024)
        except VideoError as exc:
            flash(str(exc), "error")
            return redirect(url_for("admin.reel_reviews"))
        if review.review_disk_name:
            delete_stored(current_app.config["VIDEO_STORAGE_DIR"],
                          review.review_disk_name)
        review.review_disk_name = disk_name
        review.review_mime = mime
        review.review_filename = fname
    application.selected = True
    db.session.flush()
    from ..services.social_graph import notify_everyone
    notify_everyone(
        kind="content_hub",
        body=f"New reel review on Content Hub: “{title[:80]}”",
        url=url_for("main.videos") + "#reviews",
        actor_id=current_user.id,
        exclude_id=current_user.id,
    )
    db.session.commit()
    flash("Reel review published to the Content Hub.", "success")
    return redirect(url_for("admin.reel_reviews"))


@bp.route("/reel-reviews/review/<int:review_id>/unpublish", methods=["POST"])
@admin_required
def reel_reviews_unpublish(review_id):
    review = db.session.get(ReelReview, review_id) or abort(404)
    review.published = False
    db.session.commit()
    flash("Review hidden from the Content Hub.", "success")
    return redirect(url_for("admin.reel_reviews"))


# =============================== COACHING ====================================

@bp.route("/coaching")
@admin_required
def coaching():
    rows = (CoachingRequest.query.options(joinedload(CoachingRequest.author))
            .order_by(CoachingRequest.created_at.desc()).limit(100).all())
    return render_template("admin/coaching.html", requests=rows)


@bp.route("/coaching/<int:req_id>/status", methods=["POST"])
@admin_required
def coaching_status(req_id):
    row = db.session.get(CoachingRequest, req_id) or abort(404)
    status = (request.form.get("status") or "").strip()
    if status not in ("pending", "booked", "done", "cancelled"):
        flash("Unknown status.", "error")
    else:
        row.status = status
        db.session.commit()
        flash("Coaching request updated.", "success")
    return redirect(url_for("admin.coaching"))
