"""Compatibility facade for admin panel handlers."""

from admin_panel.handlers import handle_admin_callback, handle_admin_message, is_admin

__all__ = [
    "handle_admin_callback",
    "handle_admin_message",
    "is_admin",
]
