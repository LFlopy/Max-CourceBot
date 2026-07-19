"""Compatibility facade for the database persistence layer."""

from persistence import postgres as _postgres

globals().update(
    {
        name: getattr(_postgres, name)
        for name in dir(_postgres)
        if not name.startswith("__")
    }
)

__all__ = [
    name
    for name in dir(_postgres)
    if not name.startswith("__")
]
