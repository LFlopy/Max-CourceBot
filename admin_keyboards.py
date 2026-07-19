"""Compatibility facade for admin keyboard builders."""

from admin_panel import keyboards as _keyboards

globals().update(
    {
        name: getattr(_keyboards, name)
        for name in dir(_keyboards)
        if not name.startswith("__")
    }
)

__all__ = [
    name
    for name in dir(_keyboards)
    if not name.startswith("__")
]
