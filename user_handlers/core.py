
from datetime import datetime, timedelta
from max_client import MaxBot
from config import ADMIN_IDS, WEBHOOK_BASE_URL
import keyboards as kb
import database as db
import admin_keyboards as akb
from admin_handlers import handle_admin_callback, handle_admin_message
from fsm import set_state, get_state, clear_state, user_states
import payments
from utils import (
    build_prodamus_webhook_url,
    parse_duration_to_minutes,
    parse_tariff_start_payload,
    user_link,
)



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



OFERTA_TEXT = (
    "Чунтонова Ольга Валерьевна, врач-диетолог-психолог,"
    "приглашает Вас пройти регистрацию и ознакомиться с"
    "условиями программ.\n\n"
    "Нажимая «Согласен(а)», вы подтверждаете:\n"
    "— ознакомление с договором оферты\n"
    "— согласие с политикой конфиденциальности\n"
    "— разрешение на обработку персональных данных\n\n"
    "Нажмите «Согласен(а)», чтобы продолжить путь к здоровой и стройной фигуре.\n\n"
    "ИП Чунтонова Ольга Валерьевна\n"
    "ИНН: 343606860606\n"
    "ОГРНИП: 323237500476410\n"
    "Сертификат № 1118242295666\n"
)




async def _calc_price(user_id: int, tariff: dict) -> float:
    base = float(tariff["price"])
    status = await db.get_user_tariff_status(user_id, tariff["id"])
    if status == "active" and tariff.get("active_renewal_price"):
        base = float(tariff["active_renewal_price"])
    elif status == "expired" and tariff.get("renewal_price"):
        base = float(tariff["renewal_price"])
    return base


async def _validate_promo(code: str, user_id: int, tariff_id: int) -> tuple[dict | None, str]:
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
    return parse_duration_to_minutes(text)


async def _get_visible_tariffs_for_user(user_id: int) -> list[dict]:
    tariffs = await db.list_tariffs()
    active_tariffs = [t for t in tariffs if t["is_active"]]
    active_tariff_ids = await db.get_active_tariff_ids(user_id)
    unlocked_tariff_ids = await db.get_unlocked_tariff_ids(user_id)
    visible = db.filter_tariffs_by_allowed_group(active_tariffs, unlocked_tariff_ids)
    return [t for t in visible if t["id"] not in active_tariff_ids]


async def _user_can_view_tariff(user_id: int, tariff: dict) -> bool:
    if not tariff or not tariff.get("is_active"):
        return False
    unlocked_tariff_ids = await db.get_unlocked_tariff_ids(user_id)
    return bool(db.filter_tariffs_by_allowed_group([tariff], unlocked_tariff_ids))


def _parse_positive_callback_id(payload: str, prefix: str) -> int | None:
    if not payload.startswith(prefix):
        return None
    raw_id = payload[len(prefix):].strip()
    if not raw_id.isdigit():
        return None
    tariff_id = int(raw_id)
    return tariff_id if tariff_id > 0 else None


def _limited_payload(value: str, limit: int = 128) -> str:
    text = str(value or "").strip()
    return text[:limit]


async def show_main_menu(
    bot: MaxBot,
    chat_id: int,
    user_id: int,
    *,
    source: str = "unknown",
    send_fn=None,
) -> None:
    """Показывает актуальное главное меню с динамической клавиатурой."""
    clear_state(user_id)
    btn = await db.get_button_texts(user_id=user_id)
    cabinet_text = await db.get_bot_text("desc_cabinet", user_id=user_id)
    if send_fn:
        await send_fn(cabinet_text, kb.main_menu(user_id, btn=btn))
    else:
        await bot.send_message(chat_id, cabinet_text, keyboard=kb.main_menu(user_id, btn=btn))
    if source not in ("start", "callback"):
        await db.add_user_log(user_id, f"Открыл главное меню ({source})")


async def show_catalog(
    bot: MaxBot,
    chat_id: int,
    user_id: int,
    *,
    send_fn=None,
) -> None:
    btn = await db.get_button_texts(user_id=user_id)
    visible = await _get_visible_tariffs_for_user(user_id)
    catalog_text = await db.get_bot_text("desc_catalog", user_id=user_id)
    keyboard = kb.start_catalog(visible, user_id, btn=btn)
    if send_fn:
        await send_fn(catalog_text, keyboard)
    else:
        await bot.send_message(chat_id, catalog_text, keyboard=keyboard)


async def show_tariff_details(
    bot: MaxBot,
    chat_id: int,
    user_id: int,
    tariff_id: int,
    *,
    source: str = "catalog",
    send_fn=None,
) -> bool:
    """Показывает карточку тарифа единым способом для каталога и deep link."""
    btn = await db.get_button_texts(user_id=user_id)

    async def _send(text: str, keyboard=None):
        if send_fn:
            await send_fn(text, keyboard)
        else:
            await bot.send_message(chat_id, text, keyboard=keyboard)

    tariff = await db.get_tariff(tariff_id)
    if not tariff:
        return False

    if not await _user_can_view_tariff(user_id, tariff):
        visible = await _get_visible_tariffs_for_user(user_id)
        await _send(
            "Этот тариф сейчас недоступен для оформления.\n\n"
            "Вы можете выбрать другой курс в каталоге.",
            kb.tariff_list(visible),
        )
        return True

    user_tariff_ids = await db.get_active_tariff_ids(user_id)
    if tariff_id in user_tariff_ids:
        await _send(
            "✅ У вас уже есть активная подписка на этот тариф.",
            kb.main_menu(user_id, btn=btn),
        )
        return True

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
    await _send(
        text.strip(),
        keyboard=kb.tariff_detail_buttons(tariff_id, tariff["is_free"]),
    )
    if source == "deep_link":
        await db.add_user_log(user_id, f"Открыл тариф «{tariff['name']}» по прямой ссылке")
    return True


async def process_start_payload(
    bot: MaxBot,
    chat_id: int,
    user_id: int,
    start_payload: str,
) -> bool:
    payload = str(start_payload or "").strip()
    if not payload:
        return False

    tariff_id = parse_tariff_start_payload(payload)
    if tariff_id is None:
        await db.add_user_log(user_id, f"Перешёл по неизвестному start payload: {_limited_payload(payload)}")
        return False

    handled = await show_tariff_details(
        bot,
        chat_id,
        user_id,
        tariff_id,
        source="deep_link",
    )
    if not handled:
        await db.add_user_log(user_id, f"Перешёл по недействительной ссылке на тариф: tariff_{tariff_id}")
        visible = await _get_visible_tariffs_for_user(user_id)
        await bot.send_message(
            chat_id,
            "К сожалению, этот тариф больше недоступен.\n\n"
            "Вы можете выбрать другой курс в каталоге.",
            keyboard=kb.tariff_list(visible),
        )
    return True


async def _activate_purchase(bot: MaxBot, purchase: dict):
    user_id = purchase["user_id"]
    tariff_id = purchase["tariff_id"]

    tariff_data = await db.get_tariff(tariff_id)
    expires_at = None
    if tariff_data:
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
                dm = _parse_duration_to_minutes(tariff_data.get("duration_text") or "")
                if dm and dm > 0:
                    expires_at = datetime.now() + timedelta(minutes=dm)

    confirmed = await db.confirm_purchase(purchase["id"], expires_at=expires_at)
    if not confirmed:
        return False

    resources = await db.get_tariff_resources(tariff_id)
    for res in resources:
        await bot.add_chat_member(res["chat_id"], [user_id])

    if purchase.get("promo_id"):
        await db.add_promo_activation(
            purchase["promo_id"], user_id, tariff_id, paid=True,
        )

    success_text = await db.get_bot_text("payment_success", user_id=user_id)
    duration_str = _format_course_duration(tariff_data, expires_at)
    if duration_str:
        success_text = f"{success_text}\n\n⏰ {duration_str}"
    await bot.send_message(user_id, success_text)

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
        f"Пользователь: {user_link(full_name, user_id)}\n"
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
            await bot.send_message(admin_id, admin_text, fmt="markdown")
        except Exception:
            pass

    for res in resources:
        chat_title = res.get("chat_title") or str(res["chat_id"])
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(
                    admin_id,
                    f"Пользователь {user_link(full_name, user_id)}\n"
                    f"ID: {user_id}\n\n"
                    f"Вступил в {chat_title}",
                    fmt="markdown",
                )
            except Exception:
                pass

    if resources:
        links_text = await db.get_bot_text("activation_links", user_id=user_id)
        resources_with_links = [r for r in resources if r.get("invite_link")]
        has_bonus = bool(await db.get_gift_files_for_tariffs([tariff_id]))
        bonus_kb_param = tariff_id if has_bonus else None
        if resources_with_links:
            await bot.send_message(
                user_id,
                links_text,
                keyboard=kb.resource_links_buttons(resources_with_links, bonus_tariff_id=bonus_kb_param),
            )
        else:
            tariff = await db.get_tariff(tariff_id)
            channel_link = tariff.get("channel_link") if tariff else None
            if channel_link:
                await bot.send_message(
                    user_id,
                    links_text,
                    keyboard=kb.channel_link_button(channel_link, bonus_tariff_id=bonus_kb_param),
                )
            else:
                res_names = [r.get("chat_title") or str(r["chat_id"]) for r in resources]
                await bot.send_message(
                    user_id,
                    links_text + "\n" + "\n".join(f"• {n}" for n in res_names),
                )

    await show_catalog(bot, user_id, user_id)
    return True


async def _do_create_payment(bot: MaxBot, user_id: int, tariff_id: int,
                             final_price: float, promo_id: int | None,
                             btn: dict, send_fn):
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

    webhook_url = build_prodamus_webhook_url(WEBHOOK_BASE_URL)
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
                f"Пользователь {user_link(full_name, user_id)}\n"
                f"ID: {user_id}\n"
                f"Вызвал оплату тарифа {tariff['name']}\n"
                f"Способ оплаты {method['name']}\n"
                f"Сумма: {final_price:.0f}₽",
                fmt="markdown",
            )
        except Exception:
            pass

    await send_fn(
        await db.get_bot_text(
            "payment_invoice",
            user_id=user_id,
            tariff_name=tariff["name"],
            price=f"{final_price:.0f}",
            method_name=method["name"],
        ),
        kb.payment_created(result["payment_url"], purchase["id"]),
    )



async def _send_welcome_catalog(bot: MaxBot, chat_id: int, user_id: int):
    await bot.send_message(chat_id, await db.get_bot_text("welcome", user_id=user_id))
    await show_catalog(bot, chat_id, user_id)


async def handle_start(bot: MaxBot, chat_id: int, sender: dict, start_payload: str = ""):
    """Команда /start или bot_started."""
    user_id = int(sender.get("user_id", 0))
    if not user_id:
        return
    clear_state(user_id)
    start_payload = str(start_payload or "").strip()

    first_name = sender.get("first_name", "")
    last_name = sender.get("last_name", "")
    if not first_name and not last_name:
        full = sender.get("name", "")
        parts = full.split(" ", 1)
        first_name = parts[0] if parts else ""
        last_name = parts[1] if len(parts) > 1 else ""

    user_exists = await db.get_user(user_id)
    is_new = user_exists is None

    print(f"[USER] id={user_id} is_new={is_new} name={first_name!r} {last_name!r}")

    await db.upsert_user(
        user_id,
        first_name=first_name,
        last_name=last_name,
        username=sender.get("username", ""),
    )

    await db.add_user_log(user_id, "Впервые зашёл в бота" if is_new else "Вызвал /start")

    if await db.is_user_banned(user_id):
        await bot.send_message(chat_id, "⛔ Вы заблокированы.")
        return

    if is_new:
        full_name = f"{first_name} {last_name}".strip() or "—"
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(
                    admin_id,
                    f"🆕 Новый пользователь:\n{user_link(full_name, user_id)}\n"
                    f"ID: {user_id}",
                    fmt="markdown",
                )
            except Exception:
                pass

    if not await db.has_terms_agreed(user_id):
        if start_payload:
            set_state(user_id, "waiting_terms", start_payload=start_payload)
        await bot.send_message(chat_id, OFERTA_TEXT, keyboard=kb.consent_buttons())
        return

    if await process_start_payload(bot, chat_id, user_id, start_payload):
        return

    await _send_welcome_catalog(bot, chat_id, user_id)


async def handle_callback(bot: MaxBot, update: dict):
    """Обработка нажатий inline-кнопок."""
    callback = update.get("callback", {})
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

    if payload.startswith("adm:"):
        await handle_admin_callback(bot, update)
        return

    if payload == "agree_terms":
        state_data = user_states.get(user_id, {})
        pending_payload = state_data.get("start_payload", "") if state_data.get("state") == "waiting_terms" else ""
        await db.set_terms_agreed(user_id)
        await db.add_user_log(user_id, "Принял оферту и политику конфиденциальности")
        clear_state(user_id)
        if await process_start_payload(bot, chat_id, user_id, pending_payload):
            return
        await _send_welcome_catalog(bot, chat_id, user_id)
        return

    if not await db.has_terms_agreed(user_id):
        await bot.send_message(chat_id, OFERTA_TEXT, keyboard=kb.consent_buttons())
        return

    btn = await db.get_button_texts(user_id=user_id)

    async def reply(text: str, keyboard=None):
        ok = await bot.edit_message(message_id, text, keyboard=keyboard)
        if not ok:
            await bot.send_message(chat_id, text, keyboard=keyboard)

    if payload in {"back_main", "main_menu"}:
        await show_main_menu(bot, chat_id, user_id, source="callback", send_fn=reply)

    elif payload.startswith("get_bonus_tariff:"):
        tariff_id = _parse_positive_callback_id(payload, "get_bonus_tariff:")
        if tariff_id is None:
            await reply("❌ Некорректный тариф.", keyboard=kb.main_menu(user_id, btn=btn))
            return
        gifts = await db.get_gift_files_for_tariffs([tariff_id])
        if not gifts:
            await reply("К этому тарифу бонусов не предусмотрено",
                        keyboard=kb.main_menu(user_id, btn=btn))
            return
        await reply("Вот ваш бонус 👇")
        seen_tokens: set[str] = set()
        for g in gifts:
            token = g.get("file_token") or ""
            if not token or token in seen_tokens:
                continue
            seen_tokens.add(token)
            await bot.send_file_token(user_id, token, text="")


    elif payload == "courses" or payload == "back_courses":
        clear_state(user_id)
        visible = await _get_visible_tariffs_for_user(user_id)
        await reply(await db.get_bot_text("tariff_selection", user_id=user_id), keyboard=kb.tariff_list(visible))

    elif payload.startswith("tariff:"):
        clear_state(user_id)
        tariff_id = _parse_positive_callback_id(payload, "tariff:")
        if tariff_id is None:
            await reply("❌ Некорректный тариф.", keyboard=kb.main_menu(user_id, btn=btn))
            return
        handled = await show_tariff_details(
            bot,
            chat_id,
            user_id,
            tariff_id,
            source="catalog",
            send_fn=reply,
        )
        if not handled:
            await reply("К сожалению, этот тариф больше недоступен.", keyboard=kb.main_menu(user_id, btn=btn))

    elif payload.startswith("pay:"):
        tariff_id = _parse_positive_callback_id(payload, "pay:")
        if tariff_id is None:
            await reply("❌ Некорректный тариф.", keyboard=kb.main_menu(user_id, btn=btn))
            return
        tariff = await db.get_tariff(tariff_id)
        if not tariff:
            return
        if not await _user_can_view_tariff(user_id, tariff):
            await reply("❌ Этот тариф вам недоступен.", keyboard=kb.main_menu(user_id, btn=btn))
            return
        user_tariff_ids = await db.get_active_tariff_ids(user_id)
        if tariff_id in user_tariff_ids:
            await reply("✅ У вас уже есть активная подписка на этот тариф.", keyboard=kb.main_menu(user_id, btn=btn))
            return
        price = await _calc_price(user_id, tariff)
        await db.add_user_log(user_id, f"Вызвал оплату тарифа «{tariff['name']}»")
        set_state(user_id, "waiting_promo", tariff_id=tariff_id, base_price=price)
        await reply(
            await db.get_bot_text(
                "promo_activation",
                user_id=user_id,
                Название=tariff['name'],
                сумма=f"{price:.0f}₽",
            ),
            keyboard=kb.promo_input_cancel(tariff_id),
        )

    elif payload.startswith("promo_skip:"):
        tariff_id = _parse_positive_callback_id(payload, "promo_skip:")
        if tariff_id is None:
            await reply("❌ Некорректный тариф.", keyboard=kb.main_menu(user_id, btn=btn))
            return
        state_data = user_states.get(user_id, {})
        base_price = state_data.get("base_price", 0)
        tariff_tmp = await db.get_tariff(tariff_id)
        if not base_price:
            base_price = await _calc_price(user_id, tariff_tmp) if tariff_tmp else 0
        clear_state(user_id)
        if tariff_tmp and tariff_tmp.get("payment_link"):
            pay_kb = {"type": "inline_keyboard", "payload": {"buttons": [[
                {"type": "link", "text": "💳 Перейти к оплате", "url": tariff_tmp["payment_link"]}
            ], [
                {"type": "callback", "text": "🏠 Главное меню", "payload": "main_menu"}
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

        webhook_url = build_prodamus_webhook_url(WEBHOOK_BASE_URL)
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

        await reply(
            await db.get_bot_text(
                "payment_invoice",
                user_id=user_id,
                tariff_name=tariff["name"],
                price=f"{final_price:.0f}",
                method_name=method["name"],
            ),
            keyboard=kb.payment_created(result["payment_url"], purchase["id"], btn=btn),
        )

    elif payload.startswith("check_pay:"):
        purchase_id = _parse_positive_callback_id(payload, "check_pay:")
        if purchase_id is None:
            await reply("❌ Платёж не найден.", keyboard=kb.main_menu(user_id, btn=btn))
            return
        purchase = await db.get_purchase(purchase_id)

        if not purchase:
            await reply("❌ Платёж не найден.", keyboard=kb.main_menu(user_id, btn=btn))
            return

        if purchase["user_id"] != user_id:
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
            processing_text = await db.get_bot_text("payment_processing", user_id=user_id)
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
            if await _activate_purchase(bot, purchase):
                await db.add_user_log(user_id, "Оплатил")
        elif status == "canceled":
            await db.add_user_log(user_id, "Не оплатил (отмена)")
            await db.cancel_purchase(purchase_id)
            failed_text = await db.get_bot_text("payment_failed", user_id=user_id)
            await reply(
                failed_text,
                keyboard=kb.main_menu(user_id, btn=btn),
            )
        else:
            processing_text = await db.get_bot_text("payment_processing", user_id=user_id)
            await reply(
                processing_text,
                keyboard=kb.payment_created("https://max.ru", purchase_id, btn=btn),
            )

    elif payload.startswith("activate:"):
        tariff_id = _parse_positive_callback_id(payload, "activate:")
        if tariff_id is None:
            await reply("❌ Некорректный тариф.", keyboard=kb.main_menu(user_id, btn=btn))
            return
        tariff = await db.get_tariff(tariff_id)
        if not tariff:
            return
        if not await _user_can_view_tariff(user_id, tariff):
            await reply("❌ Этот тариф вам недоступен.", keyboard=kb.main_menu(user_id, btn=btn))
            return
        user_tariff_ids = await db.get_active_tariff_ids(user_id)
        if tariff_id in user_tariff_ids:
            await reply("✅ У вас уже есть активная подписка на этот тариф.", keyboard=kb.main_menu(user_id, btn=btn))
            return

        await db.upsert_user(user_id)

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

        has_bonus = bool(await db.get_gift_files_for_tariffs([tariff_id]))
        bonus_kb_param = tariff_id if has_bonus else None
        resources_with_links = [r for r in resources if r.get("invite_link")]
        free_text = await db.get_bot_text("free_activation_success", user_id=user_id)
        channel_link = tariff.get("channel_link")
        if resources_with_links:
            await reply(free_text, keyboard=kb.resource_links_buttons(resources_with_links, bonus_tariff_id=bonus_kb_param))
        elif channel_link:
            await reply(free_text, keyboard=kb.channel_link_button(channel_link, bonus_tariff_id=bonus_kb_param))
        elif has_bonus:
            await reply(free_text, keyboard=kb._kb([
                [{"type": "callback", "text": "🎁 Получить бонус", "payload": f"get_bonus_tariff:{tariff_id}"}],
                [{"type": "callback", "text": "🏠 Главное меню", "payload": "main_menu"}],
            ]))
        else:
            await reply(free_text, keyboard=kb.main_menu(user_id, btn=btn))

        await show_catalog(bot, chat_id, user_id)

    elif payload == "my_subs":
        subs = await db.get_active_subscriptions_with_resources(user_id)
        if not subs:
            await reply(
                await db.get_bot_text("no_active_subs", user_id=user_id),
                keyboard=kb.main_menu(user_id, btn=btn),
            )
        else:
            lines = ["📋 Ваши подписки:\n"]
            for s in subs:
                fake_tariff = {
                    "end_date": s.get("tariff_end_date"),
                    "duration_days": s.get("tariff_duration_days"),
                }
                dur_str = _format_course_duration(fake_tariff, expires_at=s.get("expires_at"))
                dur_line = f"\n   ⏰ {dur_str}" if dur_str else ""
                lines.append(f"✅ {s['tariff_name']}{dur_line}")
            has_links = any(
                res.get("invite_link", "").strip()
                for s in subs
                for res in s.get("resources", [])
            )
            if not has_links:
                lines.append("\n_Ссылки на ресурсы появятся здесь после их настройки._")
            await reply("\n".join(lines), keyboard=kb.my_subs_buttons(subs))

    elif payload == "oferta":
        await reply(OFERTA_TEXT, keyboard=kb.oferta_buttons())

    elif payload == "feedback":
        set_state(user_id, "waiting_feedback")
        await reply(await db.get_bot_text("feedback", user_id=user_id), keyboard=kb.feedback_cancel())

    elif payload == "cancel_feedback":
        clear_state(user_id)
        await show_main_menu(bot, chat_id, user_id, source="callback", send_fn=reply)


async def handle_message(bot: MaxBot, update: dict):
    """Обработка текстовых сообщений (FSM)."""
    msg = update.get("message", {})
    body = msg.get("body", {})
    text = body.get("text", "").strip()
    sender = msg.get("sender", {})
    recipient = msg.get("recipient", {})
    user_id = int(sender.get("user_id", 0))
    chat_id = int(recipient.get("chat_id") or user_id)

    btn = await db.get_button_texts(user_id=user_id)

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

    if text.startswith("/start"):
        parts = text.split(maxsplit=1)
        start_payload = parts[1] if len(parts) > 1 else ""
        await handle_start(bot, chat_id, sender, start_payload=start_payload)
        return

    if text.startswith("/menu"):
        await db.upsert_user(
            user_id,
            first_name=sender.get("first_name", ""),
            last_name=sender.get("last_name", ""),
            username=sender.get("username", ""),
        )
        if await db.is_user_banned(user_id):
            await bot.send_message(chat_id, "⛔ Вы заблокированы.")
            return
        if not await db.has_terms_agreed(user_id):
            clear_state(user_id)
            await bot.send_message(chat_id, OFERTA_TEXT, keyboard=kb.consent_buttons())
            return
        await show_main_menu(bot, chat_id, user_id, source="menu_command")
        return

    if text.startswith("/chat_id"):
        if chat_id == user_id:
            await bot.send_message(
                chat_id,
                f"Текущий dialog/user_id: `{chat_id}`\n"
                "Чтобы получить ID ресурса, отправьте /chat_id в нужном групповом чате или канале.",
            )
            return

        title = str(chat_id)
        saved = False
        try:
            info = await bot.get_chat_info(chat_id)
            chat_type = info.get("type")
            status = info.get("status")
            title = info.get("title") or title
            if chat_type in ("chat", "channel") and status == "active":
                await db.upsert_bot_chat(
                    int(info.get("chat_id") or chat_id),
                    title=title,
                    link=info.get("link") or "",
                    is_channel=chat_type == "channel",
                )
                saved = True
        except Exception as e:
            print(f"  [/chat_id] не удалось получить инфо chat_id={chat_id}: {e}")

        suffix = "\nРесурс сохранён в каталоге бота." if saved else "\nID можно добавить вручную в админке."
        await bot.send_message(
            chat_id,
            f"chat_id: `{chat_id}`\nНазвание: {title}{suffix}",
        )
        return

    if not await db.has_terms_agreed(user_id):
        await bot.send_message(chat_id, OFERTA_TEXT, keyboard=kb.consent_buttons())
        return

    if await handle_admin_message(bot, user_id, chat_id, text, attachments=attachments or []):
        return

    media_atts = [
        att for att in attachments
        if att.get("type") in ("image", "file", "video", "audio")
           and att.get("payload", {}).get("token")
    ]

    state = get_state(user_id)

    if not text and not media_atts:
        return

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
                ], [
                    {"type": "callback", "text": "🏠 Главное меню", "payload": "main_menu"}
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
            f"Пользователь: {user_link(full_name, user_id)}\n"
            f"ID: **{user_id}**\n"
            f"Оставил запрос: {display_text}"
        )
        for admin_id in ADMIN_IDS:
            await bot.send_message(
                admin_id,
                feedback_text,
                keyboard=akb.admin_feedback_actions(user_id),
                fmt="markdown",
            )
            for att in media_atts:
                att_type = att.get("type", "file")
                token = att.get("payload", {}).get("token", "")
                if token:
                    await bot.forward_attachment(admin_id, att_type, token)

        await bot.send_message(
            chat_id,
            "✅ Ваше сообщение отправлено! Ольга Валерьевна ответит, как освободится.",
            keyboard=kb.main_menu(user_id, btn=btn),
        )
        return

    if await db.is_user_banned(user_id):
        await bot.send_message(chat_id, "⛔ Вы заблокированы.")
        return

    unknown_text = await db.get_bot_text("unknown_message", user_id=user_id)
    await bot.send_message(chat_id, unknown_text, keyboard=kb.main_menu(user_id, btn=btn))
