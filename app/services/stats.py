"""Dashboard statistics, computed from the local database only."""
from datetime import date, datetime, time, timedelta

from sqlalchemy import func
from sqlalchemy.orm import joinedload

from ..extensions import db
from ..models import (ForumPost, MarketplaceListing, PageView, SiteFeedback,
                      User, Video)
from . import support_groups as sg_svc


def _dt(day: date) -> datetime:
    return datetime.combine(day, time.min)


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
    return {
        "forum_posts": posts_30d,
        "forum_posts_24h": posts_24h,
        "engagement_pct": engagement,
        "posters_week": posters_week,
        "avg_streak": round(float(avg_streak or 0), 1),
        "new_members_week": new_week,
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
    """Recent members with plan + streak for the intelligence table."""
    rows = (User.query
            .filter(User.deleted_at.is_(None))
            .order_by(User.created_at.desc())
            .limit(limit)
            .all())
    out = []
    now = datetime.utcnow()
    for u in rows:
        streak = int(getattr(u, "current_streak", 0) or 0)
        posts = ForumPost.query.filter_by(user_id=u.id).count()
        last = getattr(u, "last_checkin_date", None)
        if isinstance(last, date) and not isinstance(last, datetime):
            last = datetime.combine(last, time.min)
        last = last or u.created_at
        if last and (now - last).days == 0:
            last_label = "Today"
        elif last and (now - last).days == 1:
            last_label = "Yesterday"
        elif last:
            last_label = f"{(now - last).days}d ago"
        else:
            last_label = "—"
        if streak >= 7 or posts >= 3:
            status, tone = "Active", "ok"
        elif streak >= 1:
            status, tone = "Cooling", "warn"
        else:
            status, tone = "At risk", "bad"
        out.append({
            "name": u.public_name(),
            "plan": u.membership_label(),
            "last_active": last_label,
            "posts": posts,
            "streak": streak,
            "status": status,
            "tone": tone,
        })
    return out


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
