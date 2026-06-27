"""Вспомогательные утилиты."""


class _SafeFormatDict(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def format_template(template: str, **context) -> str:
    """Безопасно подставляет плейсхолдеры в текст."""
    if not template:
        return ""
    try:
        return template.format_map(_SafeFormatDict(context))
    except ValueError:
        return template


def build_user_name(user: dict | None, fallback: str = "") -> str:
    """Собирает отображаемое имя пользователя."""
    if not user:
        return fallback

    first_name = str(user.get("first_name") or "").strip()
    last_name = str(user.get("last_name") or "").strip()
    username = str(user.get("username") or "").strip()

    if first_name or last_name:
        return f"{first_name} {last_name}".strip()
    if username:
        return f"@{username}"

    user_id = user.get("user_id")
    return fallback or (str(user_id) if user_id is not None else "")


def build_user_template_context(user: dict | None, fallback: str = "") -> dict[str, str | int]:
    """Собирает контекст для подстановки пользовательских плейсхолдеров."""
    first_name = str(user.get("first_name") or "").strip() if user else ""
    last_name = str(user.get("last_name") or "").strip() if user else ""
    username = str(user.get("username") or "").strip() if user else ""
    user_id = user.get("user_id") if user else None
    fallback_name = fallback or (str(user_id) if user_id is not None else "")
    full_name = build_user_name(user, fallback=fallback_name)
    first_name_value = first_name or full_name or fallback_name

    return {
        "user_name": full_name,
        "First_name": first_name_value,
        "first_name": first_name_value,
        "last_name": last_name,
        "username": username,
        "user_id": user_id if user_id is not None else fallback_name,
    }


def user_link(name: str, user_id: int) -> str:
    """Возвращает Markdown-ссылку на профиль пользователя в MAX."""
    safe_name = name.replace("[", "").replace("]", "").replace("(", "").replace(")", "")
    return f"[{safe_name}](max://user/{user_id})"
