"""Account closure / data-minimization helpers."""
from __future__ import annotations

from ..extensions import db
from ..models import ForumComment, ForumPost, User, utcnow


def close_account(user: User) -> None:
    """Soft-delete and scrub personal data so the account can't be recovered
    as the same person, while keeping forum integrity (hidden, not wiped)."""
    uid = user.id
    # Hide public community content
    ForumPost.query.filter_by(user_id=uid, hidden=False).update(
        {"hidden": True}, synchronize_session=False)
    ForumComment.query.filter_by(user_id=uid, hidden=False).update(
        {"hidden": True}, synchronize_session=False)

    user.deleted_at = utcnow()
    user.email = f"deleted+{uid}@invalid.local"
    user.password_hash = None
    user.email_verified_at = None
    user.display_name = "Former member"
    user.username = None
    user.avatar_url = None
    user.avatar_data = None
    user.avatar_mime = None
    user.avatar_anim_data = None
    user.avatar_anim_mime = None
    user.bio = None
    user.links_json = None
    user.goals_json = None
    user.timezone = None
    user.displayed_badges_json = None
    user.default_anonymous = False
    # Keep membership column for historical order linkage; no login possible.
    db.session.commit()
