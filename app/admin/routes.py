"""Admin panel. Every route requires is_admin + recent admin activity.

Freshness is a *sliding* idle timeout: each admin action pushes the clock
forward, so day-to-day use never nags. Re-authentication is only required after
``ADMIN_IDLE_DAYS`` of no admin activity.
"""
import csv
import io
import logging
import os
from datetime import date, datetime, timedelta
from functools import wraps

from flask import (Response, abort, current_app, flash, redirect,
                   render_template, request, send_file, send_from_directory,
                   session, url_for)
from flask_login import current_user
from sqlalchemy import func
from sqlalchemy.orm import joinedload

from ..extensions import db
from ..models import (Announcement, ChallengeWaitlist, ContentReport, FaqItem, ForumComment,
                      ForumPost, MEMBERSHIPS, MEMBERSHIP_LABELS, MarketplaceListing,
                      MembershipPlan,
                      Page, Product, ProductAsset, Quote, QuoteFavorite, QuotePin,
                      ReelReview, ReelReviewApplication, SiteFeedback, Testimonial,
                      User, Video, QUOTE_CATEGORIES, utcnow)
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


@bp.before_request
def _studio_readonly_guard():
    """View-only owners may browse Studio but cannot POST/PUT/PATCH/DELETE."""
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return None
    if not current_user.is_authenticated:
        return None
    if not getattr(current_user, "is_admin", False):
        return None
    if not getattr(current_user, "admin_readonly", False):
        return None
    flash(
        "This Studio account is view-only — you can look around, but changes are locked.",
        "error",
    )
    target = request.referrer
    if not target or "/admin" not in target:
        target = url_for("admin.dashboard")
    return redirect(target)


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
        # Owner perks use effective_membership() (always Creator). Do not write
        # membership=creator here — that left demoted co-owners stuck on Creator.
        return f(*args, **kwargs)
    return wrapper


def _spotlight_candidates():
    """Current Creator-tier members (and owners) for Creator of the Month."""
    creators = (User.query.filter(
                    User.deleted_at.is_(None),
                    db.or_(User.membership == "creator", User.is_admin.is_(True)))
                .order_by(User.display_name).all())
    out = []
    for u in creators:
        # Skip demoted accounts that somehow still have a stale Creator column
        # without admin rights or a real Creator tier.
        if not u.is_admin and not u.is_creator():
            continue
        if not u.is_admin and u.membership != "creator":
            continue
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
    # Throttled Stripe pull so opening Studio isn't a multi-second API round-trip
    # every time. Manual sync remains at /admin/sync-purchases.
    from ..services import stripe_pay as pay
    from ..services.settings import get_setting
    if pay.configured():
        last_raw = (get_setting("stripe_last_sync_at") or "").strip()
        should_sync = True
        if last_raw:
            try:
                last_dt = datetime.fromisoformat(last_raw)
                should_sync = (datetime.utcnow() - last_dt).total_seconds() >= 15 * 60
            except ValueError:
                should_sync = True
        if should_sync:
            try:
                sync_info = pay.sync_recent_payments(days=60, max_pages=2)
                set_setting(
                    "stripe_last_sync_at",
                    datetime.utcnow().isoformat(timespec="seconds"),
                )
                if sync_info.get("imported"):
                    flash(
                        f"Synced {sync_info['imported']} purchase"
                        f"{'' if sync_info['imported'] == 1 else 's'} from Stripe.",
                        "success",
                    )
            except Exception:
                log.exception("dashboard: stripe purchase sync failed")
    return render_template(
        "admin/dashboard.html",
        today_quote=quotes_service.quote_for(today),
        tomorrow_quote=quotes_service.quote_for(today + timedelta(days=1)),
        cards=stats.dashboard_cards(),
        chart_signups=stats.signups_by_week(12),
        chart_purchases=stats.purchases_over_time(90),
        trending_product=stats.trending_product(7),
        most_visited=stats.most_visited(7),
        memberships=stats.membership_breakdown(),
        video_count=stats.video_count(),
        marketplace=stats.marketplace_counts(),
        member_activity=stats.member_activity(),
        showcase_perf=stats.showcase_performance(),
        recent_feedback=stats.recent_feedback(),
        support_occupancy=stats.support_occupancy(),
        founder_days=stats.founder_days_remaining(),
        challenge_waitlist=stats.challenge_waitlist_insights(),
        stripe_configured=pay.configured(),
    )


@bp.route("/sync-purchases", methods=["POST"])
@admin_required
def sync_purchases():
    """Manual pull of recent Stripe payments into Studio / My space."""
    from ..services import stripe_pay as pay
    if not pay.configured():
        flash("Add STRIPE_SECRET_KEY (and live mode) before syncing.", "error")
        return redirect(url_for("admin.dashboard"))
    try:
        result = pay.sync_recent_payments(days=90, max_pages=4)
        set_setting(
            "stripe_last_sync_at", datetime.utcnow().isoformat(timespec="seconds"))
    except Exception:
        log.exception("manual stripe sync failed")
        flash("Could not sync purchases from Stripe. Check the API key and mode.", "error")
        return redirect(url_for("admin.dashboard"))
    if not result.get("ok"):
        flash(result.get("error") or "Sync failed.", "error")
    elif result.get("imported"):
        flash(
            f"Imported {result['imported']} purchase"
            f"{'' if result['imported'] == 1 else 's'} "
            f"(checked {result.get('checked', 0)}).",
            "success",
        )
    else:
        flash(
            f"No new purchases — checked {result.get('checked', 0)} recent "
            "Stripe payment(s).",
            "info",
        )
    return redirect(url_for("admin.dashboard"))


@bp.route("/import-checkout-session", methods=["POST"])
@admin_required
def import_checkout_session():
    """Fulfill one Checkout Session by id (bypasses webhook — useful for $0 / missed deliveries)."""
    from ..services import stripe_pay as pay
    if not pay.configured():
        flash("Add STRIPE_SECRET_KEY (live mode) before importing.", "error")
        return redirect(url_for("admin.dashboard"))
    sid = (request.form.get("session_id") or "").strip()
    if not sid.startswith("cs_"):
        flash("Paste a Checkout Session id starting with cs_live_ or cs_test_.", "error")
        return redirect(url_for("admin.dashboard"))
    try:
        order = pay.fulfill_checkout_session_id(sid)
        if order is None:
            flash(
                "Could not import that session (not complete/paid, or Stripe retrieve failed). "
                "Check Render logs and that STRIPE_SECRET_KEY is the live key.",
                "error",
            )
            return redirect(url_for("admin.dashboard"))
        db.session.commit()
        flash(
            f"Imported {order.buyer_email} — {order.status} "
            f"({order.total_display()}). Buyer must use that same email in My Space.",
            "success",
        )
    except Exception as exc:
        db.session.rollback()
        log.exception("import checkout session failed: %s", sid)
        flash(f"Import failed: {exc}", "error")
    return redirect(url_for("admin.dashboard"))


# =============================== PRODUCTS ====================================

def _parse_accent(raw: str | None) -> str | None:
    """Normalize a #RRGGBB colour or return None."""
    value = (raw or "").strip()
    if len(value) == 7 and value.startswith("#"):
        try:
            int(value[1:], 16)
            return value.upper()
        except ValueError:
            return None
    return None


def _parse_price_cents(raw: str | None) -> int | None:
    text = (raw or "").strip().replace(",", "")
    if not text:
        return None
    try:
        return round(float(text) * 100)
    except ValueError:
        return None


def _apply_product_fields(product: Product, form) -> None:
    """Map studio form fields onto a Product (caller commits)."""
    from ..services.catalog import slugify_title, unique_product_slug

    title = (form.get("title") or "").strip()[:160]
    if title:
        product.title = title
    track = (form.get("track") or product.track or "healing").strip()
    product.track = track if track in ("healing", "building") else "healing"
    product.type = (form.get("type") or product.type or "guide").strip() or "guide"
    product.category_label = (form.get("category_label") or "").strip()[:80] or None
    product.badge = (form.get("badge") or "").strip()[:30] or None
    product.promise = (form.get("promise") or "").strip()[:120] or None
    product.meta_line = (form.get("meta_line") or "").strip()[:200] or None
    product.description_md = (form.get("description") or "").strip() or None
    product.audience = (form.get("audience") or "").strip() or None
    product.contents_text = (form.get("contents") or "").strip() or None

    curriculum_rows = []
    for i in range(1, 13):
        t = (form.get(f"mod{i}_title") or "").strip()
        if not t:
            continue
        curriculum_rows.append({
            "title": t[:160],
            "description": (form.get(f"mod{i}_desc") or "").strip()[:500],
        })
    product.set_curriculum(curriculum_rows)

    product.stripe_price_id = (form.get("stripe") or "").strip() or None
    price = _parse_price_cents(form.get("price"))
    if price is not None or form.get("price") is not None:
        # Allow clearing price with empty field on edit
        if (form.get("price") or "").strip() == "":
            product.price_cents = None
        elif price is not None:
            product.price_cents = price
    compare = _parse_price_cents(form.get("compare_at"))
    if (form.get("compare_at") or "").strip() == "":
        product.compare_at_cents = None
    elif compare is not None:
        product.compare_at_cents = compare

    if form.get("use_accent"):
        product.accent_color = _parse_accent(form.get("accent"))
    else:
        product.accent_color = None

    want_live = bool(form.get("live"))
    if want_live:
        blockers = product.publish_blockers()
        if blockers:
            product.status = "draft"
        else:
            product.status = "published"
    else:
        product.status = "draft"

    new_slug = (form.get("slug") or "").strip().lower()
    if new_slug:
        cleaned = slugify_title(new_slug)
        if cleaned and cleaned != product.slug:
            product.slug = unique_product_slug(cleaned, exclude_id=product.id)


@bp.route("/products")
@admin_required
def products():
    items = (Product.query
             .options(joinedload(Product.assets))
             .order_by(Product.track, Product.sort_order, Product.id).all())
    return render_template("admin/products.html", items=items)


@bp.route("/products/new", methods=["GET", "POST"])
@admin_required
def product_new():
    from ..services.catalog import unique_product_slug
    from ..services.assets import AssetError, add_asset
    from ..services.product_covers import CoverError, process_and_save as save_cover

    if request.method == "POST":
        title = (request.form.get("title") or "").strip()[:160]
        if not title:
            flash("Give the product a title.", "error")
            return redirect(url_for("admin.product_new"))
        product = Product(
            title=title,
            slug=unique_product_slug(title),
            type="guide",
            track="healing",
            status="draft",
            currency="USD",
        )
        _apply_product_fields(product, request.form)
        if not product.title:
            product.title = title
        db.session.add(product)
        db.session.flush()
        cover = request.files.get("cover")
        if cover and getattr(cover, "filename", None):
            try:
                product.cover_url = save_cover(product.id, cover)
            except CoverError as exc:
                flash(str(exc), "error")
            except Exception:
                log.exception("create product cover upload failed")
                flash("Product saved, but the cover didn’t upload.", "error")
        upload = request.files.get("asset")
        if upload and getattr(upload, "filename", None):
            try:
                add_asset(
                    product, upload,
                    title=(request.form.get("asset_title") or "").strip()[:160] or None,
                )
            except AssetError as exc:
                flash(str(exc), "error")
            except Exception:
                log.exception("create product asset upload failed")
                flash("Product saved, but the reading file didn’t upload.", "error")
        teasers = request.files.getlist("teasers")
        gallery_urls = []
        for teaser in teasers:
            if not teaser or not getattr(teaser, "filename", None):
                continue
            try:
                from ..services.product_covers import process_gallery_image
                gallery_urls.append(process_gallery_image(product.id, teaser))
            except CoverError as exc:
                flash(str(exc), "error")
            except Exception:
                log.exception("create product teaser upload failed")
        if gallery_urls:
            product.set_gallery(gallery_urls)
        blockers = product.publish_blockers() if product.status == "published" else []
        if blockers:
            product.status = "draft"
            flash(
                "Saved as draft — still need: " + ", ".join(blockers) + ".",
                "info",
            )
        db.session.commit()
        flash(f"“{product.title}” created.", "success")
        return redirect(url_for("admin.product_edit", product_id=product.id))

    blank = Product(title="", slug="", type="guide", track="healing",
                    status="draft", currency="USD")
    return render_template(
        "admin/product_form.html",
        product=blank,
        is_new=True,
        curriculum=[{"title": "", "description": ""}] * 2,
    )


@bp.route("/products/<int:product_id>/edit", methods=["GET", "POST"])
@admin_required
def product_edit(product_id):
    product = (Product.query
               .options(joinedload(Product.assets))
               .filter_by(id=product_id).first())
    if product is None:
        flash("That product was already gone.", "info")
        return redirect(url_for("admin.products"))

    if request.method == "POST":
        from ..services.product_covers import CoverError, process_and_save as save_cover

        prev_status = product.status
        _apply_product_fields(product, request.form)
        cover = request.files.get("cover")
        if cover and getattr(cover, "filename", None):
            try:
                product.cover_url = save_cover(product.id, cover)
            except CoverError as exc:
                flash(str(exc), "error")
            except Exception:
                log.exception("edit product cover upload failed")
                flash("Product saved, but the cover didn’t upload.", "error")
        blockers = product.publish_blockers() if product.status == "published" else []
        if blockers:
            product.status = "draft"
            flash(
                "Kept as draft — still need: " + ", ".join(blockers) + ".",
                "info",
            )
        elif product.status == "published" and prev_status != "published":
            flash(f"“{product.title}” is now live on Courses.", "success")
        else:
            flash("Product saved.", "success")
        db.session.commit()
        return redirect(url_for("admin.product_edit", product_id=product.id))

    curriculum = product.curriculum() or []
    while len(curriculum) < 2:
        curriculum.append({"title": "", "description": ""})
    return render_template(
        "admin/product_form.html",
        product=product,
        is_new=False,
        curriculum=curriculum,
        blockers=product.publish_blockers(),
    )


@bp.route("/products/<int:product_id>/assets", methods=["POST"])
@admin_required
def product_asset_upload(product_id):
    from ..services.assets import AssetError, add_asset

    product = db.session.get(Product, product_id)
    if product is None:
        flash("That product was already gone.", "info")
        return redirect(url_for("admin.products"))
    upload = request.files.get("asset")
    title = (request.form.get("asset_title") or "").strip()[:160] or None
    try:
        asset = add_asset(product, upload, title=title)
        db.session.commit()
        flash(f"Uploaded “{asset.display_title()}” for on-site reading.", "success")
    except AssetError as exc:
        db.session.rollback()
        flash(str(exc), "error")
    except Exception:
        db.session.rollback()
        log.exception("product asset upload failed")
        flash("Could not upload that file. Try a smaller PDF or H5P.", "error")
    return redirect(url_for("admin.product_edit", product_id=product_id))


@bp.route("/products/<int:product_id>/assets/<int:asset_id>/delete", methods=["POST"])
@admin_required
def product_asset_delete(product_id, asset_id):
    product = db.session.get(Product, product_id)
    asset = db.session.get(ProductAsset, asset_id)
    if product is None or asset is None or asset.product_id != product.id:
        flash("That file was already gone.", "info")
        return redirect(url_for("admin.products"))
    label = asset.display_title()
    db.session.delete(asset)
    db.session.commit()
    flash(f"Removed “{label}”.", "success")
    return redirect(url_for("admin.product_edit", product_id=product_id))


@bp.route("/products/<int:product_id>/cover", methods=["POST"])
@admin_required
def product_cover_upload(product_id):
    from ..services.product_covers import CoverError, clear as clear_cover, process_and_save

    product = db.session.get(Product, product_id)
    if product is None:
        flash("That product was already gone.", "info")
        return redirect(url_for("admin.products"))
    if request.form.get("clear_cover"):
        clear_cover(product.id)
        product.cover_url = None
        db.session.commit()
        flash("Cover removed — the flower default is back.", "success")
        return redirect(url_for("admin.product_edit", product_id=product_id))
    upload = request.files.get("cover")
    try:
        product.cover_url = process_and_save(product.id, upload)
        db.session.commit()
        flash("Cover image saved.", "success")
    except CoverError as exc:
        db.session.rollback()
        flash(str(exc), "error")
    except Exception:
        db.session.rollback()
        log.exception("product cover upload failed")
        flash("Could not upload that cover. Try a JPG or PNG under 8 MB.", "error")
    return redirect(url_for("admin.product_edit", product_id=product_id))


@bp.route("/products/<int:product_id>/gallery", methods=["POST"])
@admin_required
def product_gallery_upload(product_id):
    from ..services.product_covers import (
        CoverError, clear_gallery_image, process_gallery_image,
    )

    product = db.session.get(Product, product_id)
    if product is None:
        flash("That product was already gone.", "info")
        return redirect(url_for("admin.products"))

    remove_url = (request.form.get("remove_url") or "").strip()
    if remove_url:
        gallery = [u for u in product.gallery() if u != remove_url]
        product.set_gallery(gallery)
        # Best-effort file delete when URL is ours
        prefix = f"/media/product-gallery/{product.id}/"
        if remove_url.startswith(prefix):
            clear_gallery_image(product.id, remove_url[len(prefix):])
        db.session.commit()
        flash("Teaser removed.", "success")
        return redirect(url_for("admin.product_edit", product_id=product_id))

    gallery = product.gallery()
    added = 0
    for teaser in request.files.getlist("teasers"):
        if not teaser or not getattr(teaser, "filename", None):
            continue
        try:
            gallery.append(process_gallery_image(product.id, teaser))
            added += 1
        except CoverError as exc:
            flash(str(exc), "error")
        except Exception:
            log.exception("product teaser upload failed")
            flash("Could not upload one of the teaser images.", "error")
    if added:
        product.set_gallery(gallery)
        db.session.commit()
        flash(f"Added {added} teaser image{'s' if added != 1 else ''}.", "success")
    return redirect(url_for("admin.product_edit", product_id=product_id))


@bp.route("/products/<int:product_id>/delete", methods=["POST"])
@admin_required
def product_delete(product_id):
    from ..models import CourseProgress, Order, Testimonial
    from ..services.product_covers import clear as clear_cover, clear_all_gallery

    product = db.session.get(Product, product_id)
    if product is None:
        flash("That product was already gone.", "info")
        return redirect(url_for("admin.products"))
    title = product.title
    order_n = product.orders.count()

    # Keep purchase history, but drop the catalogue link so the row can go.
    if order_n:
        (Order.query.filter_by(product_id=product.id)
         .update({Order.product_id: None}, synchronize_session=False))
    (Testimonial.query.filter_by(product_id=product.id)
     .update({Testimonial.product_id: None}, synchronize_session=False))
    (CourseProgress.query.filter_by(product_id=product.id)
     .update({CourseProgress.product_id: None}, synchronize_session=False))

    clear_cover(product.id)
    clear_all_gallery(product.id)
    for asset in list(product.assets):
        db.session.delete(asset)
    db.session.delete(product)
    db.session.commit()
    if order_n:
        flash(
            f"Deleted “{title}”. {order_n} past order"
            f"{'s' if order_n != 1 else ''} stay in your records, unlinked.",
            "success",
        )
    else:
        flash(f"Deleted “{title}”.", "success")
    return redirect(url_for("admin.products"))


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


# ============================= LEGACY REDIRECTS ==============================
# Old Studio paths — keep as soft redirects so bookmarks don't 404.

@bp.route("/subscribers")
@bp.route("/subscribers/export.csv")
@admin_required
def subscribers():
    flash("Main payment totals are on the Dashboard. Full history is in Stripe.", "info")
    return redirect(url_for("admin.dashboard"))


@bp.route("/subscribers/<int:sub_id>/delete", methods=["POST"])
@admin_required
def subscriber_delete(sub_id):
    return redirect(url_for("admin.dashboard"))


@bp.route("/orders")
@bp.route("/orders/export.csv")
@admin_required
def orders():
    flash("Payment totals are on the Dashboard. Full history is in Stripe.", "info")
    return redirect(url_for("admin.dashboard"))


# =============================== SPOTLIGHT ===================================

_SPOTLIGHT_KEYS = (
    "creator_name",
    "creator_instagram",
    "creator_image_url",
    "creator_blurb",
    "reel_url",
    "reel_description",
)


@bp.route("/spotlight", methods=["GET", "POST"])
@admin_required
def spotlight():
    """Home-page Creator of the Month + Reel of the Week."""
    if request.method == "POST":
        if request.form.get("clear_spotlight_creator"):
            for key in ("creator_name", "creator_instagram", "creator_image_url",
                        "creator_blurb"):
                set_setting(key, "")
            from ..services.site_images import clear as clear_site_image
            clear_site_image("creator")
            flash("Creator of the month cleared from the home page.", "success")
            return redirect(url_for("admin.spotlight"))
        if request.form.get("clear_spotlight_reel"):
            set_setting("reel_url", "")
            set_setting("reel_description", "")
            flash("Reel of the week cleared from the home page.", "success")
            return redirect(url_for("admin.spotlight"))

        values = {key: (request.form.get(key) or "").strip()
                  for key in _SPOTLIGHT_KEYS}
        handle = instagram_handle(values.get("creator_instagram") or "")
        values["creator_instagram"] = handle
        from ..services.site_images import (SiteImageError, clear as clear_site_image,
                                            process_and_save)
        try:
            if request.form.get("clear_creator"):
                clear_site_image("creator")
                values["creator_image_url"] = ""
            creator = request.files.get("creator_file")
            if creator and creator.filename:
                values["creator_image_url"] = process_and_save("creator", creator)
        except SiteImageError as exc:
            flash(str(exc), "error")
            return redirect(url_for("admin.spotlight"))
        if handle and (not values.get("creator_image_url")
                       or not values.get("creator_blurb")):
            preview = fetch_instagram_preview(handle)
            if preview.get("image") and not values.get("creator_image_url"):
                values["creator_image_url"] = preview["image"]
            if preview.get("blurb") and not values.get("creator_blurb"):
                values["creator_blurb"] = preview["blurb"]
        for key, val in values.items():
            set_setting(key, val)
        flash("Home spotlight saved.", "success")
        return redirect(url_for("admin.spotlight"))

    values = all_settings()
    if values.get("creator_instagram"):
        h = instagram_handle(values["creator_instagram"])
        values["creator_instagram"] = f"@{h}" if h else values["creator_instagram"]
    return render_template(
        "admin/spotlight.html",
        values=values,
        spotlight=_spotlight_candidates(),
    )


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
            set_setting("announcement_url", "")
            flash("Announcement removed.", "success")
            return redirect(url_for("admin.settings"))
        if request.form.get("add_announcement"):
            body = (request.form.get("ann_body") or "").strip()[:300]
            if body:
                expires = date.today() + timedelta(days=7)  # default: 1 week
                raw = (request.form.get("ann_expires") or "").strip()
                if raw:
                    try:
                        expires = date.fromisoformat(raw)
                    except ValueError:
                        pass
                from ..services.settings import sanitize_announcement_url
                link = sanitize_announcement_url(request.form.get("ann_url"))
                db.session.add(Announcement(body=body, expires=expires, link_url=link or None))
                from ..services.social_graph import notify_everyone
                notify_everyone(
                    kind="announcement",
                    body=f"Site update: {body[:120]}",
                    url=link or url_for("main.index"),
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
                  for key in SETTING_DEFAULTS
                  if key not in _SPOTLIGHT_KEYS}
        # Site images: upload preferred; clear flags; URL fields still work.
        from ..services.site_images import (SiteImageError, clear as clear_site_image,
                                            process_and_save)
        try:
            if request.form.get("clear_portrait"):
                clear_site_image("portrait")
                values["portrait_url"] = ""
            portrait = request.files.get("portrait_file")
            if portrait and portrait.filename:
                values["portrait_url"] = process_and_save("portrait", portrait)
            if request.form.get("clear_hero"):
                clear_site_image("hero")
                values["hero_image_url"] = ""
            hero = request.files.get("hero_file")
            if hero and hero.filename:
                values["hero_image_url"] = process_and_save("hero", hero)
        except SiteImageError as exc:
            flash(str(exc), "error")
            return redirect(url_for("admin.settings"))
        # quick announcement: blank expiry defaults to one week
        if values.get("announcement_text") and not values.get("announcement_expires"):
            values["announcement_expires"] = (date.today() + timedelta(days=7)).isoformat()
        from ..services.settings import sanitize_announcement_url
        values["announcement_url"] = sanitize_announcement_url(values.get("announcement_url"))
        for key, val in values.items():
            set_setting(key, val)
        flash("Settings saved.", "success")
        return redirect(url_for("admin.settings"))
    values = all_settings()
    announcements = (Announcement.query
                     .order_by(Announcement.sort_order, Announcement.created_at.desc()).all())
    default_expires = (date.today() + timedelta(days=7)).isoformat()
    return render_template("admin/settings.html", values=values,
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
        healing_access = bool(request.form.get("healing_access"))
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
                video.healing_access = healing_access
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

def _csv_response(filename: str, header: list[str], rows: list[list]) -> Response:
    """UTF-8 CSV (with BOM) for Excel + Brevo / Mailchimp / Klaviyo imports."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(header)
    writer.writerows(rows)
    # BOM helps Excel open UTF-8 correctly; ESPs ignore it fine.
    payload = "\ufeff" + buf.getvalue()
    return Response(
        payload,
        mimetype="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


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
                           memberships=MEMBERSHIPS,
                           membership_labels=MEMBERSHIP_LABELS, q=q,
                           spotlight=_spotlight_candidates())


@bp.route("/members/export.csv")
@admin_required
def members_export_csv():
    """Email list for marketing tools (Email, First Name, Last Name, …)."""
    q = (request.args.get("q") or "").strip()
    membership = (request.args.get("membership") or "").strip().lower()
    query = User.query.filter(User.deleted_at.is_(None))
    if q:
        like = f"%{q}%"
        query = query.filter(db.or_(User.email.ilike(like),
                                    User.display_name.ilike(like)))
    if membership in MEMBERSHIPS:
        query = query.filter(User.membership == membership)
    people = query.order_by(User.created_at.desc()).all()

    rows = []
    for m in people:
        email = (m.email or "").strip().lower()
        if not email or email.endswith("@invalid.local") or "@" not in email:
            continue
        name = (m.display_name or "").strip()
        parts = name.split(None, 1) if name else []
        first = parts[0] if parts else ""
        last = parts[1] if len(parts) > 1 else ""
        tier = MEMBERSHIP_LABELS.get(m.membership, m.membership or "Free")
        joined = m.created_at.strftime("%Y-%m-%d") if m.created_at else ""
        rows.append([email, first, last, name, tier, joined])

    stamp = utcnow().strftime("%Y%m%d")
    return _csv_response(
        f"bloom-anyway-members-{stamp}.csv",
        ["Email", "First Name", "Last Name", "Full Name", "Membership", "Joined"],
        rows,
    )


@bp.route("/members/<int:user_id>/membership", methods=["POST"])
@admin_required
def set_membership(user_id):
    member = db.session.get(User, user_id) or abort(404)
    if member.is_admin:
        flash("The owner account always keeps Full Bloom access.", "info")
        return redirect(request.form.get("next") or url_for("admin.members"))
    tier = request.form.get("membership")
    if tier in MEMBERSHIPS:
        member.membership = tier
        from ..services.listings import enforce_listing_limits
        enforce_listing_limits(member)
        db.session.commit()
        flash(f"{member.public_name()} \u2192 {member.membership_label()}.", "success")
    return redirect(request.form.get("next") or url_for("admin.members"))


@bp.route("/members/<int:user_id>/remove", methods=["POST"])
@admin_required
def remove_member(user_id):
    """Soft-delete a member/user account from the Members page."""
    from ..services.privacy import close_account

    member = db.session.get(User, user_id) or abort(404)
    if member.deleted_at is not None:
        flash("That account is already removed.", "info")
        return redirect(url_for("admin.members"))
    if member.is_admin:
        flash("Studio owners can't be removed from Members.", "error")
        return redirect(url_for("admin.members"))
    name = member.public_name()
    close_account(member)
    flash(f"{name} was removed from Bloom Anyway.", "success")
    return redirect(url_for("admin.members", q=request.form.get("q") or ""))


# ======================== CHALLENGE WAITLIST =================================

@bp.route("/challenge-waitlist")
@admin_required
def challenge_waitlist():
    q = (request.args.get("q") or "").strip()
    query = ChallengeWaitlist.query
    if q:
        query = query.filter(ChallengeWaitlist.email.ilike(f"%{q}%"))
    rows = query.order_by(ChallengeWaitlist.created_at.desc()).limit(500).all()
    insights = stats.challenge_waitlist_insights()
    return render_template(
        "admin/challenge_waitlist.html",
        rows=rows,
        q=q,
        insights=insights,
    )


@bp.route("/challenge-waitlist/export.csv")
@admin_required
def challenge_waitlist_export_csv():
    """Waitlist emails for marketing imports (Email + signup date)."""
    q = (request.args.get("q") or "").strip()
    query = ChallengeWaitlist.query
    if q:
        query = query.filter(ChallengeWaitlist.email.ilike(f"%{q}%"))
    entries = query.order_by(ChallengeWaitlist.created_at.desc()).all()

    rows = []
    for row in entries:
        email = (row.email or "").strip().lower()
        if not email or "@" not in email:
            continue
        joined = row.created_at.strftime("%Y-%m-%d") if row.created_at else ""
        rows.append([email, joined, "2-Month Creator Challenge"])

    stamp = utcnow().strftime("%Y%m%d")
    return _csv_response(
        f"bloom-anyway-challenge-waitlist-{stamp}.csv",
        ["Email", "Joined", "List"],
        rows,
    )


@bp.route("/challenge-waitlist/<int:entry_id>/delete", methods=["POST"])
@admin_required
def challenge_waitlist_delete(entry_id):
    row = db.session.get(ChallengeWaitlist, entry_id) or abort(404)
    email = row.email
    db.session.delete(row)
    db.session.commit()
    flash(f"Removed {email} from the challenge waitlist.", "success")
    return redirect(url_for("admin.challenge_waitlist", q=request.form.get("q") or ""))


# =============================== OWNERS ======================================

@bp.route("/owners")
@admin_required
def owners():
    from ..services import owners as owners_svc
    return render_template(
        "admin/owners.html",
        owners=owners_svc.current_owners(),
        invites=owners_svc.invite_entries(),
        me_email=(current_user.email or "").strip().lower(),
        studio_readonly=bool(getattr(current_user, "admin_readonly", False)),
    )


@bp.route("/owners/invite", methods=["POST"])
@admin_required
def owners_invite():
    from ..services import owners as owners_svc
    role = (request.form.get("role") or "full").strip().lower()
    readonly = role in ("view", "readonly", "view-only", "view_only")
    ok, msg = owners_svc.invite(
        request.form.get("email") or "",
        actor=current_user,
        readonly=readonly,
    )
    flash(msg, "success" if ok else "error")
    return redirect(url_for("admin.owners"))


@bp.route("/owners/remove", methods=["POST"])
@admin_required
def owners_remove():
    from ..services import owners as owners_svc
    ok, msg = owners_svc.remove(request.form.get("email") or "", actor=current_user)
    flash(msg, "success" if ok else "error")
    return redirect(url_for("admin.owners"))


# ============================ MEMBERSHIP PLANS ===============================

_PLAN_DEFAULTS = {
    "healing": {"name": "Healing membership",
                "tagline": "Healing community, support, and one Showcase listing.",
                "sort_order": 1},
    "creator": {"name": "Creator membership",
                "tagline": "Building community, tips, spotlight, and Showcase.",
                "sort_order": 2},
    "full_bloom": {"name": "Full Bloom membership",
                   "tagline": "Everything in Healing and Creator.",
                   "sort_order": 3},
}


def _get_plans():
    """Return membership plans, creating any that are missing."""
    plans = {p.tier: p for p in MembershipPlan.query.all()}
    changed = False
    for tier, d in _PLAN_DEFAULTS.items():
        if tier not in plans:
            plan = MembershipPlan(tier=tier, name=d["name"], tagline=d["tagline"],
                                  sort_order=d["sort_order"])
            db.session.add(plan)
            plans[tier] = plan
            changed = True
        else:
            # Keep names/taglines fresh when still on old defaults
            pass
    if changed:
        db.session.commit()
    return [plans["healing"], plans["creator"], plans["full_bloom"]]


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
            plan.period = "month"
            plan.stripe_price_id = (request.form.get(f"{p}_stripe") or "").strip() or None
            plan.stripe_price_id_annual = (
                request.form.get(f"{p}_stripe_annual") or "").strip() or None
            plan.active = bool(request.form.get(f"{p}_active"))
            raw = (request.form.get(f"{p}_price") or "").strip().replace(",", "")
            try:
                plan.price_cents = round(float(raw) * 100) if raw else None
            except ValueError:
                plan.price_cents = plan.price_cents
            raw_y = (request.form.get(f"{p}_annual_price") or "").strip().replace(",", "")
            try:
                plan.annual_price_cents = round(float(raw_y) * 100) if raw_y else None
            except ValueError:
                plan.annual_price_cents = plan.annual_price_cents
            raw_f = (request.form.get(f"{p}_founder_price") or "").strip().replace(",", "")
            try:
                plan.founder_price_cents = round(float(raw_f) * 100) if raw_f else None
            except ValueError:
                plan.founder_price_cents = plan.founder_price_cents
            raw_fy = (request.form.get(f"{p}_founder_annual_price") or "").strip().replace(",", "")
            try:
                plan.founder_annual_price_cents = (
                    round(float(raw_fy) * 100) if raw_fy else None
                )
            except ValueError:
                plan.founder_annual_price_cents = plan.founder_annual_price_cents
        # Reject the same Stripe price on two plans — that made Creator checkouts
        # look like Full Bloom when both rows matched one order.
        seen_prices: dict[str, str] = {}
        dupes = []
        for plan in plans:
            for raw in (plan.stripe_price_id, plan.stripe_price_id_annual):
                key = (raw or "").strip()
                if not key:
                    continue
                other = seen_prices.get(key)
                if other and other != plan.tier:
                    dupes.append(f"{key} ({other} + {plan.tier})")
                else:
                    seen_prices[key] = plan.tier
        if dupes:
            db.session.rollback()
            flash(
                "Each Stripe price can only belong to one plan. Duplicates: "
                + "; ".join(dupes),
                "error",
            )
            return redirect(url_for("admin.membership_plans"))
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
        elif r.target_type == "comment":
            target = db.session.get(ForumComment, r.target_id)
            if target:
                snippet = (target.body or "")[:200]
        elif r.target_type == "user":
            target = db.session.get(User, r.target_id)
            if target:
                name = (target.public_name() or "").strip()
                handle = (target.username or "").strip()
                bits = [name] if name else []
                if handle and name.lstrip("@").lower() != handle.lower():
                    bits.append(f"@{handle}")
                bits.append(f"warnings {target.forum_warnings or 0}")
                snippet = " · ".join(bits)
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

def _member_reports(member_id: int) -> list:
    """Reports about this member (peer flags) or their posts/comments."""
    post_ids = [
        pid for (pid,) in
        db.session.query(ForumPost.id).filter_by(user_id=member_id).all()
    ]
    comment_ids = [
        cid for (cid,) in
        db.session.query(ForumComment.id).filter_by(user_id=member_id).all()
    ]
    clauses = [
        db.and_(
            ContentReport.target_type == "user",
            ContentReport.target_id == member_id,
        )
    ]
    if post_ids:
        clauses.append(db.and_(
            ContentReport.target_type == "post",
            ContentReport.target_id.in_(post_ids),
        ))
    if comment_ids:
        clauses.append(db.and_(
            ContentReport.target_type == "comment",
            ContentReport.target_id.in_(comment_ids),
        ))
    return (
        ContentReport.query.options(joinedload(ContentReport.reporter))
        .filter(db.or_(*clauses))
        .order_by(ContentReport.created_at.desc())
        .limit(30)
        .all()
    )


def _enrich_flagged_members(members: list) -> list:
    rows = []
    for member in members:
        reports = _member_reports(member.id)
        rows.append({
            "member": member,
            "reports": reports,
            "open_reports": sum(1 for r in reports if r.status == "open"),
        })
    return rows


@bp.route("/community")
@admin_required
def community():
    posts = (ForumPost.query.options(joinedload(ForumPost.category),
                                     joinedload(ForumPost.author))
             .order_by(ForumPost.created_at.desc()).limit(100).all())
    flagged_q = (
        User.query.filter(
            User.deleted_at.is_(None),
            User.is_admin.is_(False),
            db.or_(User.forum_warnings > 0, User.forum_banned.is_(True)),
        )
        .order_by(User.forum_banned.desc(), User.forum_warnings.desc())
    )
    flagged_users = flagged_q.all()

    # Include anyone with an open peer/user report even if the counter was cleared.
    seen = {u.id for u in flagged_users}
    open_flag_ids = [
        tid for (tid,) in
        db.session.query(ContentReport.target_id)
        .filter_by(target_type="user", status="open")
        .distinct()
        .all()
    ]
    for uid in open_flag_ids:
        if uid in seen:
            continue
        extra = db.session.get(User, uid)
        if extra and extra.deleted_at is None and not extra.is_admin:
            flagged_users.append(extra)
            seen.add(uid)

    return render_template(
        "admin/community.html",
        posts=posts,
        flagged=_enrich_flagged_members(flagged_users),
        warning_limit=2,
    )


@bp.route("/community/post/<int:post_id>/delete", methods=["POST"])
@admin_required
def community_delete_post(post_id):
    from ..services import forum_moderation
    post = db.session.get(ForumPost, post_id) or abort(404)
    forum_moderation.delete_post(post)
    flash("Post removed.", "success")
    return redirect(url_for("admin.community"))


@bp.route("/community/comment/<int:comment_id>/delete", methods=["POST"])
@admin_required
def community_delete_comment(comment_id):
    from ..services import forum_moderation
    comment = db.session.get(ForumComment, comment_id) or abort(404)
    forum_moderation.delete_comment(comment)
    flash("Comment removed.", "success")
    return redirect(url_for("admin.community"))


def _community_member_for_moderation(user_id: int):
    """Return a moderatable member, or None after flashing why not.

    Studio owner accounts and removed members used to abort(404), which dumped
    owners onto the public "different path" page after Community actions.
    """
    member = db.session.get(User, user_id)
    if member is None or member.deleted_at is not None:
        flash("That member isn't available anymore.", "error")
        return None
    if member.is_admin:
        flash("Studio owner accounts can't be moderated from Community.", "info")
        return None
    return member


@bp.route("/community/member/<int:user_id>/reset", methods=["POST"])
@admin_required
def community_reset_member(user_id):
    member = _community_member_for_moderation(user_id)
    if member is None:
        return redirect(url_for("admin.community"))
    member.forum_warnings = 0
    member.forum_banned = False
    # Close open peer flags so they leave the "needs a look" list.
    try:
        ContentReport.query.filter_by(
            target_type="user", target_id=member.id, status="open",
        ).update(
            {
                "status": "resolved",
                "resolved_at": utcnow(),
                "owner_note": "Cleared with fresh start",
            },
            synchronize_session=False,
        )
    except Exception:
        log.exception("Fresh-start report close failed for user %s", member.id)
        for report in ContentReport.query.filter_by(
            target_type="user", target_id=member.id, status="open",
        ).all():
            report.status = "resolved"
            report.resolved_at = utcnow()
            report.owner_note = "Cleared with fresh start"
    db.session.commit()
    flash("Fresh start given — flags cleared and posting restored.", "success")
    return redirect(url_for("admin.community"))


@bp.route("/community/member/<int:user_id>/warn", methods=["POST"])
@admin_required
def community_warn_member(user_id):
    """Send a real in-app + email warning (peer flags alone do not notify)."""
    from ..services.mailer import send_styled_email
    from ..services.social_graph import notify

    member = _community_member_for_moderation(user_id)
    if member is None:
        return redirect(url_for("admin.community"))
    if member.forum_warnings < 1:
        member.forum_warnings = 1

    body = (
        "A studio owner reviewed reports about your account and is sending "
        "this gentle warning. Please keep community spaces and support "
        "sessions kind and respectful.\n\n"
        "If this feels like a mistake, reply to this email and we'll talk it through."
    )
    notify(
        member.id,
        kind="moderation",
        body=("Studio sent you a community warning — please keep spaces kind. "
              "Reach out if this seems wrong."),
        url="/settings",
    )
    db.session.commit()
    try:
        send_styled_email(
            member.email,
            subject="A gentle reminder from Bloom Anyway",
            preview="Please keep community and support spaces kind.",
            header="A GENTLE REMINDER",
            title="Community warning",
            body=body,
            button_text="Open settings",
            button_url=url_for("main.settings", _external=True),
        )
    except Exception:
        log.exception("Community warning email failed for user %s", member.id)

    flash(f"Warning sent to {member.public_name()}.", "success")
    return redirect(url_for("admin.community"))


@bp.route("/community/member/<int:user_id>/pause", methods=["POST"])
@admin_required
def community_pause_member(user_id):
    """Pause community posting (forums). Support booking still follows membership."""
    from ..services.social_graph import notify

    member = _community_member_for_moderation(user_id)
    if member is None:
        return redirect(url_for("admin.community"))
    member.forum_banned = True
    notify(
        member.id,
        kind="moderation",
        body=("Community posting is paused on your account. "
              "You can still read; reach out if you'd like to talk it through."),
        url="/settings",
    )
    db.session.commit()
    flash(f"Posting paused for {member.public_name()}.", "success")
    return redirect(url_for("admin.community"))


@bp.route("/community/member/<int:user_id>/revoke-access", methods=["POST"])
@admin_required
def community_revoke_access(user_id):
    """Revoke membership (community + support groups) and pause forum posting."""
    from ..services import stripe_pay as pay
    from ..services.listings import enforce_listing_limits
    from ..services.social_graph import notify

    member = _community_member_for_moderation(user_id)
    if member is None:
        return redirect(url_for("admin.community"))
    if pay.configured() and member.email:
        try:
            pay.cancel_membership_subscriptions(
                member.email, at_period_end=False,
            )
        except Exception:
            log.exception("Stripe cancel failed while revoking user %s", member.id)

    member.membership = "none"
    member.forum_banned = True
    enforce_listing_limits(member)
    notify(
        member.id,
        kind="moderation",
        body=("Your membership access (community and support groups) was revoked "
              "by the studio. Reach out if you'd like to talk it through."),
        url="/membership",
    )
    db.session.commit()
    flash(
        f"Community and support access revoked for {member.public_name()}.",
        "success",
    )
    return redirect(url_for("admin.community"))


@bp.route("/community/member/<int:user_id>/remove", methods=["POST"])
@admin_required
def community_remove_member(user_id):
    """Soft-delete the account (same scrub as self-serve close account)."""
    from ..services.privacy import close_account

    member = _community_member_for_moderation(user_id)
    if member is None:
        return redirect(url_for("admin.community"))
    name = member.public_name()
    close_account(member)
    flash(f"{name} was removed from Bloom Anyway.", "success")
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


# --- support / coaching groups ----------------------------------------------

@bp.route("/support-groups")
@admin_required
def support_groups():
    from ..services import coaching_intake as intake_svc
    from ..services import support_groups as sg_svc
    sg_svc.maybe_sweep_reminders(force=True)
    stats = sg_svc.circle_stats()
    open_rows = sg_svc.open_meetings()
    past = sg_svc.recent_meetings()
    owner_tz = (current_user.timezone or "UTC").strip() or "UTC"
    from ..services.timefmt import timezone_groups, timezone_label
    tz_groups = timezone_groups(selected=owner_tz)
    selected_tz_label = timezone_label(owner_tz)
    for group in tz_groups:
        for opt in group["options"]:
            if opt.get("selected"):
                selected_tz_label = opt["label"]
                break
        else:
            continue
        break
    saman_windows = intake_svc.list_availability("saman")
    saman_intakes = intake_svc.studio_intakes("saman", limit=30)
    intake_meeting_ids = {i.meeting_id for i in saman_intakes if i.meeting_id}
    # Intake-linked 1:1s live only in the intakes panel (not duplicated below).
    open_rows = [m for m in open_rows if m.id not in intake_meeting_ids]
    seat_map = {m.id: sg_svc.meeting_seats(m) for m in open_rows + past}
    for intake in saman_intakes:
        if intake.meeting_id and intake.meeting_id not in seat_map and intake.meeting:
            seat_map[intake.meeting_id] = sg_svc.meeting_seats(intake.meeting)
    intake_rows = []
    for intake in saman_intakes:
        answers = intake_svc.answer_rows(intake)
        meeting = intake.meeting
        intake_rows.append({
            "intake": intake,
            "answers": answers,
            "member": intake.member,
            "meeting": meeting,
            "seats": (
                seat_map.get(intake.meeting_id, []) if intake.meeting_id else []
            ),
        })
    window_rows = [
        {
            "window": w,
            "tz_label": timezone_label(w.timezone),
        }
        for w in saman_windows
    ]
    return render_template(
        "admin/support_groups.html",
        circle_stats=stats,
        open_meetings=open_rows,
        past_meetings=past,
        seat_map=seat_map,
        owner_tz=owner_tz,
        pending_total=sg_svc.pending_count(),
        saman_windows=saman_windows,
        window_rows=window_rows,
        intake_rows=intake_rows,
        weekday_labels=intake_svc.WEEKDAY_LABELS,
        minutes_to_hhmm=intake_svc.minutes_to_hhmm,
        tz_groups=tz_groups,
        selected_tz_label=selected_tz_label,
    )


@bp.route("/support-groups/availability", methods=["POST"])
@admin_required
def support_groups_availability():
    from ..services import coaching_intake as intake_svc

    action = (request.form.get("action") or "add").strip().lower()
    if action == "remove":
        err = intake_svc.remove_availability(
            request.form.get("window_id", type=int) or 0,
            coach="saman",
        )
        flash(err or "Availability window removed.", "error" if err else "success")
        return redirect(url_for("admin.support_groups"))

    start = intake_svc.hhmm_to_minutes(request.form.get("start_time") or "")
    end = intake_svc.hhmm_to_minutes(request.form.get("end_time") or "")
    if start is None or end is None:
        flash("Pick a start and end time.", "error")
        return redirect(url_for("admin.support_groups"))
    tz = (request.form.get("timezone") or current_user.timezone or "UTC").strip()
    _, err = intake_svc.add_availability(
        "saman",
        weekday=request.form.get("weekday", type=int),
        start_minute=start,
        end_minute=end,
        tz_name=tz,
    )
    flash(err or "Saman availability saved.", "error" if err else "success")
    return redirect(url_for("admin.support_groups"))


@bp.route("/support-groups/form", methods=["POST"])
@admin_required
def support_groups_form():
    from ..services import support_groups as sg_svc

    kind = (request.form.get("kind") or "").strip().lower()
    tz = (request.form.get("timezone") or current_user.timezone or "UTC").strip()
    meeting, err = sg_svc.schedule_studio_session(
        current_user,
        kind=kind,
        date_s=request.form.get("meeting_date") or "",
        time_s=request.form.get("meeting_time") or "",
        tz_name=tz,
        title=request.form.get("title") or "",
        coach=request.form.get("coach") or "",
        member_email=request.form.get("member_email") or "",
    )
    if err:
        flash(err, "error")
    else:
        label = sg_svc.meeting_display_title(meeting)
        flash(
            f"{label} scheduled — Daily room ready; seated members were emailed.",
            "success",
        )
    return redirect(url_for("admin.support_groups"))


@bp.route("/support-groups/<int:meeting_id>/schedule", methods=["POST"])
@admin_required
def support_groups_schedule(meeting_id):
    from ..models import SupportGroupMeeting
    from ..services import support_groups as sg_svc
    meeting = db.session.get(SupportGroupMeeting, meeting_id) or abort(404)
    if meeting.status not in ("draft", "scheduled"):
        flash("That meeting can no longer be scheduled.", "error")
        return redirect(url_for("admin.support_groups"))
    tz = (request.form.get("timezone") or current_user.timezone or "UTC").strip()
    # Prefer separate date + time fields; fall back to legacy datetime-local.
    when = sg_svc.parse_owner_parts(
        request.form.get("meeting_date") or "",
        request.form.get("meeting_time") or "",
        tz,
    )
    if when is None:
        when = sg_svc.parse_owner_local(request.form.get("scheduled_at") or "", tz)
    err = sg_svc.schedule_meeting(
        meeting,
        scheduled_at=when,
        owner=current_user,
    )
    if err:
        flash(err, "error")
    else:
        flash(
            "Meeting scheduled — Daily room ready; members were emailed and notified.",
            "success",
        )
    return redirect(url_for("admin.support_groups"))


@bp.route("/support-groups/<int:meeting_id>/complete", methods=["POST"])
@admin_required
def support_groups_complete(meeting_id):
    from ..models import SupportGroupMeeting
    from ..services import support_groups as sg_svc
    meeting = db.session.get(SupportGroupMeeting, meeting_id) or abort(404)
    if meeting.status != "scheduled":
        flash("Only scheduled meetings can be marked complete.", "error")
    else:
        sg_svc.complete_meeting(meeting)
        flash("Marked complete.", "success")
    return redirect(url_for("admin.support_groups"))


@bp.route("/support-groups/<int:meeting_id>/cancel", methods=["POST"])
@admin_required
def support_groups_cancel(meeting_id):
    from ..models import SupportGroupMeeting
    from ..services import support_groups as sg_svc
    meeting = db.session.get(SupportGroupMeeting, meeting_id) or abort(404)
    if meeting.status not in ("draft", "scheduled"):
        flash("That meeting is already closed.", "error")
    else:
        sg_svc.cancel_meeting(meeting, owner=current_user)
        flash("Meeting cancelled.", "success")
    return redirect(url_for("admin.support_groups"))

