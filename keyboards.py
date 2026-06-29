"""Все клавиатуры бота."""

from config import OFERTA_URL, PRIVACY_URL, ADMIN_IDS


def _kb(buttons: list[list[dict]]) -> dict:
    """Обёртка для inline keyboard."""
    return {
        "type": "inline_keyboard",
        "payload": {"buttons": buttons},
    }


# ── Главное меню (4 кнопки + Admin для админов) ──────────────

def main_menu(user_id: int = 0, btn: dict | None = None) -> dict:
    """Личный кабинет — основное меню пользователя.

    Кнопка «Получить бонус» убрана из главного меню (2025-07-10).
    Теперь бонус показывается сразу после покупки/активации конкретного тарифа
    через кнопку, добавляемую к клавиатуре ссылок на ресурсы.
    """
    b = btn or {}
    buttons = [
        [{"type": "callback", "text": b.get("btn_courses", "🍏 Курсы"), "payload": "courses"}],
        [{"type": "callback", "text": b.get("btn_my_subs", "📋 Мои подписки"), "payload": "my_subs"}],
        # Кнопка «Получить бонус» убрана (2025-07-10) — бонус показывается сразу после покупки
        [{"type": "callback", "text": b.get("btn_oferta", "📄 Договор оферты"), "payload": "oferta"}],
        [{"type": "callback", "text": b.get("btn_feedback", "💬 Обратная связь"), "payload": "feedback"}],
    ]
    if user_id in ADMIN_IDS:
        buttons.append([{"type": "callback", "text": "⚙️ Admin", "payload": "adm:menu"}])
    return _kb(buttons)


def start_catalog(tariffs: list[dict], user_id: int = 0, btn: dict | None = None) -> dict:
    """Каталог тарифов при /start + кнопка Личный кабинет внизу."""
    b = btn or {}
    buttons = []
    for t in tariffs:
        if t["is_free"]:
            label = f"{t['name']} - бесплатно"
        else:
            label = f"{t['name']} - {t['price']}₽"
        buttons.append([{
            "type": "callback",
            "text": label,
            "payload": f"tariff:{t['id']}",
        }])
    buttons.append([{"type": "callback", "text": b.get("btn_cabinet", "👤 Личный кабинет"), "payload": "back_main"}])
    if user_id in ADMIN_IDS:
        buttons.append([{"type": "callback", "text": "⚙️ Admin", "payload": "adm:menu"}])
    return _kb(buttons)


# ── Список тарифов ──────────────────────────────────────────

def my_subs_buttons(subscriptions: list[dict]) -> dict:
    """Кнопки подписок с ссылками на ресурсы + Назад в ЛК."""
    buttons = []
    for s in subscriptions:
        resources = s.get("resources", [])
        for res in resources:
            link = res.get("invite_link", "").strip()
            if link:
                title = res.get("chat_title") or s.get("tariff_name", "Ресурс")
                buttons.append([{"type": "link", "text": f"🔗 {title}", "url": link}])
    buttons.append([{"type": "callback", "text": "🔙 Назад", "payload": "back_main"}])
    return _kb(buttons)


def tariff_list(tariffs: list[dict]) -> dict:
    buttons = []
    for t in tariffs:
        if t["is_free"]:
            label = f"{t['name']} - бесплатно"
        else:
            label = f"{t['name']} - {t['price']}₽"
        buttons.append([{
            "type": "callback",
            "text": label,
            "payload": f"tariff:{t['id']}",
        }])
    buttons.append([{"type": "callback", "text": "🔙 Назад", "payload": "back_main"}])
    return _kb(buttons)


# ── Кнопки под описанием тарифа ──────────────────────────────

def tariff_detail_buttons(tariff_id: str, is_free: bool) -> dict:
    if is_free:
        return _kb([
            [{"type": "callback", "text": "✅ Активировать тариф", "payload": f"activate:{tariff_id}"}],
            [{"type": "callback", "text": "🔙 Назад", "payload": "back_courses"}],
        ])
    return _kb([
        [{"type": "callback", "text": "💳 Оплатить", "payload": f"pay:{tariff_id}"}],
        [{"type": "callback", "text": "🔙 Назад", "payload": "back_courses"}],
    ])


# ── Ввод промокода ───────────────────────────────────────────

def promo_input_cancel(tariff_id: int) -> dict:
    return _kb([
        [{"type": "callback", "text": "➡️ Продолжить", "payload": f"promo_skip:{tariff_id}"}],
        [{"type": "callback", "text": "🔙 Назад", "payload": f"tariff:{tariff_id}"}],
    ])


# ── Выбор способа оплаты ─────────────────────────────────────

def payment_method_list(methods: list[dict], tariff_id: int) -> dict:
    buttons = []
    for m in methods:
        buttons.append([{
            "type": "callback",
            "text": f"💳 {m['name']}",
            "payload": f"pay_method:{m['id']}",
        }])
    buttons.append([{"type": "callback", "text": "🔙 Назад", "payload": f"tariff:{tariff_id}"}])
    return _kb(buttons)


# ── Кнопка перехода к оплате + проверка ──────────────────────

def payment_created(payment_url: str, purchase_id: int, btn: dict | None = None) -> dict:
    b = btn or {}
    return _kb([
        [{"type": "link", "text": b.get("btn_pay_go", "💳 Перейти к оплате"), "url": payment_url}],
        [{"type": "callback", "text": b.get("btn_pay_check", "🔄 Проверить оплату"), "payload": f"check_pay:{purchase_id}"}],
        [{"type": "callback", "text": "🔙 Назад", "payload": "back_courses"}],
    ])


# ── Старая кнопка перехода к оплате (совместимость) ──────────

def payment_button(payment_link: str) -> dict:
    return _kb([
        [{"type": "link", "text": "💳 Перейти к оплате", "url": payment_link}],
        [{"type": "callback", "text": "🔙 Назад", "payload": "back_courses"}],
    ])


# ── Кнопка со ссылкой на канал после активации ───────────────

def channel_link_button(link: str, bonus_tariff_id: int | None = None) -> dict:
    """Клавиатура с кнопкой ссылки на канал и опционально «Получить бонус».

    bonus_tariff_id — если передан, добавляет кнопку для получения бонуса
    именно по этому тарифу (показывается сразу после покупки/активации).
    """
    buttons = [
        [{"type": "link", "text": "🔗 Ссылки для доступа", "url": link}],
        [{"type": "callback", "text": "🔙 Назад", "payload": "back_main"}],
    ]
    if bonus_tariff_id is not None:
        buttons.append([
            {"type": "callback",
             "text": "🎁 Получить бонус",
             "payload": f"get_bonus_tariff:{bonus_tariff_id}"},
        ])
    return _kb(buttons)


def resource_links_buttons(resources: list[dict], back_payload: str = "back_main",
                           bonus_tariff_id: int | None = None) -> dict:
    """Кнопки со ссылками на каждый ресурс тарифа.

    bonus_tariff_id — если передан, добавляет кнопку «Получить бонус»
    для данного конкретного тарифа (показывается сразу после покупки/активации).
    """
    buttons = []
    for res in resources:
        link = res.get("invite_link", "")
        if link:
            title = res.get("chat_title") or "Ресурс"
            buttons.append([{"type": "link", "text": f"🔗 {title}", "url": link}])
    buttons.append([{"type": "callback", "text": "🔙 Назад", "payload": back_payload}])
    if bonus_tariff_id is not None:
        buttons.append([
            {"type": "callback",
             "text": "🎁 Получить бонус",
             "payload": f"get_bonus_tariff:{bonus_tariff_id}"},
        ])
    return _kb(buttons)


# ── Согласие при /start ──────────────────────────────────────

def consent_buttons() -> dict:
    return _kb([
        [{"type": "link", "text": "📄 Договор оферты", "url": OFERTA_URL}],
        [{"type": "link", "text": "🔒 Политика конфиденциальности", "url": PRIVACY_URL}],
        [{"type": "callback", "text": "✅ Согласен(а)", "payload": "agree_terms"}],
    ])


# ── Оферта ───────────────────────────────────────────────────

def oferta_buttons() -> dict:
    return _kb([
        [{"type": "link", "text": "📄 Договор оферты", "url": OFERTA_URL}],
        [{"type": "link", "text": "🔒 Политика конфиденциальности", "url": PRIVACY_URL}],
        [{"type": "callback", "text": "🔙 Назад", "payload": "back_main"}],
    ])


# ── Обратная связь ───────────────────────────────────────────

def feedback_cancel() -> dict:
    return _kb([
        [{"type": "callback", "text": "❌ Отмена", "payload": "cancel_feedback"}],
    ])
