"""Клавиатуры админ-панели."""


def _kb(buttons: list[list[dict]]) -> dict:
    return {
        "type": "inline_keyboard",
        "payload": {"buttons": buttons},
    }


# ── Главное меню админки ──────────────────────────────────────

def admin_main() -> dict:
    return _kb([
        [{"type": "callback", "text": "📦 Тарифы", "payload": "adm:tariffs"}],
        [{"type": "callback", "text": "📊 Статистика", "payload": "adm:stats"}],
        [{"type": "callback", "text": "⚙️ Настройки", "payload": "adm:settings_menu"}],
        [{"type": "callback", "text": "🔙 Назад", "payload": "back_main"}],
    ])


# ── Список тарифов ────────────────────────────────────────────

def admin_tariff_list(tariffs: list[dict], show_price: bool = False) -> dict:
    buttons = []
    for t in tariffs:
        icon = "✅" if t["is_active"] else "❌"
        label = f"{icon} {t['name']}"
        if show_price:
            if t["is_free"]:
                label += " — бесплатно"
            else:
                label += f" — {t['price']}₽"
        buttons.append([{
            "type": "callback",
            "text": label,
            "payload": f"adm:tariff:{t['id']}",
        }])
    buttons.append([{"type": "callback", "text": "🔀 Изменить порядок", "payload": "adm:reorder"}])
    buttons.append([{"type": "callback", "text": "💰 Отображать цену в названии", "payload": "adm:toggle_price"}])
    buttons.append([{"type": "callback", "text": "➕ Тариф", "payload": "adm:add_tariff"}])
    buttons.append([{"type": "callback", "text": "➕ Категория", "payload": "adm:add_category"}])
    buttons.append([{"type": "callback", "text": "🔙 Назад", "payload": "adm:back"}])
    return _kb(buttons)


def admin_gift_tariff_picker(tariffs: list[dict], selected_ids: set[int]) -> dict:
    """Выбор тарифов для привязки гифт файла (чекбоксы)."""
    buttons: list[list[dict]] = []
    for t in tariffs:
        icon = "✅" if t["id"] in selected_ids else "⬜"
        buttons.append([{
            "type": "callback",
            "text": f"{icon} {t['name']}",
            "payload": f"adm:gift_toggle:{t['id']}",
        }])
    buttons.append([{"type": "callback", "text": "➡️ Далее", "payload": "adm:gift_next"}])
    buttons.append([{"type": "callback", "text": "🔙 Назад", "payload": "adm:tariffs"}])
    return _kb(buttons)


def admin_gift_wait_file() -> dict:
    return _kb([
        [{"type": "callback", "text": "🔙 Назад", "payload": "adm:gifts"}],
        [{"type": "callback", "text": "❌ Отмена", "payload": "adm:tariffs"}],
    ])


# ── Режим изменения порядка ───────────────────────────────────

def admin_reorder_list(tariffs: list[dict], selected_id: int | None = None) -> dict:
    buttons = []
    if selected_id:
        buttons.append([{"type": "callback", "text": "⬆️ Поднять", "payload": f"adm:move_up:{selected_id}"}])
    for t in tariffs:
        icon = "👉" if t["id"] == selected_id else "•"
        buttons.append([{
            "type": "callback",
            "text": f"{icon} {t['name']}",
            "payload": f"adm:sel_reorder:{t['id']}",
        }])
    if selected_id:
        buttons.append([{"type": "callback", "text": "⬇️ Опустить", "payload": f"adm:move_down:{selected_id}"}])
    buttons.append([{"type": "callback", "text": "✅ Готово", "payload": "adm:tariffs"}])
    return _kb(buttons)


# ── Создание тарифа: шаг «название» ──────────────────────────

def admin_create_cancel() -> dict:
    return _kb([
        [{"type": "callback", "text": "❌ Отмена", "payload": "adm:cancel_create"}],
    ])


# ── Создание тарифа: шаг «цена» ──────────────────────────────

def admin_create_price() -> dict:
    return _kb([
        [{"type": "callback", "text": "🆓 Бесплатно", "payload": "adm:create_free"}],
        [{"type": "callback", "text": "❌ Отмена", "payload": "adm:cancel_create"}],
    ])


# ── Создание тарифа: шаг «длительность» ──────────────────────

def _duration_buttons() -> list[list[dict]]:
    """Общие кнопки выбора продолжительности."""
    return [
        [{"type": "callback", "text": "7 дней", "payload": "adm:dur:7"}],
        [{"type": "callback", "text": "14 дней", "payload": "adm:dur:14"}],
        [{"type": "callback", "text": "30 дней", "payload": "adm:dur:30"}],
        [{"type": "callback", "text": "60 дней", "payload": "adm:dur:60"}],
        [{"type": "callback", "text": "90 дней", "payload": "adm:dur:90"}],
        [{"type": "callback", "text": "♾ Навсегда", "payload": "adm:dur:0"}],
        [{"type": "callback", "text": "🕐 Выберите часы/минуты", "payload": "adm:dur:custom"}],
    ]


def admin_create_duration() -> dict:
    buttons = _duration_buttons()
    buttons.append([{"type": "callback", "text": "❌ Отмена", "payload": "adm:cancel_create"}])
    return _kb(buttons)


def admin_edit_duration(tariff_id: int) -> dict:
    buttons = _duration_buttons()
    buttons.append([{"type": "callback", "text": "🔙 Назад", "payload": f"adm:settings:{tariff_id}"}])
    return _kb(buttons)


# ── Создание тарифа: шаг «ресурсы» ───────────────────────────

def admin_create_go_resources() -> dict:
    return _kb([
        [{"type": "callback", "text": "⚙️ Перейти к настройке ресурсов", "payload": "adm:go_resources"}],
        [{"type": "callback", "text": "❌ Отмена", "payload": "adm:cancel_create"}],
    ])


def admin_resource_picker(chats: list[dict], selected_ids: set,
                          edit_tariff_id: int | None = None) -> dict:
    buttons = []
    for c in chats:
        chat_id = c.get("chat_id")
        title = c.get("title", c.get("chat_id", "?"))
        icon = "✅" if chat_id in selected_ids else "⬜"
        buttons.append([{
            "type": "callback",
            "text": f"{icon} {title}",
            "payload": f"adm:res_toggle:{chat_id}",
        }])
    buttons.append([{"type": "callback", "text": "💾 Сохранить", "payload": "adm:res_save"}])
    if edit_tariff_id:
        buttons.append([{"type": "callback", "text": "🔙 Назад", "payload": f"adm:settings:{edit_tariff_id}"}])
    else:
        buttons.append([{"type": "callback", "text": "❌ Отмена", "payload": "adm:cancel_create"}])
    return _kb(buttons)


# ── После создания тарифа ─────────────────────────────────────

def admin_tariff_created(tariff_id: int) -> dict:
    return _kb([
        [{"type": "callback", "text": "⚙️ Управление тарифом", "payload": f"adm:settings:{tariff_id}"}],
        [{"type": "callback", "text": "🔙 Назад", "payload": "adm:tariffs"}],
    ])


# ── Настройки тарифа ──────────────────────────────────────────

def admin_tariff_settings(tariff_id: int, is_active: bool) -> dict:
    hide_text = "👁 Показать тариф" if not is_active else "🙈 Скрыть тариф"
    return _kb([
        [{"type": "callback", "text": "🖼 Добавить медиа тарифа", "payload": f"adm:set_media:{tariff_id}"}],
        [{"type": "callback", "text": "✏️ Название", "payload": f"adm:set_name:{tariff_id}"}],
        [{"type": "callback", "text": "💰 Цена", "payload": f"adm:set_price:{tariff_id}"}],
        [{"type": "callback", "text": "⏱ Продолжительность", "payload": f"adm:set_duration:{tariff_id}"}],
        [{"type": "callback", "text": "📝 Описание", "payload": f"adm:set_desc:{tariff_id}"}],
        [{"type": "callback", "text": "🔗 Ресурсы", "payload": f"adm:set_resources:{tariff_id}"}],
        [{"type": "callback", "text": "📁 Категория", "payload": f"adm:set_category:{tariff_id}"}],
        [{"type": "callback", "text": "📅 Дата начала/окончания", "payload": f"adm:set_dates:{tariff_id}"}],
        [{"type": "callback", "text": "🧾 Название в чеке", "payload": f"adm:set_check:{tariff_id}"}],
        [{"type": "callback", "text": "🎉 Текст при успешной покупке", "payload": f"adm:set_success:{tariff_id}"}],
        [{"type": "callback", "text": "👥 Группа разрешённых", "payload": f"adm:set_allowed:{tariff_id}"}],
        [{"type": "callback", "text": "🎁 Бонусный файл", "payload": f"adm:tariff_gifts:{tariff_id}"}],
        [{"type": "callback", "text": "🛒 Ссылка на покупку", "payload": f"adm:buy_link:{tariff_id}"}],
        [{"type": "callback", "text": "💾 Сохранить", "payload": f"adm:save_settings:{tariff_id}"}],
        [{"type": "callback", "text": hide_text, "payload": f"adm:toggle_active:{tariff_id}"}],
        [{"type": "callback", "text": "🗑 Удалить", "payload": f"adm:delete:{tariff_id}"}],
        [{"type": "callback", "text": "🔙 Назад", "payload": "adm:tariffs"}],
    ])


# ── Бонусные файлы тарифа ─────────────────────────────────────

def admin_tariff_gifts_menu(tariff_id: int) -> dict:
    return _kb([
        [{"type": "callback", "text": "➕ Добавить бонусный файл", "payload": f"adm:tariff_gift_add:{tariff_id}"}],
        [{"type": "callback", "text": "🗑 Удалить бонусный файл", "payload": f"adm:tariff_gift_del:{tariff_id}"}],
        [{"type": "callback", "text": "🔙 Назад", "payload": f"adm:settings:{tariff_id}"}],
    ])


def admin_tariff_gift_wait_file(tariff_id: int) -> dict:
    return _kb([
        [{"type": "callback", "text": "🔙 Назад", "payload": f"adm:tariff_gifts:{tariff_id}"}],
    ])


def admin_tariff_gift_delete_list(gifts: list[dict], tariff_id: int) -> dict:
    buttons = []
    for g in gifts:
        name = g.get("file_name") or f"Файл #{g['id']}"
        date_str = g["created_at"].strftime("%d.%m.%Y") if g.get("created_at") else ""
        label = f"🗑 {name}" + (f" ({date_str})" if date_str else "")
        buttons.append([{
            "type": "callback",
            "text": label,
            "payload": f"adm:tariff_gift_del_confirm:{g['id']}:{tariff_id}",
        }])
    buttons.append([{"type": "callback", "text": "🔙 Назад", "payload": f"adm:tariff_gifts:{tariff_id}"}])
    return _kb(buttons)


# ── Настройка цен ─────────────────────────────────────────────

def admin_price_settings(tariff_id: int) -> dict:
    return _kb([
        [{"type": "callback", "text": "💰 Стандартная цена", "payload": f"adm:ep_std:{tariff_id}"}],
        [{"type": "callback", "text": "💸 Старая цена", "payload": f"adm:ep_old:{tariff_id}"}],
        [{"type": "callback", "text": "🔄 Цена продления", "payload": f"adm:ep_renew:{tariff_id}"}],
        [{"type": "callback", "text": "🔄 Цена продления активной", "payload": f"adm:ep_active:{tariff_id}"}],
        [{"type": "callback", "text": "🔙 Назад", "payload": f"adm:settings:{tariff_id}"}],
    ])


# ── Настройка дат ─────────────────────────────────────────────

def admin_date_settings(tariff_id: int) -> dict:
    return _kb([
        [{"type": "callback", "text": "📅 Дата начала тарифа", "payload": f"adm:ed_start:{tariff_id}"}],
        [{"type": "callback", "text": "📅 Дата конца тарифа", "payload": f"adm:ed_end:{tariff_id}"}],
        [{"type": "callback", "text": "🔙 Назад", "payload": f"adm:settings:{tariff_id}"}],
    ])


# ── Ввод даты ─────────────────────────────────────────────────

def admin_date_input_back(tariff_id: int) -> dict:
    return _kb([
        [{"type": "callback", "text": "🔙 Назад", "payload": f"adm:set_dates:{tariff_id}"}],
    ])


# ── Подтверждение удаления ────────────────────────────────────

def admin_confirm_delete(tariff_id: int) -> dict:
    return _kb([
        [{"type": "callback", "text": "⚠️ Да, удалить", "payload": f"adm:confirm_del:{tariff_id}"}],
        [{"type": "callback", "text": "🔙 Отмена", "payload": f"adm:settings:{tariff_id}"}],
    ])


# ── Простая кнопка «Назад» к настройкам ───────────────────────

def admin_back_to_settings(tariff_id: int) -> dict:
    return _kb([
        [{"type": "callback", "text": "🔙 Назад", "payload": f"adm:settings:{tariff_id}"}],
    ])


# ── Настройки бота ──────────────────────────────────────────────

def admin_bot_settings() -> dict:
    return _kb([
        [{"type": "callback", "text": "👥 Подписчики", "payload": "adm:subscribers"}],
        [{"type": "callback", "text": "📨 Рассылка", "payload": "adm:broadcast"}],
        [{"type": "callback", "text": "📱 Сбор контактов", "payload": "adm:collect_contacts"}],
        [{"type": "callback", "text": "📋 Ресурсы", "payload": "adm:manage_resources"}],
        [{"type": "callback", "text": "💳 Способы оплаты", "payload": "adm:payment_methods"}],
        [{"type": "callback", "text": "✏️ Редактирование", "payload": "adm:editing_menu"}],
        [{"type": "callback", "text": "🎟 Промокоды", "payload": "adm:promo_menu"}],
        [{"type": "callback", "text": "🔙 Назад", "payload": "adm:menu"}],
    ])


def admin_editing_menu() -> dict:
    """Меню редактирования."""
    return _kb([
        [{"type": "callback", "text": "✏️ Ответы от бота", "payload": "adm:bot_texts"}],
        [{"type": "callback", "text": "🔤 Кнопки", "payload": "adm:button_texts"}],
        [{"type": "callback", "text": "📝 Описания", "payload": "adm:desc_texts"}],
        [{"type": "callback", "text": "🔙 Назад", "payload": "adm:settings_menu"}],
    ])


def admin_button_texts_list(labels: dict) -> dict:
    """Список кнопок ЛК для редактирования."""
    buttons = []
    for key, label in labels.items():
        buttons.append([{
            "type": "callback",
            "text": f"✏️ {label}",
            "payload": f"adm:edit_btn:{key}",
        }])
    buttons.append([{"type": "callback", "text": "🔙 Назад", "payload": "adm:editing_menu"}])
    return _kb(buttons)


def admin_desc_texts_list(labels: dict) -> dict:
    """Список описаний для редактирования."""
    buttons = []
    for key, label in labels.items():
        buttons.append([{
            "type": "callback",
            "text": f"✏️ {label}",
            "payload": f"adm:edit_desc:{key}",
        }])
    buttons.append([{"type": "callback", "text": "🔙 Назад", "payload": "adm:editing_menu"}])
    return _kb(buttons)


def admin_edit_btn_back() -> dict:
    return _kb([
        [{"type": "callback", "text": "🔙 Назад", "payload": "adm:button_texts"}],
    ])


def admin_edit_desc_back() -> dict:
    return _kb([
        [{"type": "callback", "text": "🔙 Назад", "payload": "adm:desc_texts"}],
    ])


# ── Подписчики ──────────────────────────────────────────────────

def admin_subscribers() -> dict:
    return _kb([
        [{"type": "callback", "text": "🔍 Поиск по ID", "payload": "adm:sub_search_id"}],
        [{"type": "callback", "text": "📋 Список подписчиков", "payload": "adm:sub_list"}],
        [{"type": "callback", "text": "📋 Список не продливших", "payload": "adm:sub_expired"}],
        [{"type": "callback", "text": "📊 Таблица пользователей", "payload": "adm:sub_table"}],
        [{"type": "callback", "text": "🎁 Выдать подписку", "payload": "adm:sub_grant"}],
        [{"type": "callback", "text": "✏️ Изменить срок подписки", "payload": "adm:sub_change_term"}],
        [{"type": "callback", "text": "🔄 Передать подписку", "payload": "adm:sub_transfer"}],
        [{"type": "callback", "text": "🔄 Продлить подписки", "payload": "adm:sub_renew"}],
        [{"type": "callback", "text": "🚫 Обнулить подписку", "payload": "adm:sub_revoke"}],
        [{"type": "callback", "text": "👤 Профиль пользователя", "payload": "adm:sub_profile"}],
        [{"type": "callback", "text": "🔙 Назад", "payload": "adm:settings_menu"}],
    ])


def admin_resources_list(chats: list[dict], usage: dict[int, list[str]]) -> dict:
    """Список ресурсов (чатов) с кнопкой удаления.
    usage = {chat_id: [tariff_name, ...]} — какие тарифы используют ресурс."""
    buttons = []
    for c in chats:
        cid = c.get("chat_id")
        title = c.get("title", c.get("chat_id", "?"))
        count = len(usage.get(cid, []))
        label = f"🗑 {title}"
        if count:
            label += f" ({count} тариф.)"
        buttons.append([{
            "type": "callback",
            "text": label,
            "payload": f"adm:res_del:{cid}",
        }])
    if not chats:
        buttons.append([{"type": "callback", "text": "Ресурсов нет", "payload": "adm:manage_resources"}])
    buttons.append([{"type": "callback", "text": "🔙 Назад", "payload": "adm:settings_menu"}])
    return _kb(buttons)


def admin_confirm_res_delete(chat_id: int) -> dict:
    return _kb([
        [{"type": "callback", "text": "⚠️ Да, удалить", "payload": f"adm:res_del_confirm:{chat_id}"}],
        [{"type": "callback", "text": "🔙 Отмена", "payload": "adm:manage_resources"}],
    ])


def admin_back_subscribers() -> dict:
    return _kb([
        [{"type": "callback", "text": "🔙 Назад", "payload": "adm:subscribers"}],
    ])


# ── Рассылка ────────────────────────────────────────────────────

def admin_broadcast_groups() -> dict:
    return _kb([
        [{"type": "callback", "text": "👥 Всем пользователям", "payload": "adm:bc_all"}],
        [{"type": "callback", "text": "✅ Оплатили тариф", "payload": "adm:bc_paid"}],
        [{"type": "callback", "text": "🚫 Без подписки", "payload": "adm:bc_no_sub"}],
        [{"type": "callback", "text": "💸 Нет платных подписок", "payload": "adm:bc_no_paid"}],
        [{"type": "callback", "text": "⏳ Вызвал оплату, но не оплатил тариф", "payload": "adm:bc_pending"}],
        [{"type": "callback", "text": "📦 Определённый тариф", "payload": "adm:bc_tariff"}],
        [{"type": "callback", "text": "👥 Всем кроме тарифа", "payload": "adm:bc_all_except"}],
        [{"type": "callback", "text": "🔙 Назад", "payload": "adm:settings_menu"}],
    ])


def admin_broadcast_excluded_tariff_list(tariffs: list[dict], selected_ids: set[int]) -> dict:
    """Выбор тарифов, ПОДПИСЧИКАМ КОТОРЫХ не будет отправлена рассылка."""
    buttons = []
    for t in tariffs:
        icon = "✅" if t["id"] in selected_ids else "⬜"
        buttons.append([{
            "type": "callback",
            "text": f"{icon} {t['name']}",
            "payload": f"adm:bc_excluded_toggle:{t['id']}",
        }])
    if selected_ids:
        buttons.append([{"type": "callback", "text": "➡️ Далее (отправить текст)", "payload": "adm:bc_excluded_next"}])
    else:
        buttons.append([{"type": "callback", "text": "⚠️ Выберите хотя бы один тариф для исключения", "payload": "adm:bc_all_except"}])
    buttons.append([{"type": "callback", "text": "🔙 Назад", "payload": "adm:broadcast"}])
    return _kb(buttons)


def admin_broadcast_tariff_list(tariffs: list[dict]) -> dict:
    buttons = []
    for t in tariffs:
        buttons.append([{
            "type": "callback",
            "text": t["name"],
            "payload": f"adm:bc_tariff_pick:{t['id']}",
        }])
    buttons.append([{"type": "callback", "text": "🔙 Назад", "payload": "adm:broadcast"}])
    return _kb(buttons)


def admin_broadcast_cancel() -> dict:
    return _kb([
        [{"type": "callback", "text": "❌ Отмена", "payload": "adm:broadcast"}],
    ])


def admin_broadcast_button_picker(tariffs: list[dict], added_tariff_ids: set[int] | None = None) -> dict:
    """Выбор тарифа для кнопки в рассылке."""
    added = added_tariff_ids or set()
    buttons = []
    for t in tariffs:
        if t.get("is_active") and t["id"] not in added:
            buttons.append([{
                "type": "callback",
                "text": t["name"],
                "payload": f"adm:bc_btn_tariff:{t['id']}",
            }])
    if not buttons:
        buttons.append([{"type": "callback", "text": "Все тарифы уже добавлены", "payload": "adm:bc_add_btn_disabled"}])
    buttons.append([{"type": "callback", "text": "🔙 Назад", "payload": "adm:bc_buttons_menu"}])
    return _kb(buttons)


# ── Профиль пользователя ────────────────────────────────────────

def admin_user_profile(target_user_id: int) -> dict:
    return _kb([
        [{"type": "callback", "text": "✉️ Написать пользователю", "payload": f"adm:msg_user:{target_user_id}"}],
        [{"type": "callback", "text": "🧾 Таблица платежей", "payload": f"adm:pay_table:{target_user_id}"}],
        [{"type": "callback", "text": "📋 Таблица подписок", "payload": f"adm:sub_table_user:{target_user_id}"}],
        [{"type": "callback", "text": "🔙 Назад", "payload": "adm:subscribers"}],
    ])


# ── Выдать подписку: список тарифов ─────────────────────────────

def admin_grant_tariff_list(tariffs: list[dict]) -> dict:
    buttons = []
    for t in tariffs:
        buttons.append([{
            "type": "callback",
            "text": t["name"],
            "payload": f"adm:grant_pick:{t['id']}",
        }])
    buttons.append([{"type": "callback", "text": "🔙 Назад", "payload": "adm:subscribers"}])
    return _kb(buttons)


# ── Обнулить подписку: список тарифов ────────────────────────────

def admin_revoke_tariff_list(tariffs: list[dict]) -> dict:
    buttons = []
    for t in tariffs:
        buttons.append([{
            "type": "callback",
            "text": t["name"],
            "payload": f"adm:revoke_pick:{t['id']}",
        }])
    buttons.append([{"type": "callback", "text": "🔙 Назад", "payload": "adm:subscribers"}])
    return _kb(buttons)


# ── Передать подписку: список тарифов ────────────────────────────

def admin_transfer_tariff_list(tariffs: list[dict]) -> dict:
    buttons = []
    for t in tariffs:
        buttons.append([{
            "type": "callback",
            "text": t["name"],
            "payload": f"adm:transfer_pick:{t['id']}",
        }])
    buttons.append([{"type": "callback", "text": "🔙 Назад", "payload": "adm:subscribers"}])
    return _kb(buttons)


# ── Кнопки под сообщением обратной связи (для админа) ──────────

def admin_feedback_actions(target_user_id: int) -> dict:
    return _kb([
        [{"type": "callback", "text": "✉️ Ответить", "payload": f"adm:reply_feedback:{target_user_id}"}],
        [{"type": "callback", "text": "🚫 Забанить пользователя", "payload": f"adm:ban_user:{target_user_id}"}],
    ])


def admin_cancel_feedback_reply() -> dict:
    return _kb([
        [{"type": "callback", "text": "❌ Отмена", "payload": "adm:cancel_feedback_reply"}],
    ])


# ── Ответы от бота ────────────────────────────────────────────────

def admin_bot_texts_list(labels: dict) -> dict:
    """labels = {key: label_name}"""
    buttons = []
    for key, label in labels.items():
        buttons.append([{
            "type": "callback",
            "text": f"✏️ {label}",
            "payload": f"adm:edit_text:{key}",
        }])
    buttons.append([{"type": "callback", "text": "🔙 Назад", "payload": "adm:editing_menu"}])
    return _kb(buttons)


def admin_bot_text_back() -> dict:
    return _kb([
        [{"type": "callback", "text": "🔙 Назад", "payload": "adm:editing_menu"}],
    ])


# ── Промокоды ──────────────────────────────────────────────────────

def admin_promo_menu() -> dict:
    return _kb([
        [{"type": "callback", "text": "🎟 Общие промокоды", "payload": "adm:promo_general"}],
        [{"type": "callback", "text": "📨 Промокоды из рассылок", "payload": "adm:promo_broadcast"}],
        [{"type": "callback", "text": "🔗 Промокоды активационных ссылок", "payload": "adm:promo_activation"}],
        [{"type": "callback", "text": "📁 Создать группу промокодов", "payload": "adm:promo_create_group"}],
        [{"type": "callback", "text": "➕ Создать промокод", "payload": "adm:promo_create"}],
        [{"type": "callback", "text": "🔙 Назад", "payload": "adm:settings_menu"}],
    ])


def admin_promo_back() -> dict:
    return _kb([
        [{"type": "callback", "text": "🔙 Назад", "payload": "adm:promo_menu"}],
    ])


def admin_promo_list(promos: list[dict]) -> dict:
    buttons = []
    for p in promos:
        buttons.append([{
            "type": "callback",
            "text": f"🎟 {p['code']} (-{p['discount_percent']}%)",
            "payload": f"adm:promo_open:{p['id']}",
        }])
    buttons.append([{"type": "callback", "text": "🔙 Назад", "payload": "adm:promo_menu"}])
    return _kb(buttons)


def admin_promo_created(promo_id: int) -> dict:
    return _kb([
        [{"type": "callback", "text": "⚙️ Открыть промокод", "payload": f"adm:promo_open:{promo_id}"}],
        [{"type": "callback", "text": "🔙 Назад", "payload": "adm:promo_menu"}],
    ])


def admin_promo_detail(promo_id: int) -> dict:
    return _kb([
        [{"type": "callback", "text": "📦 Разрешённые тарифы", "payload": f"adm:promo_tariffs:{promo_id}"}],
        [{"type": "callback", "text": "🔢 Изменить кол-во активаций", "payload": f"adm:promo_edit_max:{promo_id}"}],
        [{"type": "callback", "text": "👤 Изменить кол-во активаций на чел.", "payload": f"adm:promo_edit_per_user:{promo_id}"}],
        [{"type": "callback", "text": "👥 Изменить группу разрешённых", "payload": f"adm:promo_edit_group:{promo_id}"}],
        [{"type": "callback", "text": "⏱ Изменить срок действия", "payload": f"adm:promo_edit_expiry:{promo_id}"}],
        [{"type": "callback", "text": "📋 Список разрешённых пользователей", "payload": f"adm:promo_allowed_users:{promo_id}"}],
        [{"type": "callback", "text": "📊 Список активаций", "payload": f"adm:promo_activations:{promo_id}"}],
        [{"type": "callback", "text": "🗑 Удалить", "payload": f"adm:promo_delete:{promo_id}"}],
        [{"type": "callback", "text": "🔙 Назад", "payload": "adm:promo_menu"}],
    ])


def admin_tariff_allowed_picker(tariffs: list[dict], selected_ids: set, tariff_id: int) -> dict:
    """Пикер тарифов для «Группы разрешённых» — список тарифов-чекбоксов."""
    buttons = []
    for t in tariffs:
        if t["id"] == tariff_id:
            continue  # не показываем сам тариф
        icon = "✅" if t["id"] in selected_ids else "⬜"
        buttons.append([{
            "type": "callback",
            "text": f"{icon} {t['name']}",
            "payload": f"adm:allowed_toggle:{tariff_id}:{t['id']}",
        }])
    buttons.append([{"type": "callback", "text": "💾 Сохранить", "payload": f"adm:allowed_save:{tariff_id}"}])
    buttons.append([{"type": "callback", "text": "🔙 Назад", "payload": f"adm:settings:{tariff_id}"}])
    return _kb(buttons)


def admin_promo_tariff_picker(tariffs: list[dict], selected_ids: set, promo_id: int) -> dict:
    buttons = []
    for t in tariffs:
        icon = "✅" if t["id"] in selected_ids else "⬜"
        buttons.append([{
            "type": "callback",
            "text": f"{icon} {t['name']}",
            "payload": f"adm:promo_toggle_t:{promo_id}:{t['id']}",
        }])
    buttons.append([{"type": "callback", "text": "💾 Сохранить", "payload": f"adm:promo_save_t:{promo_id}"}])
    buttons.append([{"type": "callback", "text": "🔙 Назад", "payload": f"adm:promo_open:{promo_id}"}])
    return _kb(buttons)


def admin_promo_confirm_delete(promo_id: int) -> dict:
    return _kb([
        [{"type": "callback", "text": "⚠️ Да, удалить", "payload": f"adm:promo_confirm_del:{promo_id}"}],
        [{"type": "callback", "text": "🔙 Отмена", "payload": f"adm:promo_open:{promo_id}"}],
    ])


def admin_promo_back_to_detail(promo_id: int) -> dict:
    return _kb([
        [{"type": "callback", "text": "🔙 Назад", "payload": f"adm:promo_open:{promo_id}"}],
    ])


# ── Способы оплаты ────────────────────────────────────────────────

def admin_payment_methods_list(methods: list[dict]) -> dict:
    buttons = []
    for m in methods:
        icon = "✅" if m["is_active"] else "❌"
        buttons.append([{
            "type": "callback",
            "text": f"{icon} {m['name']} ({m['provider']})",
            "payload": f"adm:pay_detail:{m['id']}",
        }])
    buttons.append([{"type": "callback", "text": "➕ Добавить способ оплаты", "payload": "adm:add_pay_method"}])
    buttons.append([{"type": "callback", "text": "🔙 Назад", "payload": "adm:settings_menu"}])
    return _kb(buttons)


def admin_payment_provider_list(providers: dict[str, str]) -> dict:
    """providers = {key: display_name}"""
    buttons = []
    for key, name in providers.items():
        buttons.append([{
            "type": "callback",
            "text": name,
            "payload": f"adm:pay_provider:{key}",
        }])
    buttons.append([{"type": "callback", "text": "🔙 Назад", "payload": "adm:payment_methods"}])
    return _kb(buttons)


def admin_payment_detail(method_id: int, is_active: bool) -> dict:
    toggle_text = "❌ Выключить" if is_active else "✅ Включить"
    return _kb([
        [{"type": "callback", "text": toggle_text, "payload": f"adm:toggle_pay:{method_id}"}],
        [{"type": "callback", "text": "🗑 Удалить", "payload": f"adm:del_pay:{method_id}"}],
        [{"type": "callback", "text": "🔙 Назад", "payload": "adm:payment_methods"}],
    ])


def admin_payment_cancel() -> dict:
    return _kb([
        [{"type": "callback", "text": "❌ Отмена", "payload": "adm:payment_methods"}],
    ])


def admin_confirm_pay_delete(method_id: int) -> dict:
    return _kb([
        [{"type": "callback", "text": "⚠️ Да, удалить", "payload": f"adm:del_pay_confirm:{method_id}"}],
        [{"type": "callback", "text": "🔙 Отмена", "payload": f"adm:pay_detail:{method_id}"}],
    ])


# ── Добавление кнопок к рассылке ────────────────────────────────

def admin_broadcast_add_buttons() -> dict:
    """Первый выбор: какие кнопки добавить к рассылке."""
    return _kb([
        [{"type": "callback", "text": "🔗 Сторонняя ссылка", "payload": "adm:bc_add_btns:yes"}],
        [{"type": "callback", "text": "💰 Кнопка тарифа", "payload": "adm:bc_add_btns:tariff"}],
        [{"type": "callback", "text": "📨 Без кнопки", "payload": "adm:bc_add_btns:no"}],
    ])


def admin_broadcast_button_list(buttons_data: list[dict], can_add_more: bool = True) -> dict:
    """Список добавленных кнопок: можно добавить ещё или отправить рассылку."""
    buttons = []
    if can_add_more:
        buttons.append([{"type": "callback", "text": "➕ Сторонняя ссылка", "payload": "adm:bc_add_btn"}])
        buttons.append([{"type": "callback", "text": "➕ Кнопка тарифа", "payload": "adm:bc_add_btns:tariff"}])
    else:
        buttons.append([{"type": "callback", "text": "➕ Максимум 5 кнопок", "payload": "adm:bc_add_btn_disabled"}])
    buttons.append([{"type": "callback", "text": "✅ Отправить рассылку", "payload": "adm:bc_send_with_btns"}])
    buttons.append([{"type": "callback", "text": "❌ Отмена", "payload": "adm:broadcast"}])

    return _kb(buttons)


def admin_broadcast_button_format_help() -> dict:
    """Подсказка по формату кнопок."""
    return _kb([
        [{"type": "callback", "text": "🔙 Назад", "payload": "adm:broadcast"}],
    ])