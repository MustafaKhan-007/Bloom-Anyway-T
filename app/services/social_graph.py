"""@username mentions, follows, and in-app notifications."""
import re

from markupsafe import Markup, escape
from sqlalchemy import func

from ..extensions import db
from ..models import Follow, ForumPost, Notification, User, utcnow

USERNAME_RE = re.compile(r"^[a-zA-Z0-9_]{3,30}$")
MENTION_RE = re.compile(r"(?<![\w@])@([a-zA-Z0-9_]{3,30})\b")


def normalize_username(raw: str) -> str:
    return (raw or "").strip().lstrip("@").lower()


def is_valid_username(raw: str) -> bool:
    return bool(USERNAME_RE.match(normalize_username(raw)))


def allocate_username(email: str, preferred: str | None = None) -> str:
    """Pick a unique username from preferred or the email local-part."""
    base = normalize_username(preferred or "")
    if not is_valid_username(base):
        local = (email or "member").split("@", 1)[0]
        base = re.sub(r"[^a-z0-9_]", "", local.lower())[:24] or "member"
        if len(base) < 3:
            base = (base + "user")[:3]
    candidate = base
    n = 0
    while User.query.filter(func.lower(User.username) == candidate).first():
        n += 1
        suffix = str(n)
        candidate = f"{base[: 30 - len(suffix)]}{suffix}"
    return candidate


def find_mentioned_users(text: str) -> list[User]:
    handles = {normalize_username(m) for m in MENTION_RE.findall(text or "")}
    if not handles:
        return []
    users = (User.query
             .filter(func.lower(User.username).in_(handles), User.deleted_at.is_(None))
             .all())
    return users


def linkify_mentions(text: str) -> Markup:
    """Escape text, turn @handles into profile links, keep newlines as <br>."""
    if not text:
        return Markup("")
    parts = []
    last = 0
    for m in MENTION_RE.finditer(text):
        parts.append(str(escape(text[last:m.start()])))
        handle = m.group(1)
        user = (User.query
                .filter(func.lower(User.username) == handle.lower(),
                        User.deleted_at.is_(None))
                .first())
        if user:
            from flask import url_for
            href = url_for("main.profile", user_id=user.id)
            parts.append(
                f'<a class="mention" href="{href}">@{escape(user.username)}</a>'
            )
        else:
            parts.append(str(escape(m.group(0))))
        last = m.end()
    parts.append(str(escape(text[last:])))
    return Markup("".join(parts).replace("\n", "<br>\n"))


def is_following(follower: User, target: User) -> bool:
    if not follower or not target or follower.id == target.id:
        return False
    return Follow.query.filter_by(
        follower_id=follower.id, following_id=target.id).first() is not None


def follow_counts(user: User) -> tuple[int, int]:
    followers = Follow.query.filter_by(following_id=user.id).count()
    following = Follow.query.filter_by(follower_id=user.id).count()
    return followers, following


def toggle_follow(follower: User, target: User) -> bool:
    """Follow or unfollow. Returns True if now following."""
    if follower.id == target.id:
        return False
    row = Follow.query.filter_by(
        follower_id=follower.id, following_id=target.id).first()
    if row:
        db.session.delete(row)
        return False
    db.session.add(Follow(follower_id=follower.id, following_id=target.id))
    return True


def notify(user_id: int, *, kind: str, body: str, actor_id: int | None = None,
           post_id: int | None = None):
    if user_id == actor_id:
        return
    db.session.add(Notification(
        user_id=user_id, actor_id=actor_id, kind=kind,
        post_id=post_id, body=(body or "")[:300], created_at=utcnow(),
    ))


def notify_followers_of_post(author: User, post: ForumPost):
    if post.anonymous:
        return
    follower_ids = [f.follower_id for f in
                    Follow.query.filter_by(following_id=author.id).all()]
    handle = f"@{author.username}" if author.username else author.public_name()
    body = f"{handle} posted “{(post.title or '')[:80]}”"
    for fid in follower_ids:
        notify(fid, kind="follow_post", body=body,
               actor_id=author.id, post_id=post.id)


def notify_mentions(actor: User, text: str, post_id: int | None = None):
    handle = f"@{actor.username}" if actor.username else actor.public_name()
    for user in find_mentioned_users(text):
        if user.id == actor.id:
            continue
        notify(user.id, kind="mention", body=f"{handle} mentioned you",
               actor_id=actor.id, post_id=post_id)


def unread_notification_count(user: User) -> int:
    if not user:
        return 0
    return Notification.query.filter_by(user_id=user.id, read_at=None).count()
