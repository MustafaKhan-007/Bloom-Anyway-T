"""Community participation counts for My space overview."""
from __future__ import annotations

from ..extensions import db
from ..models import ForumComment, ForumPost


def community_participation_count(user) -> int:
    """Times this member showed up in community: posts + comments + check-ins."""
    if user is None or not getattr(user, "id", None):
        return 0
    posts = (db.session.query(db.func.count(ForumPost.id))
             .filter(ForumPost.user_id == user.id,
                     ForumPost.hidden.is_(False))
             .scalar()) or 0
    comments = (db.session.query(db.func.count(ForumComment.id))
                .filter(ForumComment.user_id == user.id,
                        ForumComment.hidden.is_(False))
                .scalar()) or 0
    checkins = int(getattr(user, "total_checkins", 0) or 0)
    return int(posts) + int(comments) + checkins


def participation_bar_pct(count: int) -> int:
    """Soft fill toward 20 actions = full bar."""
    return min(max(int(count or 0) * 5, 0), 100)
