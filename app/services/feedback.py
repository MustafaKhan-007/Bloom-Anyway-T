"""Site feedback, complaints, and error reports."""
from __future__ import annotations

import re

from flask_login import current_user

from ..extensions import db
from ..models import FEEDBACK_KINDS, SiteFeedback, utcnow

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def submit_feedback(*, kind: str, body: str, stars=None, page_path: str = "",
                    contact_email: str = "") -> tuple[SiteFeedback | None, str]:
    kind = (kind or "").strip().lower()
    if kind not in FEEDBACK_KINDS:
        return None, "Pick feedback, a complaint, or an error report."
    body = (body or "").strip()
    if len(body) < 3:
        return None, "A few words help us understand — please add a short note."
    if len(body) > 4000:
        return None, "That note is a bit long — keep it under 4000 characters."

    star_val = None
    if kind == "feedback":
        try:
            star_val = int(stars)
        except (TypeError, ValueError):
            star_val = 0
        if star_val < 1 or star_val > 5:
            return None, "Please choose a star rating from 1 to 5."

    email = (contact_email or "").strip().lower()[:255]
    if email and not _EMAIL_RE.match(email):
        return None, "That email doesn't look quite right."

    user_id = None
    if getattr(current_user, "is_authenticated", False):
        user_id = current_user.id
        email = email or None  # prefer account identity; optional contact unused

    row = SiteFeedback(
        kind=kind,
        stars=star_val,
        body=body,
        page_path=(page_path or "")[:300] or None,
        user_id=user_id,
        contact_email=email or None,
        status="new",
        created_at=utcnow(),
    )
    db.session.add(row)
    db.session.commit()
    return row, "Thank you — it's in the inbox."


def mark_reviewed(row: SiteFeedback) -> None:
    row.status = "reviewed"
    db.session.commit()
