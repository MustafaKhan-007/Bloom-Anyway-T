"""Deprecated Lemon Squeezy helpers — payments now go through ``dodo``."""

from .dodo import upsert_order_from_payment as upsert_order  # noqa: F401
