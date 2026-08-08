"""Dashboard statistics, computed from the local database only."""
from datetime import date, datetime, time, timedelta

from sqlalchemy import func
from sqlalchemy.orm import joinedload

from ..extensions import db
from ..models import (ForumPost, MarketplaceListing, Order, PageView, Product,
                      SiteFeedback, User, Video, VisitEvent)
from . import support_groups as sg_svc


def _dt(day: date) -> datetime:
    return datetime.combine(day, time.min)


def _money(cents: int, currency: str = "USD") -> str:
    symbol = {"USD": "$", "EUR": "\u20ac", "GBP": "\u00a3"}.get(currency, currency + " ")
    return f"{symbol}{(cents or 0) / 100:,.0f}"


def payment_insights(days: int = 30) -> dict:
    """Main payment numbers for Studio (not a full ledger)."""
    start = _dt(date.today() - timedelta(days=days - 1))
    paid = Order.query.filter(Order.status == "paid", Order.created_at >= start).all()
    revenue = sum(o.total_cents or 0 for o in paid)
    count = len(paid)
    # Top products by order count in window
    top_rows = (
        db.session.query(Product.title, func.count(Order.id))
        .join(Order, Order.product_id == Product.id)
        .filter(Order.status == "paid", Order.created_at >= start)
        .group_by(Product.title)
        .order_by(func.count(Order.id).desc())
        .limit(3)
        .all()
    )
    sources = (
        db.session.query(VisitEvent.source, func.count(VisitEvent.id))
        .filter(VisitEvent.created_at >= start)
        .group_by(VisitEvent.source)
        .order_by(func.count(VisitEvent.id).desc())
        .limit(5)
        .all()
    )
    return {
        "revenue": _money(revenue) if count else None,
        "revenue_note": f"{count} paid order{'s' if count != 1 else ''} in {days} days",
        "orders_30d": count,
        "top_products": [{"title": t, "orders": n} for t, n in top_rows],
        "traffic_sources": [{"source": s, "count": n} for s, n in sources],
    }


def dashboard_cards() -> dict:
    """Community metrics shown on the Studio dashboard."""
    today = date.today()
    posts_24h = db.session.query(func.count(ForumPost.id)).filter(
        ForumPost.created_at >= datetime.utcnow() - timedelta(hours=24)
    ).scalar() or 0
    posts_30d = db.session.query(func.count(ForumPost.id)).filter(
        ForumPost.created_at >= _dt(today - timedelta(days=29))
    ).scalar() or 0
    week_start = today - timedelta(days=today.weekday())
    posters_week = db.session.query(func.count(func.distinct(ForumPost.user_id))).filter(
        ForumPost.created_at >= _dt(week_start)
    ).scalar() or 0
    active_members = db.session.query(func.count(User.id)).filter(
        User.deleted_at.is_(None),
        User.membership.in_(("healing", "creator")),
    ).scalar() or 0
    free_n = db.session.query(func.count(User.id)).filter(
        User.deleted_at.is_(None),
        User.membership == "none",
    ).scalar() or 0
    denom = max(active_members + free_n, 1)
    engagement = round(100 * posters_week / denom)
    avg_streak = db.session.query(func.avg(User.current_streak)).filter(
        User.deleted_at.is_(None),
        User.current_streak.isnot(None),
        User.current_streak > 0,
    ).scalar()
    new_week = db.session.query(func.count(User.id)).filter(
        User.deleted_at.is_(None),
        User.created_at >= _dt(today - timedelta(days=7)),
    ).scalar() or 0
    pay = payment_insights(30)
    return {
        "forum_posts": posts_30d,
        "forum_posts_24h": posts_24h,
        "engagement_pct": engagement,
        "posters_week": posters_week,
        "avg_streak": round(float(avg_streak or 0), 1),
        "new_members_week": new_week,
        "revenue": pay["revenue"],
        "revenue_note": pay["revenue_note"],
        "orders_30d": pay["orders_30d"],
        "top_products": pay["top_products"],
        "traffic_sources": pay["traffic_sources"],
    }


def signups_by_week(weeks: int = 12) -> dict:
    today = date.today()
    start = today - timedelta(weeks=weeks)
    labels, users = [], []
    for i in range(weeks):
        week_start = start + timedelta(weeks=i)
        week_end = week_start + timedelta(weeks=1)
        labels.append(week_start.isoformat())
        users.append(db.session.query(func.count(User.id)).filter(
            User.created_at >= _dt(week_start), User.created_at < _dt(week_end)
        ).scalar())
    return {"labels": labels, "users": users}


def membership_breakdown() -> dict:
    rows = dict(db.session.query(User.membership, func.count(User.id))
                .filter(User.deleted_at.is_(None)).group_by(User.membership).all())
    return {
        "none": rows.get("none", 0),
        "healing": rows.get("healing", 0),
        "creator": rows.get("creator", 0),
        "total": sum(rows.values()),
    }


def video_count() -> int:
    return db.session.query(func.count(Video.id)).scalar() or 0


def marketplace_counts() -> dict:
    active = db.session.query(func.count(MarketplaceListing.id)).filter(
        MarketplaceListing.active.is_(True)).scalar() or 0
    total = db.session.query(func.count(MarketplaceListing.id)).scalar() or 0
    return {"active": active, "total": total}


def most_visited(days: int = 7, limit: int = 10):
    start = date.today() - timedelta(days=days - 1)
    return db.session.query(
        PageView.path, func.sum(PageView.count).label("views")
    ).filter(PageView.date >= start).group_by(PageView.path).order_by(
        func.sum(PageView.count).desc()
    ).limit(limit).all()


def member_activity(limit: int = 12) -> list[dict]:
    """Recent signups + traffic arrivals for the Studio activity feed."""
    out: list[dict] = []
    now = datetime.utcnow()

    visits = (VisitEvent.query
              .order_by(VisitEvent.created_at.desc())
              .limit(max(6, limit // 2))
              .all())
    for v in visits:
        who = "Someone"
        if v.user_id and v.user:
            who = v.user.public_name()
        path = v.path or "/"
        if path == "/":
            place = "the home page"
        elif path.startswith("/courses"):
            place = "Courses & Guides"
        elif path.startswith("/membership"):
            place = "Membership"
        else:
            place = path
        out.append({
            "kind": "visit",
            "when": v.created_at,
            "name": who,
            "plan": v.source,
            "last_active": _relative(v.created_at, now),
            "posts": "—",
            "streak": "—",
            "summary": f"Viewed {place} — arrived via {v.source}",
        })

    rows = (User.query
            .filter(User.deleted_at.is_(None))
            .order_by(User.created_at.desc())
            .limit(limit)
            .all())
    for u in rows:
        streak = int(getattr(u, "current_streak", 0) or 0)
        posts = ForumPost.query.filter_by(user_id=u.id).count()
        last = getattr(u, "last_checkin_date", None)
        if isinstance(last, date) and not isinstance(last, datetime):
            last = datetime.combine(last, time.min)
        last = last or u.created_at
        out.append({
            "kind": "member",
            "when": u.created_at,
            "name": u.public_name(),
            "plan": u.membership_label(),
            "last_active": _relative(last, now),
            "posts": posts,
            "streak": streak,
            "summary": f"Joined as {u.membership_label()}",
        })

    out.sort(key=lambda r: r.get("when") or now, reverse=True)
    return out[:limit]


def _relative(when, now=None) -> str:
    now = now or datetime.utcnow()
    if not when:
        return "—"
    if isinstance(when, date) and not isinstance(when, datetime):
        when = datetime.combine(when, time.min)
    days = (now - when).days
    if days <= 0:
        return "Today"
    if days == 1:
        return "Yesterday"
    return f"{days}d ago"


def showcase_performance(limit: int = 8) -> list[dict]:
    rows = (MarketplaceListing.query
            .options(joinedload(MarketplaceListing.author))
            .filter_by(active=True)
            .order_by(MarketplaceListing.clicks.desc())
            .limit(limit)
            .all())
    out = []
    for ln in rows:
        clicks = int(ln.clicks or 0)
        # Views aren't tracked separately; approximate with clicks * 4 + 1.
        views = max(clicks * 4, clicks, 1)
        ctr = round(100 * clicks / views, 1) if views else 0
        out.append({
            "member": ln.author.public_name() if ln.author else "Member",
            "title": ln.title,
            "views": views,
            "clicks": clicks,
            "ctr": ctr,
        })
    return out


def recent_feedback(limit: int = 6) -> list[dict]:
    rows = (SiteFeedback.query
            .order_by(SiteFeedback.created_at.desc())
            .limit(limit)
            .all())
    out = []
    for f in rows:
        out.append({
            "stars": f.stars,
            "body": (f.body or "")[:180],
            "kind": f.kind,
            "when": f.created_at,
        })
    return out


def support_occupancy() -> list[dict]:
    try:
        return sg_svc.circle_stats()
    except Exception:
        return []


def founder_days_remaining() -> int | None:
    from .settings import get_setting
    raw = (get_setting("founder_price_ends") or "").strip()
    if not raw:
        return None
    try:
        end = date.fromisoformat(raw[:10])
    except ValueError:
        return None
    return max(0, (end - date.today()).days)
