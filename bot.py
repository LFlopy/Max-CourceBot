import asyncio
import hmac
import json
import logging
from aiohttp import web
from max_client import MaxBot
import config as cfg
from handlers import handle_start, handle_callback, handle_message, _activate_purchase
import database as db
import payments
from services.background_jobs import (
    EXPIRY_CHECK_INTERVAL,
    PAYMENT_CHECK_INTERVAL,
    WARMUP_CHECK_INTERVAL,
    check_expired_subscriptions,
    check_pending_payments,
    check_warmup_messages,
)
from utils import build_prodamus_webhook_url, parse_duration_to_minutes, redact_headers, redact_mapping

logger = logging.getLogger(__name__)

BOT_TOKEN = cfg.BOT_TOKEN
WEBHOOK_HOST = getattr(cfg, "WEBHOOK_HOST", "0.0.0.0")
WEBHOOK_PORT = getattr(cfg, "WEBHOOK_PORT", 8443)
WEBHOOK_BASE_URL = getattr(cfg, "WEBHOOK_BASE_URL", "")
MAX_WEBHOOK_PATH = getattr(cfg, "MAX_WEBHOOK_PATH", "/max/webhook")
MAX_WEBHOOK_URL = getattr(
    cfg,
    "MAX_WEBHOOK_URL",
    build_prodamus_webhook_url(WEBHOOK_BASE_URL, MAX_WEBHOOK_PATH),
)
MAX_WEBHOOK_SECRET = getattr(cfg, "MAX_WEBHOOK_SECRET", "")
MAX_UPDATE_TYPES = getattr(
    cfg,
    "MAX_UPDATE_TYPES",
    ["bot_started", "message_created", "message_callback", "bot_added", "bot_removed"],
)

MAX_WEBHOOK_BODY_BYTES = 512 * 1024


def _parse_duration_to_minutes(text: str) -> int | None:
    return parse_duration_to_minutes(text)


def _run_background_update(bot: MaxBot, update: dict) -> None:
    task = asyncio.create_task(process_update(bot, update))
    task.add_done_callback(_log_background_task_result)


def _log_background_task_result(task: asyncio.Task) -> None:
    try:
        task.result()
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.exception("Background update task failed")


def _extract_event_chat_id(upd: dict) -> int | None:
    chat_id = upd.get("chat_id")
    if chat_id:
        return int(chat_id)

    msg = upd.get("message") or {}
    recipient = msg.get("recipient") or {}
    chat_id = recipient.get("chat_id")
    if chat_id:
        return int(chat_id)

    callback = upd.get("callback") or {}
    callback_message = callback.get("message") or {}
    recipient = callback_message.get("recipient") or {}
    chat_id = recipient.get("chat_id")
    if chat_id:
        return int(chat_id)

    return None


async def remember_chat_from_update(bot: MaxBot, upd: dict) -> None:
    """Поддерживает локальный каталог ресурсов по любому событию из чата."""
    chat_id = _extract_event_chat_id(upd)
    if not chat_id:
        return

    try:
        info = await bot.get_chat_info(chat_id)
    except Exception as e:
        print(f"  [chat_catalog] не удалось получить инфо chat_id={chat_id}: {e}")
        return

    chat_type = info.get("type")
    status = info.get("status")
    if chat_type not in ("chat", "channel") or status != "active":
        return

    await db.upsert_bot_chat(
        int(info.get("chat_id") or chat_id),
        title=info.get("title") or str(chat_id),
        link=info.get("link") or "",
        is_channel=chat_type == "channel",
    )


async def process_update(bot: MaxBot, upd: dict) -> None:
    """Обрабатывает один Update от MAX (одинаково для polling и webhook)."""
    try:
        update_type = upd.get("update_type", "")

        await remember_chat_from_update(bot, upd)

        if update_type == "bot_added":
            chat_id = upd.get("chat_id")
            is_channel = upd.get("is_channel", False)
            print(f"  [bot_added] chat_id={chat_id} is_channel={is_channel}")
            title, link = str(chat_id), ""
            try:
                info = await bot.get_chat_info(chat_id)
                title = info.get("title") or title
                link = info.get("link") or ""
            except Exception as e:
                print(f"  [bot_added] не удалось получить инфо о чате: {e}")
            await db.upsert_bot_chat(chat_id, title=title, link=link, is_channel=is_channel)
            return

        if update_type == "bot_removed":
            chat_id = upd.get("chat_id")
            print(f"  [bot_removed] chat_id={chat_id}")
            await db.mark_bot_chat_removed(chat_id)
            return

        if update_type == "chat_title_changed":
            chat_id = upd.get("chat_id")
            new_title = upd.get("title", "")
            print(f"  [chat_title_changed] chat_id={chat_id} title={new_title}")
            if chat_id and new_title:
                await db.update_bot_chat_title(chat_id, new_title)
            return

        if "callback" in upd:
            print(f"  [callback] payload={upd['callback'].get('payload', '?')}")
            await handle_callback(bot, upd)

        elif "message" in upd:
            msg = upd["message"]
            text = msg.get("body", {}).get("text", "")
            sender = msg.get("sender", {})
            recipient = msg.get("recipient", {})
            chat_id = int(recipient.get("chat_id") or sender.get("user_id", 0))
            print(f"  [message] text={text}")

            if text.strip().startswith("/start"):
                await handle_start(bot, chat_id, sender)
            else:
                await handle_message(bot, upd)

        elif "user" in upd and "message" not in upd and "callback" not in upd:
            user_info = upd.get("user", {})
            chat_id = int(upd.get("chat_id") or user_info.get("user_id", 0))
            print(f"  [bot_started] user_id={user_info.get('user_id')}")
            await handle_start(bot, chat_id, user_info)

    except Exception as e:
        print(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()



async def handle_max_webhook(request: web.Request) -> web.Response:
    """Принимает POST от MAX. Должен ответить 200 в течение 30 секунд,
    иначе MAX считает доставку неуспешной и повторит попытку."""
    bot: MaxBot = request.app["bot"]

    if request.content_length and request.content_length > MAX_WEBHOOK_BODY_BYTES:
        return web.Response(status=413, text="Payload Too Large")

    print(f"  [max-webhook] headers={redact_headers(dict(request.headers))}")
    if MAX_WEBHOOK_SECRET:
        received = request.headers.get("X-Max-Bot-Api-Secret", "")
        if not hmac.compare_digest(received, MAX_WEBHOOK_SECRET):
            print(f"  [max-webhook] ❌ Неверный X-Max-Bot-Api-Secret")
            return web.Response(status=403, text="Forbidden")

    try:
        body = await request.read()
        if len(body) > MAX_WEBHOOK_BODY_BYTES:
            return web.Response(status=413, text="Payload Too Large")
        upd = json.loads(body)
    except Exception as e:
        print(f"  [max-webhook] ❌ Не удалось распарсить JSON: {e}")
        return web.Response(status=400, text="Bad Request")

    updates = upd.get("updates") if isinstance(upd, dict) else None
    if isinstance(updates, list):
        for item in updates:
            if isinstance(item, dict):
                _run_background_update(bot, item)
    else:
        _run_background_update(bot, upd)
    return web.Response(text="OK", status=200)



async def handle_prodamus_webhook(request: web.Request) -> web.Response:
    """Принимает POST от Prodamus при успешной оплате."""
    bot: MaxBot = request.app["bot"]
    try:
        if request.content_length and request.content_length > MAX_WEBHOOK_BODY_BYTES:
            return web.Response(status=413, text="Payload Too Large")
        body = await request.read()
        if len(body) > MAX_WEBHOOK_BODY_BYTES:
            return web.Response(status=413, text="Payload Too Large")
        data = await request.post()

        print("  [webhook] Prodamus fields:", sorted(data.keys()))

        status = (
            data.get("status")
            or data.get("payment_status")
            or data.get("paymentState")
            or ""
        ).lower()

        if status not in ("success", "paid", "succeeded", "ok"):
            print(f"⛔ Неуспешный статус: {status}")
            return web.Response(text="OK")

        _id_fields = ("order_num", "order_id", "order", "payment_id", "id")
        candidate_ids = []
        for field in _id_fields:
            val = data.get(field)
            if val is not None:
                val_str = str(val).strip()
                if val_str and val_str not in candidate_ids:
                    candidate_ids.append(val_str)

        print(f"  [webhook] Prodamus: status={status}, candidate_ids={candidate_ids}")

        purchase = None
        matched_id = None
        for cid in candidate_ids:
            purchase = await db.get_pending_purchase_by_payment_id(cid)
            if purchase:
                matched_id = cid
                break

        if not purchase:
            print(f"  [webhook] ❌ Покупка не найдена ни по одному ID: {candidate_ids}")
            print(f"  [webhook] Данные webhook для отладки: {redact_mapping(dict(data))}")
            return web.Response(text="OK")

        method = await db.get_payment_method(purchase["payment_method_id"])
        if method and method.get("secret_key"):
            signature = (
                request.headers.get("Sign")
                or request.headers.get("sign")
                or request.headers.get("X-Signature")
                or request.headers.get("x-signature")
                or ""
            )
            if not payments.ProdamusProvider.verify_signature(body, method["secret_key"], signature):
                print(f"  [webhook] Неверная подпись для order_id={matched_id}")
                return web.Response(status=403, text="Invalid signature")

        if await _activate_purchase(bot, purchase):
            await db.add_user_log(purchase["user_id"], "Оплатил (webhook Prodamus)")
            print(f"  [webhook] ✅ Платёж matched_id={matched_id} user={purchase['user_id']} — активирован")
        else:
            print(f"  [webhook] Платёж matched_id={matched_id} уже обработан")

    except Exception as e:
        logger.exception("[webhook] Ошибка обработки: %s", e)

    return web.Response(text="OK")


_webhook_runner: web.AppRunner | None = None


async def start_webhook_server(bot: MaxBot) -> None:
    """Запускает HTTP-сервер для приёма webhook-ов (MAX + платёжные)."""
    global _webhook_runner
    app = web.Application()
    app["bot"] = bot

    app.router.add_post(MAX_WEBHOOK_PATH, handle_max_webhook)
    app.router.add_get(MAX_WEBHOOK_PATH, lambda r: web.Response(text="OK"))

    app.router.add_post("/prodamus/webhook", handle_prodamus_webhook)
    app.router.add_post("/prodamus/webhook/{tail:.*}", handle_prodamus_webhook)
    app.router.add_get("/prodamus/webhook", lambda r: web.Response(text="OK"))
    app.router.add_get("/prodamus/webhook/{tail:.*}", lambda r: web.Response(text="OK"))

    _webhook_runner = web.AppRunner(app)
    await _webhook_runner.setup()
    site = web.TCPSite(_webhook_runner, WEBHOOK_HOST, WEBHOOK_PORT)
    await site.start()
    print(f"🌐 Webhook-сервер запущен на {WEBHOOK_HOST}:{WEBHOOK_PORT}")
    print(f"   MAX webhook (локально):    {MAX_WEBHOOK_PATH}")
    print(f"   MAX webhook (публично):    {MAX_WEBHOOK_URL}")
    if WEBHOOK_BASE_URL:
        print(f"   URL для Prodamus:          {build_prodamus_webhook_url(WEBHOOK_BASE_URL)}")


async def subscribe_max_webhook(bot: MaxBot) -> None:
    """Подписывает бота на доставку обновлений MAX по webhook."""
    if not MAX_WEBHOOK_URL or not MAX_WEBHOOK_URL.startswith("https://"):
        raise RuntimeError(
            "MAX_WEBHOOK_URL должен быть HTTPS-адресом на порту 443. "
            "Укажите его в config.py."
        )
    if not MAX_WEBHOOK_SECRET:
        print("⚠️  MAX_WEBHOOK_SECRET не задан — рекомендуется указать его в config.py.")

    ok, data = await bot.subscribe_webhook(
        url=MAX_WEBHOOK_URL,
        update_types=MAX_UPDATE_TYPES,
        secret=MAX_WEBHOOK_SECRET or None,
    )
    if not ok:
        raise RuntimeError(f"Не удалось подписаться на webhook MAX: {data}")
    print(f"✅ Подписка на MAX webhook оформлена: {MAX_WEBHOOK_URL}")


async def backfill_bot_chats(bot: MaxBot) -> None:
    """Разово подтягивает список чатов через GET /chats и кладёт в bot_chats.
    Нужно, чтобы в таблице оказались чаты, в которые бота добавили ДО того,
    как появилась эта логика (для новых чатов дальше всё придёт через
    события bot_added/bot_removed).
    ⚠️ GET /chats больше не поддерживается MAX, поэтому функция оставлена
    только как историческая утилита и не вызывается при старте."""
    try:
        chats = await bot.get_chats()
    except Exception as e:
        print(f"  [backfill] не удалось получить список чатов: {e}")
        return
    for c in chats:
        cid = c.get("chat_id")
        if not cid:
            continue
        await db.upsert_bot_chat(
            cid,
            title=c.get("title", str(cid)),
            link=c.get("link", ""),
            is_channel=c.get("type") == "channel" or c.get("is_channel", False),
        )
    print(f"  [backfill] bot_chats: подтянуто/обновлено {len(chats)} чатов")


async def shutdown(bot: MaxBot):
    """Корректное завершение: закрываем сессии и сервер."""
    print("\n🔴 Завершение работы...")
    await bot.stop()
    await payments.close_session()
    if _webhook_runner:
        await _webhook_runner.cleanup()
    await db.close_db()
    print("✅ Все соединения закрыты.")


async def main():
    """Run the bot, webhook server, and background workers."""
    await db.init_db()
    print("✅ БД инициализирована")

    bot = MaxBot(BOT_TOKEN)
    await bot.start()

    me = await bot.get_me()
    name = me.get("first_name", "?")
    print(f"✅ Бот: {name} (@{me.get('username', '?')})")

    await bot.cleanup_webhooks()

    await start_webhook_server(bot)

    await subscribe_max_webhook(bot)

    print("🟢 Webhook активен. Отправь /start боту в MAX.")
    print(f"🔄 Проверка подписок каждые {EXPIRY_CHECK_INTERVAL}с, платежей каждые {PAYMENT_CHECK_INTERVAL}с, догревающих каждые {WARMUP_CHECK_INTERVAL}с\n")
    try:
        await asyncio.gather(
            check_expired_subscriptions(bot),
            check_pending_payments(bot),
            check_warmup_messages(bot),
        )
    except asyncio.CancelledError:
        pass
    finally:
        await shutdown(bot)


if __name__ == "__main__":
    if BOT_TOKEN == "ВСТАВЬ_ТОКЕН_СЮДА":
        print("❌ Замени BOT_TOKEN в config.py!")
        exit(1)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Бот остановлен.")
