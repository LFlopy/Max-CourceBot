"""
Точка входа. Запуск: python bot.py
"""
import asyncio
import logging
from datetime import datetime, timedelta
import re
from aiohttp import web
from max_client import MaxBot
from config import BOT_TOKEN, WEBHOOK_HOST, WEBHOOK_PORT, WEBHOOK_BASE_URL
from handlers import handle_start, handle_callback, handle_message, _activate_purchase
import database as db
import payments

logger = logging.getLogger(__name__)

# Интервал проверки (секунды)
EXPIRY_CHECK_INTERVAL = 60
PAYMENT_CHECK_INTERVAL = 15


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


async def check_expired_subscriptions(bot: MaxBot):
    """Фоновая задача: проверяет истёкшие подписки,
    удаляет пользователей из ресурсов тарифа и уведомляет их."""
    while True:
        try:
            # Дозаполняем expires_at у активных покупок, если тариф ограничен по времени
            missing = await db.get_active_purchases_missing_expiry()
            for p in missing:
                expires_at = None
                # Если у тарифа есть end_date — подписка действует до него
                tariff_end = p.get("tariff_end_date")
                if tariff_end:
                    expires_at = tariff_end
                else:
                    base = p.get("activated_at") or p.get("purchased_at")
                    if not base:
                        continue
                    dm = p.get("duration_minutes")
                    dd = p.get("duration_days")
                    if dm and dm > 0:
                        expires_at = base + timedelta(minutes=int(dm))
                    elif dd and dd > 0:
                        expires_at = base + timedelta(days=int(dd))
                    else:
                        dm2 = _parse_duration_to_minutes(p.get("duration_text") or "")
                        if dm2 and dm2 > 0:
                            expires_at = base + timedelta(minutes=dm2)
                if expires_at:
                    await db.set_purchase_expires_at(p["id"], expires_at)

            expired = await db.get_expired_purchases()
            for p in expired:
                user_id = p["user_id"]
                tariff_id = p["tariff_id"]
                tariff_name = p["tariff_name"]

                # Получаем ресурсы (чаты/каналы) тарифа
                resources = await db.get_tariff_resources(tariff_id)
                for res in resources:
                    chat_id = res["chat_id"]
                    ok = await bot.remove_chat_member(chat_id, user_id)
                    if ok:
                        print(f"  [expiry] Удалён user={user_id} из chat={chat_id} (тариф «{tariff_name}»)")
                    else:
                        print(f"  [expiry] Не удалось удалить user={user_id} из chat={chat_id}")

                # Помечаем покупку как expired
                await db.mark_purchase_expired(p["id"])

                # Уведомляем пользователя
                notify_text = await db.get_bot_text("subscription_end")
                try:
                    await bot.send_message(
                        user_id,
                        notify_text.format(tariff_name=tariff_name),
                    )
                except Exception:
                    pass

                print(f"  [expiry] Подписка #{p['id']} user={user_id} «{tariff_name}» — expired")

            if expired:
                print(f"  [expiry] Обработано {len(expired)} истёкших подписок")

            # Деактивируем тарифы с истёкшей end_date
            expired_tariffs = await db.get_active_tariffs_with_expired_end_date()
            for tariff in expired_tariffs:
                tariff_id = tariff["id"]
                tariff_name = tariff["name"]

                # Удаляем всех активных пользователей из каналов тарифа
                purchases = await db.get_active_purchases_by_tariff(tariff_id)
                resources = await db.get_tariff_resources(tariff_id)
                for p in purchases:
                    uid = p["user_id"]
                    for res in resources:
                        ok = await bot.remove_chat_member(res["chat_id"], uid)
                        if ok:
                            print(f"  [end_date] Удалён user={uid} из chat={res['chat_id']} (тариф «{tariff_name}»)")
                    await db.mark_purchase_expired(p["id"])
                    notify_text = await db.get_bot_text("subscription_end")
                    try:
                        await bot.send_message(uid, notify_text.format(tariff_name=tariff_name))
                    except Exception:
                        pass

                # Скрываем тариф
                await db.update_tariff(tariff_id, is_active=False)
                print(f"  [end_date] Тариф #{tariff_id} «{tariff_name}» — деактивирован (end_date истёк)")

        except Exception as e:
            print(f"  [expiry] Ошибка: {e}")

        await asyncio.sleep(EXPIRY_CHECK_INTERVAL)


async def check_pending_payments(bot: MaxBot):
    """Фоновая задача: проверяет статус pending-платежей через платёжные системы."""
    while True:
        try:
            pending = await db.get_pending_payments()
            for p in pending:
                method = await db.get_payment_method(p["payment_method_id"])
                if not method:
                    continue
                provider = payments.get_provider(
                    method["provider"], method["shop_id"], method["secret_key"],
                )
                if not provider:
                    continue

                status = await provider.check_payment(p["payment_id"])

                if status == "succeeded":
                    await db.add_user_log(p["user_id"], "Оплатил")
                    await _activate_purchase(bot, p)
                    print(f"  [payment] ✅ Платёж #{p['id']} user={p['user_id']} — оплачен")

                elif status == "canceled":
                    await db.add_user_log(p["user_id"], "Не оплатил (отмена)")
                    await db.cancel_purchase(p["id"])
                    try:
                        failed_text = await db.get_bot_text("payment_failed")
                        await bot.send_message(
                            p["user_id"],
                            failed_text,
                        )
                    except Exception:
                        pass
                    print(f"  [payment] ❌ Платёж #{p['id']} user={p['user_id']} — отменён")

        except Exception as e:
            print(f"  [payment] Ошибка: {e}")

        await asyncio.sleep(PAYMENT_CHECK_INTERVAL)


async def polling_loop(bot: MaxBot):
    """Основной polling-цикл обработки обновлений."""
    marker = None

    while True:
        data = await bot.poll(marker)
        updates = data.get("updates", [])
        marker = data.get("marker", marker)

        for upd in updates:
            try:
                # MAX не шлёт update_type — определяем по ключам
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
                    # bot_started — пользователь нажал «Начать» или перешёл по ссылке
                    user_info = upd.get("user", {})
                    chat_id = int(upd.get("chat_id") or user_info.get("user_id", 0))
                    print(f"  [bot_started] user_id={user_info.get('user_id')}")
                    await handle_start(bot, chat_id, user_info)

            except Exception as e:
                print(f"❌ Ошибка: {e}")
                import traceback
                traceback.print_exc()


# ── Webhook-сервер для Prodamus ────────────────────────────────

async def handle_prodamus_webhook(request: web.Request) -> web.Response:
    """Принимает POST от Prodamus при успешной оплате."""
    bot: MaxBot = request.app["bot"]
    try:
        body = await request.read()
        data = await request.post()

        print("🔥 WEBHOOK DATA:", dict(data))

        order_id = (
            data.get("order_num")
            or data.get("order_id")
            or data.get("order")
            or ""
        )

        status = (
            data.get("status")
            or data.get("payment_status")
            or data.get("paymentState")
            or ""
        ).lower()

        print(f"  [webhook] Prodamus: order_id={order_id} status={status}")

        if status not in ("success", "paid", "succeeded", "ok"):
            print("⛔ Неуспешный статус:", status)
            return web.Response(text="OK")

        # Ищем покупку
        purchase = await db.get_pending_purchase_by_payment_id(order_id)
        if not purchase:
            print(f"  [webhook] Покупка не найдена: order_id={order_id}")
            return web.Response(text="OK")

        # Проверяем подпись (если есть secret_key)
        method = await db.get_payment_method(purchase["payment_method_id"])
        if method and method.get("secret_key"):
            signature = request.headers.get("Sign", "")
            #f not payments.ProdamusProvider.verify_signature(body, method["secret_key"], signature):
                #rint(f"  [webhook] Неверная подпись для order_id={order_id}")
               #return web.Response(status=403, text="Invalid signature")

        # Активируем
        await db.add_user_log(purchase["user_id"], "Оплатил (webhook Prodamus)")
        await _activate_purchase(bot, purchase)
        print(f"  [webhook] ✅ Платёж order_id={order_id} user={purchase['user_id']} — активирован")

    except Exception as e:
        logger.exception("[webhook] Ошибка обработки: %s", e)

    return web.Response(text="OK")


_webhook_runner: web.AppRunner | None = None


async def start_webhook_server(bot: MaxBot) -> None:
    """Запускает HTTP-сервер для приёма webhook-ов."""
    global _webhook_runner
    app = web.Application()
    app["bot"] = bot
    app.router.add_post("/prodamus/webhook", handle_prodamus_webhook)
    app.router.add_post("/prodamus/webhook/{tail:.*}", handle_prodamus_webhook)
    app.router.add_get("/prodamus/webhook", lambda r: web.Response(text="OK"))
    app.router.add_get("/prodamus/webhook/{tail:.*}", lambda r: web.Response(text="OK"))

    _webhook_runner = web.AppRunner(app)
    await _webhook_runner.setup()
    site = web.TCPSite(_webhook_runner, WEBHOOK_HOST, WEBHOOK_PORT)
    await site.start()
    print(f"🌐 Webhook-сервер запущен на {WEBHOOK_HOST}:{WEBHOOK_PORT}")
    if WEBHOOK_BASE_URL:
        print(f"   URL для Prodamus: {WEBHOOK_BASE_URL}/prodamus/webhook")


async def shutdown(bot: MaxBot):
    """Корректное завершение: закрываем сессии и сервер."""
    print("\n🔴 Завершение работы...")
    await bot.stop()
    if _webhook_runner:
        await _webhook_runner.cleanup()
    await db.close_db()
    print("✅ Все соединения закрыты.")


async def main():
    # Инициализация PostgreSQL
    await db.init_db()
    print("✅ БД инициализирована")

    bot = MaxBot(BOT_TOKEN)
    await bot.start()

    # Проверяем бота
    me = await bot.get_me()
    name = me.get("first_name", "?")
    print(f"✅ Бот: {name} (@{me.get('username', '?')})")

    # Удаляем webhook-и
    await bot.cleanup_webhooks()

    # Запускаем webhook-сервер
    await start_webhook_server(bot)

    print("🟢 Polling запущен. Отправь /start боту в MAX.")
    print(f"🔄 Проверка подписок каждые {EXPIRY_CHECK_INTERVAL}с, платежей каждые {PAYMENT_CHECK_INTERVAL}с\n")

    try:
        await asyncio.gather(
            polling_loop(bot),
            check_expired_subscriptions(bot),
            check_pending_payments(bot),
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