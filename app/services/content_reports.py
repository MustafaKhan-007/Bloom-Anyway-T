"""Light automated review for reported forum posts/comments.

Keeps the check intentionally cheap: reuse the existing profanity filter plus a
few spam / harassment heuristics. A match hides the content and notifies the
author; otherwise the report stays open for Studio review.

Peer-session member reports silently flag the user (forum_warnings++) and land
in Studio inbox without notifying the reported member.
"""
from __future__ import annotations

import re

from ..extensions import db
from ..models import (SUPPORT_REPORT_REASONS, ContentReport, ForumComment,
                      ForumPost, User, utcnow)
from .moderation import contains_profanity
from .social_graph import notify, notify_owners

# short, high-confidence phrases — not a full moderation suite
_HOSTILE = (
    "kill yourself", "kys", "go die", "you should die",
    "rape you", "i hope you die",
)
_SPAM_URL_RE = re.compile(r"https?://\S+", re.I)
_REPEAT_RE = re.compile(r"(.)\1{9,}")

_REASON_KEYS = {k for k, _ in SUPPORT_REPORT_REASONS}
_REASON_LABELS = dict(SUPPORT_REPORT_REASONS)


def review_text(text: str) -> str | None:
    """Return a short take-down reason, or None if nothing clear is found."""
    raw = text or ""
    if contains_profanity(raw):
        return "Blocked language"
    lowered = raw.lower()
    for phrase in _HOSTILE:
        if phrase in lowered:
            return "Hostile or threatening language"
    urls = _SPAM_URL_RE.findall(raw)
    if len(urls) >= 4:
        return "Spam-like link flooding"
    if _REPEAT_RE.search(raw):
        return "Spam-like repeated characters"
    letters = [c for c in raw if c.isalpha()]
    if len(letters) >= 40:
        caps = sum(1 for c in letters if c.isupper())
        if caps / len(letters) >= 0.85:
            return "Aggressive all-caps spam"
    return None


def _load_target(target_type: str, target_id: int):
    if target_type == "post":
        return db.session.get(ForumPost, target_id)
    if target_type == "comment":
        return db.session.get(ForumComment, target_id)
    if target_type == "user":
        return db.session.get(User, target_id)
    return None


def _target_text(target) -> str:
    if isinstance(target, ForumPost):
        return f"{target.title or ''}\n{target.body or ''}"
    if isinstance(target, ForumComment):
        return target.body or ""
    return ""


def _target_author_id(target) -> int | None:
    if isinstance(target, User):
        return target.id
    return getattr(target, "user_id", None)


def _target_url(target) -> str | None:
    from flask import url_for
    try:
        if isinstance(target, ForumPost):
            return url_for("forums.post", post_id=target.id)
        if isinstance(target, ForumComment) and target.post_id:
            return url_for("forums.post", post_id=target.post_id) + "#comments"
        if isinstance(target, User):
            return url_for("main.profile", user_id=target.id)
    except RuntimeError:
        pass
    return None


def _inbox_url() -> str:
    try:
        from flask import url_for
        return url_for("admin.inbox", filter="reports")
    except RuntimeError:
        return "/admin/inbox?filter=reports"


def submit_report(*, reporter, target_type: str, target_id: int,
                  note: str = "") -> tuple[ContentReport | None, str]:
    """Create a report, run the light check, optionally hide + notify.

    Returns (report, flash_message).
    """
    if target_type not in ("post", "comment"):
        return None, "That report couldn't be filed."
    target = _load_target(target_type, target_id)
    if target is None or getattr(target, "hidden", False):
        return None, "That post or comment is no longer available."
    author_id = _target_author_id(target)
    if author_id and author_id == reporter.id:
        return None, "You can't report your own post or comment."

    # one open report per reporter/target
    existing = ContentReport.query.filter_by(
        reporter_id=reporter.id, target_type=target_type, target_id=target_id,
        status="open").first()
    if existing:
        return existing, "You've already reported this — thank you."

    reason = review_text(_target_text(target))
    report = ContentReport(
        target_type=target_type,
        target_id=target_id,
        reporter_id=reporter.id,
        note=(note or "").strip()[:500],
        status="resolved" if reason else "open",
        auto_hidden=bool(reason),
        auto_reason=reason,
        resolved_at=utcnow() if reason else None,
    )
    db.session.add(report)

    what = "post" if target_type == "post" else "comment"
    inbox_url = _inbox_url()
    if reason:
        target.hidden = True
        if author_id:
            notify(
                author_id,
                kind="moderation",
                body=("A community report removed your "
                      f"{what} "
                      f"({reason.lower()}). You can reach out if this seems wrong."),
                url=_target_url(target),
            )
        notify_owners(
            kind="inbox",
            body=(f"A {what} was auto-hidden after a report "
                  f"({reason.lower()})."),
            url=inbox_url,
            actor_id=reporter.id,
        )
        db.session.commit()
        return report, "Thank you — we reviewed it and took it down."

    notify_owners(
        kind="inbox",
        body=f"New {what} report needs a look in Studio inbox.",
        url=inbox_url,
        actor_id=reporter.id,
    )
    db.session.commit()
    return report, "Thank you — the team will take a look."


def submit_member_report(
    *,
    reporter,
    user_id: int,
    reason: str,
    note: str = "",
    meeting_id: int | None = None,
    meeting_label: str = "",
) -> tuple[ContentReport | None, str]:
    """Report a peer from a support session. Silently flags the member."""
    reason_key = (reason or "").strip()
    if reason_key not in _REASON_KEYS:
        return None, "Pick a reason from the list."

    target = db.session.get(User, user_id)
    if target is None or target.deleted_at is not None:
        return None, "That member isn’t available."
    if target.id == reporter.id:
        return None, "You can’t report yourself."

    existing = ContentReport.query.filter_by(
        reporter_id=reporter.id, target_type="user", target_id=user_id,
        status="open").first()
    if existing:
        return existing, "You've already reported this member — thank you."

    extra = (note or "").strip()
    context_bits = []
    if meeting_label:
        context_bits.append(meeting_label)
    if meeting_id:
        context_bits.append(f"session #{meeting_id}")
    context = " · ".join(context_bits)
    full_note = extra
    if context:
        full_note = f"{context}\n{extra}".strip() if extra else context

    report = ContentReport(
        target_type="user",
        target_id=user_id,
        reporter_id=reporter.id,
        reason=reason_key,
        note=full_note[:500],
        status="open",
        auto_hidden=False,
        auto_reason=_REASON_LABELS.get(reason_key),
        created_at=utcnow(),
    )
    db.session.add(report)

    # Silent flag — no notification to the reported member.
    target.forum_warnings = int(target.forum_warnings or 0) + 1

    notify_owners(
        kind="inbox",
        body=(
            f"Peer session report: {_REASON_LABELS.get(reason_key, reason_key)} "
            f"— {target.public_name()} flagged."
        ),
        url=_inbox_url(),
        actor_id=reporter.id,
    )
    db.session.commit()
    return report, "Thank you — the team will take a look."


def hide_target(report: ContentReport, *, owner_note: str = "") -> bool:
    """Owner action: hide the reported content and mark resolved."""
    if report.target_type == "user":
        report.status = "resolved"
        report.resolved_at = utcnow()
        report.owner_note = (owner_note or "Member flag reviewed")[:500]
        db.session.commit()
        return True

    target = _load_target(report.target_type, report.target_id)
    if target is None:
        report.status = "resolved"
        report.resolved_at = utcnow()
        report.owner_note = (owner_note or "Target already gone")[:500]
        db.session.commit()
        return False
    target.hidden = True
    report.status = "resolved"
    report.resolved_at = utcnow()
    report.owner_note = (owner_note or "Hidden by studio")[:500]
    author_id = _target_author_id(target)
    if author_id:
        notify(
            author_id,
            kind="moderation",
            body=("A community report led to your "
                  f"{'post' if report.target_type == 'post' else 'comment'} "
                  "being taken down. Reach out if you'd like to talk it through."),
            url=_target_url(target),
        )
    db.session.commit()
    return True


def dismiss_report(report: ContentReport, *, owner_note: str = "") -> None:
    report.status = "dismissed"
    report.resolved_at = utcnow()
    report.owner_note = (owner_note or "No action needed")[:500]
    db.session.commit()
