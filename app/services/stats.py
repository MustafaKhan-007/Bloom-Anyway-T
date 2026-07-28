"""Dashboard statistics, computed from the local database only."""
from datetime import date, datetime, time, timedelta

from sqlalchemy import func

from ..extensions import db
from ..models import ForumPost, MarketplaceListing, PageView, User, Video


def _dt(day: date) -> datetime:
    return datetime.combine(day, time.min)


def dashboard_cards() -> dict:
    """Community metrics shown on the Studio dashboard."""
    posts_30d = db.session.query(func.count(ForumPost.id)).filter(
        ForumPost.created_at >= _dt(date.today() - timedelta(days=29))
    ).scalar()
    return {"forum_posts": posts_30d}


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
