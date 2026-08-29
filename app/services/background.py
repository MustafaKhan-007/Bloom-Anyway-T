"""Run housekeeping off the request thread.

Some jobs — pulling recent Stripe payments, sending the 24h session reminders —
used to run inline on whatever page happened to trigger them, so one unlucky
visitor waited on a pile of API calls. They don't affect the response, so they
run behind it instead. One job of each name at a time; if it's still going, the
next request skips it rather than queueing up.
"""
import logging
import threading

from flask import current_app

from ..extensions import db

log = logging.getLogger(__name__)

_lock = threading.Lock()
_running: set[str] = set()


def run_in_background(name: str, fn, *args, **kwargs) -> bool:
    """Run ``fn`` in a daemon thread with its own app context.

    Returns True if it started, False if one is already running under this
    name (or we're in tests, where jobs run inline so results are checkable).
    """
    app = current_app._get_current_object()
    if app.config.get("TESTING"):
        try:
            fn(*args, **kwargs)
        except Exception:
            log.exception("background job %s failed", name)
            db.session.rollback()
        return True

    with _lock:
        if name in _running:
            return False
        _running.add(name)

    def _run():
        try:
            with app.app_context():
                try:
                    fn(*args, **kwargs)
                except Exception:
                    log.exception("background job %s failed", name)
                    db.session.rollback()
                finally:
                    db.session.remove()
        finally:
            with _lock:
                _running.discard(name)

    threading.Thread(target=_run, name=f"bg-{name}", daemon=True).start()
    return True
