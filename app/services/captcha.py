"""Simple session math captcha for auth forms (no third-party dependency)."""
import random

from flask import session


def issue_captcha() -> str:
    """Store a fresh answer in the session; return the human-readable question."""
    a = random.randint(2, 9)
    b = random.randint(2, 9)
    session["captcha_answer"] = str(a + b)
    session["captcha_question"] = f"{a} + {b}"
    return session["captcha_question"]


def captcha_question() -> str:
    """Return the current question, issuing one if missing."""
    q = session.get("captcha_question")
    if not q or "captcha_answer" not in session:
        return issue_captcha()
    return q


def verify_captcha(answer: str | None) -> bool:
    """Check the submitted answer and rotate the challenge either way."""
    expected = session.pop("captcha_answer", None)
    session.pop("captcha_question", None)
    ok = bool(expected) and (answer or "").strip() == expected
    # always refresh so a failed attempt can't replay
    issue_captcha()
    return ok
