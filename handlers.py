"""Compatibility facade for user-facing bot handlers."""

from user_handlers.core import _activate_purchase, handle_callback, handle_message, handle_start

__all__ = [
    "_activate_purchase",
    "handle_callback",
    "handle_message",
    "handle_start",
]
