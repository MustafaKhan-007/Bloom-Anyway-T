"""Weekly reel-review lottery helpers."""
from datetime import date, timedelta
import random

from ..extensions import db
from ..models import ReelReview, ReelReviewApplication


def week_monday(d: date | None = None) -> date:
    """Return the Monday that starts the ISO week containing ``d``."""
    d = d or date.today()
    return d - timedelta(days=d.weekday())


def current_week_key() -> date:
    return week_monday()


def application_for(user_id: int, week: date | None = None) -> ReelReviewApplication | None:
    week = week or current_week_key()
    return ReelReviewApplication.query.filter_by(user_id=user_id, week_key=week).first()


def week_applicants(week: date | None = None):
    week = week or current_week_key()
    # Selected winner first, then by entry time
    return (ReelReviewApplication.query
            .filter_by(week_key=week)
            .order_by(ReelReviewApplication.selected.desc(),
                      ReelReviewApplication.created_at.asc())
            .all())


def published_review_for_week(week: date | None = None) -> ReelReview | None:
    """The live Content Hub review for this draw week, if one exists."""
    week = week or current_week_key()
    return (ReelReview.query
            .join(ReelReviewApplication,
                  ReelReview.application_id == ReelReviewApplication.id)
            .filter(ReelReviewApplication.week_key == week,
                    ReelReview.published.is_(True))
            .order_by(ReelReview.created_at.desc())
            .first())


def week_is_closed(week: date | None = None) -> bool:
    """True once this week's single review has been published."""
    return published_review_for_week(week) is not None


def pick_random_applicant(week: date | None = None) -> ReelReviewApplication | None:
    """Choose one random applicant for the week and mark them selected.

    Clears prior ``selected`` flags for that week first. No-op if the week's
    review is already published (one review per week).
    """
    week = week or current_week_key()
    if week_is_closed(week):
        return None
    apps = week_applicants(week)
    if not apps:
        return None
    for a in apps:
        a.selected = False
    chosen = random.choice(apps)
    chosen.selected = True
    db.session.commit()
    return chosen


def is_instagram_reel_url(url: str) -> bool:
    u = (url or "").strip().lower()
    return ("instagram.com/" in u) and ("/reel/" in u or "/reels/" in u)
