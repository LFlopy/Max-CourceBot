"""Обработчики событий."""

from datetime import datetime, timedelta
import re
from max_client import MaxBot
from config import ADMIN_IDS, WEBHOOK_BASE_URL
import keyboards as kb
import database as db
import admin_keyboards as akb
from admin_handlers import handle_admin_callback, handle_admin_message
from fsm import set_state, get_state, clear_state, user_states
import payments


# ── Форматирование продолжительности курса ───────────────────

_MONTHS_RU = {
    1: "января", 2: "февраля", 3: "марта", 4: "апреля",
    5: "мая", 6: "июня", 7: "июля", 8: "августа",
    9: "сентября", 10: "октября", 11: "ноября", 12: "декабря",
}


def _format_russian_date(dt) -> str:
    return f"{dt.day} {_MONTHS_RU[dt.month]} {dt.year}"


def _days_word(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return "день"
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return "дня"
    return "дней"


def _format_course_duration(tariff: dict, expires_at=None) -> str:
    """Строка о продолжительности/окончании курса для показа пользователю.

    Для марафонов (end_date): 'Заканчивается: 21 апреля 2025 в 21:00'
    Для самостоятельных (duration_days):
      - без expires_at: 'Курс продолжительностью 89 дней'
      - с expires_at:   'Доступ до: 15 июня 2025'
    """
    end_date = tariff.get("end_date")
    duration_days = tariff.get("duration_days")
    if end_date:
        date_str = _format_russian_date(end_date)
        time_str = end_date.strftime("%H:%M")
        return f"Заканчивается: {date_str} в {time_str}"
    if duration_days:
        if expires_at:
            return f"Доступ до: {_format_russian_date(expires_at)}"
        return f"Курс продолжительностью {duration_days} {_days_word(duration_days)}"
    return ""


# ── Тексты (оферта — не редактируется через бота) ────────────

OFERTA_TEXT = (
    "ОФЕРТА И ДОГОВОР НА ПРОХОЖДЕНИЕ КУРСОВ.\n\n"
    "Индивидуальный предприниматель предлагает лицам, полностью "
    "оплатившим любую программу курсов, заключить Договор оферты "
    "на следующих условиях 👇"
)


# ── Вспомогательные ─────────────────────────────────────────

async def _calc_price(user_id: int, tariff: dict) -> float:
    """Рассчитывает цену с учётом продления."""
    base = float(tariff["price"])
    status = await db.get_user_tariff_status(user_id, tariff["id"])
    if status == "active" and tariff.get("active_renewal_price"):
        base = float(tariff["active_renewal_price"])
    elif status == "expired" and tariff.get("renewal_price"):
        base = float(tariff["renewal_price"])
    return base


async def _validate_promo(code: str, user_id: int, tariff_id: int) -> tuple[dict | None, str]:
    """Проверяет промокод. Возвращает (promo, error_msg)."""
    promo = await db.get_promo_by_code(code)
    if not promo:
        return None, "❌ Промокод не найден."
    if promo.get("expires_at") and promo["expires_at"] < datetime.now():
        return None, "❌ Промокод истёк."
    if promo["max_activations"] > 0:
        used = await db.count_promo_activations(promo["id"])
        if used >= promo["max_activations"]:
            return None, "❌ Промокод исчерпан."
    user_used = await db.count_user_promo_activations(promo["id"], user_id)
    if user_used >= promo["max_per_user"]:
        return None, "❌ Вы уже использовали этот промокод."
    allowed = promo.get("allowed_tariffs")
    if allowed:
        allowed_ids = {int(x) for x in allowed.split(",") if x.strip()}
        if tariff_id not in allowed_ids:
            return None, "❌ Промокод не действует для этого тарифа."
    return promo, ""


def _parse_duration_to_minutes(text: str) -> int | None:
    s = (text or "").strip().lower()
    if not s:
        return None

    m = re.search(r"(\d+)\s*(ч|час|часа|часов|h)\b", s)
    if m:
        return int(m.group(1)) * 60

    m = re.search(r"(\d+)\s*(м|мин|минута|минуты|минут|m)\b", s)
    if m:
        return int(m.group(1))

    if re.fullmatch(r"\d+", s):
        return int(s)

    return None


async def _activate_purchase(bot: MaxBot, purchase: dict):
    """Активирует покупку: добавляет в ресурсы, уведомляет."""
    user_id = purchase["user_id"]
    tariff_id = purchase["tariff_id"]

    # Берём длительность из тарифа
    tariff_data = await db.get_tariff(tariff_id)
    expires_at = None
    if tariff_data:
        # Если у тарифа есть end_date — подписка действует до него
        end_date = tariff_data.get("end_date")
        if end_date:
            expires_at = end_date
        else:
            duration_minutes = tariff_data.get("duration_minutes")
            duration_days = tariff_data.get("duration_days")
            if duration_minutes and duration_minutes > 0:
                expires_at = datetime.now() + timedelta(minutes=duration_minutes)
            elif duration_days and duration_days > 0:
                expires_at = datetime.now() + timedelta(days=duration_days)
            else:
                # фолбэк для старых тарифов: duration_text вроде "10м/2ч"
                dm = _parse_duration_to_minutes(tariff_data.get("duration_text") or "")
                if dm and dm > 0:
                    expires_at = datetime.now() + timedelta(minutes=dm)

    await db.confirm_purchase(purchase["id"], expires_at=expires_at)

    # Добавляем в ресурсы тарифа
    resources = await db.get_tariff_resources(tariff_id)
    for res in resources:
        await bot.add_chat_member(res["chat_id"], [user_id])

    # Записываем активацию промокода (paid=True)
    if purchase.get("promo_id"):
        await db.add_promo_activation(
            purchase["promo_id"], user_id, tariff_id, paid=True,
        )

    # Уведомляем пользователя
    success_text = await db.get_bot_text("payment_success")
    duration_str = _format_course_duration(tariff_data, expires_at)
    if duration_str:
        success_text = f"{success_text}\n\n⏰ {duration_str}"
    await bot.send_message(user_id, success_text)

    # Уведомляем администраторов о новой подписке
    user_data = await db.get_user(user_id)
    full_name = f"{user_data['first_name']} {user_data['last_name']}".strip() if user_data else str(user_id)

    promo_text = "-"
    if purchase.get("promo_id"):
        promo = await db.get_promo(purchase["promo_id"])
        if promo:
            promo_text = promo["code"]

    res_list = "\n".join(f"• {r.get('chat_title') or r['chat_id']}" for r in resources) if resources else "—"

    duration_str = "бессрочно"
    if expires_at:
        duration_str = f"до {expires_at.strftime('%d.%m.%Y')}"
    elif tariff_data:
        dur_text = tariff_data.get("duration_text")
        if dur_text:
            duration_str = dur_text

    tariff_price = float(tariff_data["price"]) if tariff_data else 0
    price_paid = float(purchase.get("price_paid") or 0)

    admin_text = (
        f"Новая подписка.\n\n"
        f"Пользователь: {full_name}\n"
        f"ID: {user_id}\n"
        f"Тариф: {tariff_data['name'] if tariff_data else '—'}\n"
        f"Цена тарифа: {tariff_price:.0f}₽\n"
        f"Промокод применил: {promo_text}\n"
        f"Итоговая сумма оплаты: {price_paid:.0f}₽\n\n"
        f"Список ресурсов:\n{res_list}\n\n"
        f"Срок подписки: {duration_str}"
    )
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, admin_text)
        except Exception:
            pass

    # Уведомляем о вступлении в каждый ресурс
    for res in resources:
        chat_title = res.get("chat_title") or str(res["chat_id"])
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(
                    admin_id,
                    f"Пользователь {full_name}\n"
                    f"ID: {user_id}\n\n"
                    f"Вступил в {chat_title}",
                )
            except Exception:
                pass

    # Отправляем ссылки на ресурсы
    if resources:
        links_text = await db.get_bot_text("activation_links")
        resources_with_links = [r for r in resources if r.get("invite_link")]
        if resources_with_links:
            await bot.send_message(
                user_id,
                links_text,
                keyboard=kb.resource_links_buttons(resources_with_links),
            )
        else:
            # Фолбэк на channel_link тарифа
            tariff = await db.get_tariff(tariff_id)
            channel_link = tariff.get("channel_link") if tariff else None
            if channel_link:
                await bot.send_message(
                    user_id,
                    links_text,
                    keyboard=kb.channel_link_button(channel_link),
                )
            else:
                res_names = [r.get("chat_title") or str(r["chat_id"]) for r in resources]
                await bot.send_message(
                    user_id,
                    links_text + "\n" + "\n".join(f"• {n}" for n in res_names),
                )

    btn = await db.get_button_texts()
    await bot.send_message(user_id, "Выберите действие:", keyboard=kb.main_menu(user_id, btn=btn))


async def _do_create_payment(bot: MaxBot, user_id: int, tariff_id: int,
                             final_price: float, promo_id: int | None,
                             btn: dict, send_fn):
    """Создаёт платёж через первый активный метод и отправляет инвойс.
    send_fn(text, keyboard) — либо reply (callback), либо bot.send_message (FSM)."""
    tariff = await db.get_tariff(tariff_id)
    if not tariff:
        await send_fn("❌ Ошибка. Попробуйте снова.", kb.main_menu(user_id, btn=btn))
        return

    methods = await db.list_payment_methods(active_only=True)
    if not methods:
        await send_fn("❌ Нет доступных способов оплаты. Обратитесь к администратору.",
                      kb.main_menu(user_id, btn=btn))
        return
    method = methods[0]

    webhook_url = f"{WEBHOOK_BASE_URL}/prodamus/webhook" if WEBHOOK_BASE_URL else ""
    provider = payments.get_provider(
        method["provider"], method["shop_id"], method["secret_key"],
        webhook_url=webhook_url,
    )
    if not provider:
        await send_fn("❌ Платёжная система недоступна.", kb.main_menu(user_id, btn=btn))
        return

    result = await provider.create_payment(
        amount=final_price,
        description=f"Оплата: {tariff['name']}",
        metadata={"user_id": user_id, "tariff_id": tariff_id},
    )
    if not result:
        await send_fn("❌ Не удалось создать платёж. Попробуйте снова.",
                      kb.main_menu(user_id, btn=btn))
        return

    await db.add_user_log(user_id, f"Создан платёж {result['payment_id']}")
    purchase = await db.create_paid_purchase(
        user_id=user_id,
        tariff_id=tariff_id,
        price_paid=final_price,
        payment_id=result["payment_id"],
        payment_method_id=method["id"],
        promo_id=promo_id,
        original_price=float(tariff["price"]),
    )

    clear_state(user_id)
    await db.add_user_log(user_id, "Перешёл к оплате")

    user_data = await db.get_user(user_id)
    full_name = f"{user_data['first_name']} {user_data['last_name']}".strip() if user_data else str(user_id)
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                f"Пользователь {full_name}\n"
                f"ID: {user_id}\n"
                f"Вызвал оплату тарифа {tariff['name']}\n"
                f"Способ оплаты {method['name']}\n"
                f"Сумма: {final_price:.0f}₽",
            )
        except Exception:
            pass

    invoice_text = await db.get_bot_text("payment_invoice")
    await send_fn(
        invoice_text.format(
            tariff_name=tariff["name"],
            price=f"{final_price:.0f}",
            method_name=method["name"],
        ),
        kb.payment_created(result["payment_url"], purchase["id"]),
    )


# ── Хэндлеры ────────────────────────────────────────────────

async def handle_start(bot: MaxBot, chat_id: int, sender: dict):
    """Команда /start или bot_started."""
    user_id = int(sender.get("user_id", 0))
    if not user_id:
        return
    clear_state(user_id)

    first_name = sender.get("first_name", "")
    last_name = sender.get("last_name", "")
    # bot_started от MAX шлёт "name" вместо first_name/last_name
    if not first_name and not last_name:
        full = sender.get("name", "")
        parts = full.split(" ", 1)
        first_name = parts[0] if parts else ""
        last_name = parts[1] if len(parts) > 1 else ""

    # Проверяем, есть ли пользователь ДО вставки
    user_exists = await db.get_user(user_id)
    is_new = user_exists is None

    print(f"[USER] id={user_id} is_new={is_new} name={first_name!r} {last_name!r}")

    await db.upsert_user(
        user_id,
        first_name=first_name,
        last_name=last_name,
        username=sender.get("username", ""),
    )

    # Логируем
    await db.add_user_log(user_id, "Впервые зашёл в бота" if is_new else "Вызвал /start")

    # Уведомляем админов о новом пользователе
    if is_new:
        full_name = f"{first_name} {last_name}".strip() or "—"
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(
                    admin_id,
                    f"🆕 Новый пользователь:\n{full_name}\n"
                    f"ID: {user_id}",
                )
            except Exception:
                pass

    # Приветствие
    await bot.send_message(chat_id, await db.get_bot_text("welcome"))

    # Каталог тарифов + кнопка Личный кабинет
    btn = await db.get_button_texts()
    tariffs = await db.list_tariffs()
    active = [t for t in tariffs if t["is_active"]]
    user_tariff_ids = await db.get_active_tariff_ids(user_id)
    visible = db.filter_tariffs_by_allowed_group(active, user_tariff_ids)
    visible = [t for t in visible if t["id"] not in user_tariff_ids]

    catalog_text = await db.get_bot_text("desc_catalog")
    await bot.send_message(
        chat_id, catalog_text,
        keyboard=kb.start_catalog(visible, user_id, btn=btn),
    )


async def handle_callback(bot: MaxBot, update: dict):
    """Обработка нажатий inline-кнопок."""
    callback = update.get("callback", {})
    # message лежит рядом с callback на верхнем уровне update, НЕ внутри callback
    msg = update.get("message", {})

    callback_id = callback.get("callback_id", "")
    payload = callback.get("payload", "")
    sender = callback.get("user", callback.get("sender", {}))
    user_id = int(sender.get("user_id", 0))

    body = msg.get("body", {})
    message_id = body.get("mid", "")

    recipient = msg.get("recipient", {})
    chat_id = int(recipient.get("chat_id") or user_id)

    print(f"  [callback] callback_id={callback_id!r} message_id={message_id!r} chat_id={chat_id}")

    await bot.answer_callback(callback_id)

    # ── Админ-callback-и (adm:*) ─────────────────────────
    if payload.startswith("adm:"):
        await handle_admin_callback(bot, update)
        return

    # Загружаем тексты кнопок ЛК
    btn = await db.get_button_texts()

    async def reply(text: str, keyboard=None):
        ok = await bot.edit_message(message_id, text, keyboard=keyboard)
        if not ok:
            await bot.send_message(chat_id, text, keyboard=keyboard)

    # ── Главное меню ─────────────────────────────────────
    if payload == "back_main":
        clear_state(user_id)
        cabinet_text = await db.get_bot_text("desc_cabinet")
        await reply(cabinet_text, keyboard=kb.main_menu(user_id, btn=btn))

    elif payload == "get_bonus":
        user_tariff_ids = await db.get_active_tariff_ids(user_id)
        gifts = await db.get_gift_files_for_tariffs(list(user_tariff_ids))
        if not gifts:
            await reply("Пока для вас нет бонусов", keyboard=kb.main_menu(user_id, btn=btn))
            return
        await reply("Вот ваш бонус 👇", keyboard=kb.main_menu(user_id, btn=btn))
        seen_tokens: set[str] = set()
        for g in gifts:
            token = g.get("file_token") or ""
            if not token or token in seen_tokens:
                continue
            seen_tokens.add(token)
            await bot.send_file_token(user_id, token, text="")

    # ── Курсы стройности ─────────────────────────────────
    elif payload == "courses" or payload == "back_courses":
        clear_state(user_id)
        tariffs = await db.list_tariffs()
        active = [t for t in tariffs if t["is_active"]]
        user_tariff_ids = await db.get_active_tariff_ids(user_id)
        visible = db.filter_tariffs_by_allowed_group(active, user_tariff_ids)
        # Убираем тарифы, на которые уже есть активная подписка
        visible = [t for t in visible if t["id"] not in user_tariff_ids]
        await reply(await db.get_bot_text("tariff_selection"), keyboard=kb.tariff_list(visible))

    # ── Выбор тарифа ─────────────────────────────────────
    elif payload.startswith("tariff:"):
        clear_state(user_id)
        tariff_id = int(payload.split(":", 1)[1])
        tariff = await db.get_tariff(tariff_id)
        if not tariff:
            return
        # Проверяем, нет ли уже активной подписки
        user_tariff_ids = await db.get_active_tariff_ids(user_id)
        if tariff_id in user_tariff_ids:
            await reply("✅ У вас уже есть активная подписка на этот тариф.", keyboard=kb.main_menu(user_id, btn=btn))
            return
        if tariff["is_free"]:
            price_str = "бесплатно"
        elif tariff.get("old_price"):
            price_str = f"~~{tariff['old_price']}₽~~ **{tariff['price']}₽**"
        else:
            price_str = f"**{tariff['price']}₽**"
        duration_str = _format_course_duration(tariff)
        duration_line = f"\n⏰ {duration_str}" if duration_str else ""
        text = (
            f"📌 **{tariff['name']}**\n"
            f"💰 Цена: {price_str}"
            f"{duration_line}\n\n"
            f"{tariff.get('description') or ''}"
        )
        await reply(
            text.strip(),
            keyboard=kb.tariff_detail_buttons(tariff_id, tariff["is_free"]),
        )

    # ── Оплатить → ввод промокода или продолжить ─────────
    elif payload.startswith("pay:"):
        tariff_id = int(payload.split(":", 1)[1])
        tariff = await db.get_tariff(tariff_id)
        if not tariff:
            return
        user_tariff_ids = await db.get_active_tariff_ids(user_id)
        if tariff_id in user_tariff_ids:
            await reply("✅ У вас уже есть активная подписка на этот тариф.", keyboard=kb.main_menu(user_id, btn=btn))
            return
        price = await _calc_price(user_id, tariff)
        await db.add_user_log(user_id, f"Вызвал оплату тарифа «{tariff['name']}»")
        set_state(user_id, "waiting_promo", tariff_id=tariff_id, base_price=price)
        promo_text = await db.get_bot_text("promo_activation")
        await reply(
            promo_text.format(Название=tariff['name'], сумма=f"{price:.0f}₽"),
            keyboard=kb.promo_input_cancel(tariff_id),
        )

    # ── Продолжить без промокода → создать платёж ────────
    elif payload.startswith("promo_skip:"):
        tariff_id = int(payload.split(":", 1)[1])
        state_data = user_states.get(user_id, {})
        base_price = state_data.get("base_price", 0)
        tariff_tmp = await db.get_tariff(tariff_id)
        if not base_price:
            base_price = await _calc_price(user_id, tariff_tmp) if tariff_tmp else 0
        clear_state(user_id)
        if tariff_tmp and tariff_tmp.get("payment_link"):
            pay_kb = {"type": "inline_keyboard", "payload": {"buttons": [[
                {"type": "link", "text": "💳 Перейти к оплате", "url": tariff_tmp["payment_link"]}
            ]]}}
            await reply(f"💳 Для оплаты тарифа **{tariff_tmp['name']}** перейдите по ссылке:", keyboard=pay_kb)
            await db.add_user_log(user_id, f"Вызвал оплату тарифа «{tariff_tmp['name']}»")
            user_data = await db.get_user(user_id)
            full_name = f"{user_data['first_name']} {user_data['last_name']}".strip() if user_data else str(user_id)
            for admin_id in ADMIN_IDS:
                try:
                    await bot.send_message(
                        admin_id,
                        f"Пользователь {full_name}\n"
                        f"ID: {user_id}\n"
                        f"Вызвал оплату тарифа {tariff_tmp['name']}\n"
                        f"Способ оплаты: внешняя ссылка\n"
                        f"Сумма: {base_price:.0f}₽",
                    )
                except Exception:
                    pass
        else:
            await _do_create_payment(bot, user_id, tariff_id, base_price, None, btn, reply)

    # ── Выбрал способ оплаты → создать платёж (устаревший путь) ──
    elif payload.startswith("pay_method:"):
        method_id = int(payload.split(":", 1)[1])
        state_data = user_states.get(user_id, {})
        tariff_id = state_data.get("tariff_id")
        final_price = state_data.get("final_price", 0)
        promo_id = state_data.get("promo_id")

        if not tariff_id or not final_price:
            await reply("❌ Ошибка. Попробуйте оплатить заново.", keyboard=kb.main_menu(user_id, btn=btn))
            return

        tariff = await db.get_tariff(tariff_id)
        method = await db.get_payment_method(method_id)
        if not tariff or not method:
            await reply("❌ Ошибка. Попробуйте снова.", keyboard=kb.main_menu(user_id, btn=btn))
            return

        await db.add_user_log(user_id, f"Выбрал платёжный метод «{method['name']}»")

        webhook_url = f"{WEBHOOK_BASE_URL}/prodamus/webhook" if WEBHOOK_BASE_URL else ""
        provider = payments.get_provider(method["provider"], method["shop_id"], method["secret_key"],
                                         webhook_url=webhook_url)
        if not provider:
            await reply("❌ Платёжная система недоступна.", keyboard=kb.main_menu(user_id, btn=btn))
            return

        description = f"Оплата: {tariff['name']}"
        result = await provider.create_payment(
            amount=final_price,
            description=description,
            metadata={"user_id": user_id, "tariff_id": tariff_id},
        )

        if not result:
            await reply("❌ Не удалось создать платёж. Попробуйте снова.",
                        keyboard=kb.main_menu(user_id, btn=btn))
            return

        await db.add_user_log(user_id, f"Создан платёж {result['payment_id']}")

        # Сохраняем покупку
        original_price = float(tariff["price"])
        purchase = await db.create_paid_purchase(
            user_id=user_id,
            tariff_id=tariff_id,
            price_paid=final_price,
            payment_id=result["payment_id"],
            payment_method_id=method_id,
            promo_id=promo_id,
            original_price=original_price,
        )

        clear_state(user_id)

        await db.add_user_log(user_id, "Перешёл к оплате")

        # Уведомляем админов о начале оплаты
        user_data = await db.get_user(user_id)
        full_name = f"{user_data['first_name']} {user_data['last_name']}".strip() if user_data else str(user_id)
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(
                    admin_id,
                    f"Пользователь {full_name}\n"
                    f"ID: {user_id}\n"
                    f"Вызвал оплату тарифа {tariff['name']}\n"
                    f"Способ оплаты {method['name']}\n"
                    f"Сумма: {final_price:.0f}₽",
                )
            except Exception:
                pass

        invoice_text = await db.get_bot_text("payment_invoice")
        await reply(
            invoice_text.format(
                tariff_name=tariff["name"],
                price=f"{final_price:.0f}",
                method_name=method["name"],
            ),
            keyboard=kb.payment_created(result["payment_url"], purchase["id"], btn=btn),
        )

    # ── Проверить оплату вручную ─────────────────────────
    elif payload.startswith("check_pay:"):
        purchase_id = int(payload.split(":", 1)[1])
        purchase = await db.get_purchase(purchase_id)

        if not purchase:
            await reply("❌ Платёж не найден.", keyboard=kb.main_menu(user_id, btn=btn))
            return

        if purchase["status"] == "active":
            await reply("✅ Оплата уже подтверждена!", keyboard=kb.main_menu(user_id, btn=btn))
            return

        if purchase["status"] != "pending":
            await reply("❌ Платёж отменён или истёк.", keyboard=kb.main_menu(user_id, btn=btn))
            return

        method = await db.get_payment_method(purchase["payment_method_id"])
        if not method or not purchase.get("payment_id"):
            processing_text = await db.get_bot_text("payment_processing")
            await reply(processing_text,
                        keyboard=kb.payment_created("https://max.ru", purchase_id, btn=btn))
            return

        provider = payments.get_provider(method["provider"], method["shop_id"], method["secret_key"])
        if not provider:
            await reply("⏳ Проверка недоступна. Подождите.",
                        keyboard=kb.payment_created("https://max.ru", purchase_id, btn=btn))
            return

        status = await provider.check_payment(purchase["payment_id"])

        if status == "succeeded":
            await db.add_user_log(user_id, "Оплатил")
            await _activate_purchase(bot, purchase)
        elif status == "canceled":
            await db.add_user_log(user_id, "Не оплатил (отмена)")
            await db.cancel_purchase(purchase_id)
            failed_text = await db.get_bot_text("payment_failed")
            await reply(
                failed_text,
                keyboard=kb.main_menu(user_id, btn=btn),
            )
        else:
            processing_text = await db.get_bot_text("payment_processing")
            await reply(
                processing_text,
                keyboard=kb.payment_created("https://max.ru", purchase_id, btn=btn),
            )

    # ── Активация бесплатного тарифа ─────────────────────
    elif payload.startswith("activate:"):
        tariff_id = int(payload.split(":", 1)[1])
        tariff = await db.get_tariff(tariff_id)
        if not tariff:
            return
        user_tariff_ids = await db.get_active_tariff_ids(user_id)
        if tariff_id in user_tariff_ids:
            await reply("✅ У вас уже есть активная подписка на этот тариф.", keyboard=kb.main_menu(user_id, btn=btn))
            return

        await db.upsert_user(user_id)

        # Вычисляем expires_at из длительности тарифа
        free_expires = None
        end_date = tariff.get("end_date")
        if end_date:
            free_expires = end_date
        else:
            dm = tariff.get("duration_minutes")
            dd = tariff.get("duration_days")
            if dm and dm > 0:
                free_expires = datetime.now() + timedelta(minutes=dm)
            elif dd and dd > 0:
                free_expires = datetime.now() + timedelta(days=dd)
            else:
                dm2 = _parse_duration_to_minutes(tariff.get("duration_text") or "")
                if dm2 and dm2 > 0:
                    free_expires = datetime.now() + timedelta(minutes=dm2)

        purchase = await db.create_purchase(
            user_id, tariff_id, price_paid=0, is_free=True, expires_at=free_expires,
        )

        # Добавляем в ресурсы
        resources = await db.get_tariff_resources(tariff_id)
        _fn = f"{sender.get('first_name', '')} {sender.get('last_name', '')}".strip() or str(user_id)
        for res in resources:
            await bot.add_chat_member(res["chat_id"], [user_id])
            chat_title = res.get("chat_title") or str(res["chat_id"])
            for admin_id in ADMIN_IDS:
                try:
                    await bot.send_message(
                        admin_id,
                        f"Пользователь {_fn}\n"
                        f"ID: {user_id}\n\n"
                        f"Вступил в {chat_title}",
                    )
                except Exception:
                    pass

        resources_with_links = [r for r in resources if r.get("invite_link")]
        free_text = await db.get_bot_text("free_activation_success")
        if resources_with_links:
            await reply(free_text, keyboard=kb.resource_links_buttons(resources_with_links))
        else:
            channel_link = tariff.get("channel_link") or "https://max.ru"
            await reply(free_text, keyboard=kb.channel_link_button(channel_link))

    # ── Мои подписки ─────────────────────────────────────
    elif payload == "my_subs":
        subs = await db.get_active_subscriptions_with_resources(user_id)
        pending = await db.get_pending_subscriptions(user_id)
        if not subs and not pending:
            await reply(
                await db.get_bot_text("no_active_subs"),
                keyboard=kb.main_menu(user_id, btn=btn),
            )
        else:
            lines = ["📋 Ваши подписки:\n"]
            for s in subs:
                # Собираем псевдо-тариф из полей подписки для форматирования
                fake_tariff = {
                    "end_date": s.get("tariff_end_date"),
                    "duration_days": s.get("tariff_duration_days"),
                }
                dur_str = _format_course_duration(fake_tariff, expires_at=s.get("expires_at"))
                dur_line = f"\n   ⏰ {dur_str}" if dur_str else ""
                lines.append(f"✅ {s['tariff_name']}{dur_line}")
            for p in pending:
                lines.append(f"⏳ {p['tariff_name']} — ожидает подтверждения оплаты")
            # Если подписки есть, но ни у одного ресурса нет invite_link — добавляем пояснение
            has_links = any(
                res.get("invite_link", "").strip()
                for s in subs
                for res in s.get("resources", [])
            )
            if subs and not has_links:
                lines.append("\n_Ссылки на ресурсы появятся здесь после их настройки._")
            await reply("\n".join(lines), keyboard=kb.my_subs_buttons(subs))

    # ── Договор оферты ───────────────────────────────────
    elif payload == "oferta":
        await reply(OFERTA_TEXT, keyboard=kb.oferta_buttons())

    # ── Обратная связь ───────────────────────────────────
    elif payload == "feedback":
        set_state(user_id, "waiting_feedback")
        await reply(await db.get_bot_text("feedback"), keyboard=kb.feedback_cancel())

    # ── Отмена обратной связи ────────────────────────────
    elif payload == "cancel_feedback":
        clear_state(user_id)
        await reply("Выберите действие:", keyboard=kb.main_menu(user_id, btn=btn))


async def handle_message(bot: MaxBot, update: dict):
    """Обработка текстовых сообщений (FSM)."""
    msg = update.get("message", {})
    body = msg.get("body", {})
    text = body.get("text", "").strip()
    sender = msg.get("sender", {})
    recipient = msg.get("recipient", {})
    user_id = int(sender.get("user_id", 0))
    chat_id = int(recipient.get("chat_id") or user_id)

    btn = await db.get_button_texts()

    # ── Обработка контакта (сбор телефонов) ───────────────
    attachments = body.get("attachments", [])
    for att in attachments:
        if att.get("type") == "contact":
            payload = att.get("payload", {})
            phone = payload.get("vcf_phone") or payload.get("tam_info", {}).get("phone", "")
            if phone:
                await db.save_user_phone(user_id, phone)
                await bot.send_message(
                    chat_id,
                    "✅ Спасибо! Ваш номер телефона сохранён.",
                    keyboard=kb.main_menu(user_id, btn=btn),
                )
                return

    # /start
    if text.startswith("/start"):
        await handle_start(bot, chat_id, sender)
        return

    # FSM: админ-состояния
    if await handle_admin_message(bot, user_id, chat_id, text, attachments=attachments or []):
        return

    # Медиавложения (фото, файлы, видео) — допустимы только в feedback
    media_atts = [
        att for att in attachments
        if att.get("type") in ("image", "file", "video", "audio")
           and att.get("payload", {}).get("token")
    ]

    state = get_state(user_id)

    if not text and not media_atts:
        return

    # FSM: ввод промокода
    if state == "waiting_promo":
        state_data = user_states.get(user_id, {})
        tariff_id = state_data.get("tariff_id")
        base_price = state_data.get("base_price", 0)

        tariff = await db.get_tariff(tariff_id) if tariff_id else None
        if not tariff:
            clear_state(user_id)
            await bot.send_message(chat_id, "❌ Ошибка.", keyboard=kb.main_menu(user_id, btn=btn))
            return

        promo, error = await _validate_promo(text, user_id, tariff_id)
        if error:
            await bot.send_message(
                chat_id, error,
                keyboard=kb.promo_input_cancel(tariff_id),
            )
            return

        # Промокод валиден — считаем скидку
        discount = promo["discount_percent"]
        final_price = round(base_price * (1 - discount / 100), 2)
        if final_price < 1:
            final_price = 1  # минимум 1₽ для платёжных систем

        async def _send(text, keyboard=None):
            await bot.send_message(chat_id, text, keyboard=keyboard)

        if tariff.get("payment_link"):
            await bot.send_message(
                chat_id,
                f"✅ Промокод **{promo['code']}** применён! Скидка {discount}%\n\n"
                f"~~{base_price:.0f}₽~~ → **{final_price:.0f}₽**\n\n"
                f"💳 Для оплаты перейдите по ссылке:",
                keyboard={"type": "inline_keyboard", "payload": {"buttons": [[
                    {"type": "link", "text": "💳 Перейти к оплате", "url": tariff["payment_link"]}
                ]]}},
            )
            clear_state(user_id)
            await db.add_user_log(user_id, f"Вызвал оплату тарифа «{tariff['name']}» с промокодом {promo['code']}")
            user_data = await db.get_user(user_id)
            full_name = f"{user_data['first_name']} {user_data['last_name']}".strip() if user_data else str(user_id)
            for admin_id in ADMIN_IDS:
                try:
                    await bot.send_message(
                        admin_id,
                        f"Пользователь {full_name}\n"
                        f"ID: {user_id}\n"
                        f"Вызвал оплату тарифа {tariff['name']}\n"
                        f"Промокод: {promo['code']} (-{discount}%)\n"
                        f"Способ оплаты: внешняя ссылка\n"
                        f"Сумма: {final_price:.0f}₽",
                    )
                except Exception:
                    pass
        else:
            await bot.send_message(
                chat_id,
                f"✅ Промокод **{promo['code']}** применён! Скидка {discount}%\n\n"
                f"~~{base_price:.0f}₽~~ → **{final_price:.0f}₽**",
            )
            await _do_create_payment(bot, user_id, tariff_id, final_price, promo["id"], btn, _send)
        return

    # FSM: обратная связь
    if state == "waiting_feedback":
        if await db.is_user_banned(user_id):
            await bot.send_message(
                chat_id,
                "⛔ Вы заблокированы и не можете отправлять сообщения.",
                keyboard=kb.main_menu(user_id, btn=btn),
            )
            return

        name = sender.get("first_name", "")
        last = sender.get("last_name", "")
        full_name = f"{name} {last}".strip()

        display_text = text or "(медиа вложение)"
        feedback_text = (
            f"Пользователь: **{full_name}**\n"
            f"ID: **{user_id}**\n"
            f"Оставил запрос: {display_text}"
        )
        for admin_id in ADMIN_IDS:
            await bot.send_message(
                admin_id,
                feedback_text,
                keyboard=akb.admin_feedback_actions(user_id),
            )
            # Пересылаем вложения (фото, файлы и т.д.) администратору
            for att in media_atts:
                att_type = att.get("type", "file")
                token = att.get("payload", {}).get("token", "")
                if token:
                    await bot.forward_attachment(admin_id, att_type, token)

        await bot.send_message(
            chat_id,
            "✅ Ваше сообщение отправлено! Мы ответим, как освободимся.",
            keyboard=kb.main_menu(user_id, btn=btn),
        )
        return

    # Проверяем бан
    if await db.is_user_banned(user_id):
        await bot.send_message(chat_id, "⛔ Вы заблокированы.")
        return

    # Любое другое сообщение — показываем меню
    await bot.send_message(chat_id, "Выберите действие:", keyboard=kb.main_menu(user_id, btn=btn))
