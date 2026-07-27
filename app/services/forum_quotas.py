"""Weekly free-tier community quotas.

Free members may:
  - start 1 new post per ISO week
  - leave 5 comments/replies per ISO week
  - like infinitely

Healing and Creator members are unlimited (aside from the global rate limits).
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

from ..models import ForumComment, ForumPost


def week_monday(d: date | None = None) -> date:
    d = d or date.today()
    return d - timedelta(days=d.weekday())


def next_reset_date(d: date | None = None) -> date:
    """Monday after the current ISO week (when Free quotas refresh)."""
    return week_monday(d) + timedelta(days=7)


def next_reset_label(d: date | None = None) -> str:
    nxt = next_reset_date(d)
    return nxt.strftime("%A, %b ") + str(nxt.day)


def _week_start_utc(week: date | None = None) -> datetime:
    monday = week_monday(week)
    return datetime.combine(monday, time.min)


def free_posts_used(user_id: int, week: date | None = None) -> int:
    start = _week_start_utc(week)
    return (ForumPost.query
            .filter(ForumPost.user_id == user_id,
                    ForumPost.created_at >= start,
                    ForumPost.hidden.is_(False))
            .count())


def free_replies_used(user_id: int, week: date | None = None) -> int:
    start = _week_start_utc(week)
    return (ForumComment.query
            .filter(ForumComment.user_id == user_id,
                    ForumComment.created_at >= start,
                    ForumComment.hidden.is_(False))
            .count())


FREE_POSTS_PER_WEEK = 1
FREE_REPLIES_PER_WEEK = 5


def _post_exhausted_msg() -> str:
    when = next_reset_label()
    return (
        f"You've used this week's free post. "
        f"You can start a new conversation again on {when}, "
        f"or upgrade to Healing for unlimited posts."
    )


def _reply_exhausted_msg() -> str:
    when = next_reset_label()
    return (
        f"You've used this week's five free replies. "
        f"You can reply again on {when}, "
        f"or upgrade to Healing for unlimited replies."
    )


def can_free_post(user) -> tuple[bool, str]:
    """Return (ok, error_message). Healing+ always ok."""
    if not user or not getattr(user, "is_authenticated", False):
        return False, "Sign in to post."
    if user.is_member():
        return True, ""
    if free_posts_used(user.id) >= FREE_POSTS_PER_WEEK:
        return False, _post_exhausted_msg()
    return True, ""


def can_free_reply(user) -> tuple[bool, str]:
    if not user or not getattr(user, "is_authenticated", False):
        return False, "Sign in to reply."
    if user.is_member():
        return True, ""
    if free_replies_used(user.id) >= FREE_REPLIES_PER_WEEK:
        return False, _reply_exhausted_msg()
    return True, ""
