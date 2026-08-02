import asyncio
from datetime import timedelta

from max_client import MaxBot
import config as cfg
import database as db
import payments
from handlers import _activate_purchase
from utils import build_inline_keyboard, parse_duration_to_minutes


EXPIRY_CHECK_INTERVAL = getattr(cfg, "EXPIRY_CHECK_INTERVAL", 60)
PAYMENT_CHECK_INTERVAL = getattr(cfg, "PAYMENT_CHECK_INTERVAL", 15)
WARMUP_CHECK_INTERVAL = getattr(cfg, "WARMUP_CHECK_INTERVAL", 60)


async def check_expired_subscriptions(bot: MaxBot):
    """Фоновая задача: проверяет истёкшие подписки,
    удаляет пользователей из ресурсов тарифа и уведомляет их."""
    while True:
        try:
            missing = await db.get_active_purchases_missing_expiry()
            for p in missing:
                expires_at = None
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
                        dm2 = parse_duration_to_minutes(p.get("duration_text") or "")
                        if dm2 and dm2 > 0:
                            expires_at = base + timedelta(minutes=dm2)
                if expires_at:
                    await db.set_purchase_expires_at(p["id"], expires_at)

            expired = await db.get_expired_purchases()
            for p in expired:
                user_id = p["user_id"]
                tariff_id = p["tariff_id"]
                tariff_name = p["tariff_name"]

                resources = await db.get_tariff_resources(tariff_id)
                for res in resources:
                    chat_id = res["chat_id"]
                    ok = await bot.remove_chat_member(chat_id, user_id)
                    if ok:
                        print(f"  [expiry] Удалён user={user_id} из chat={chat_id} (тариф «{tariff_name}»)")
                    else:
                        print(f"  [expiry] Не удалось удалить user={user_id} из chat={chat_id}")

                await db.mark_purchase_expired(p["id"])

                notify_text = await db.get_bot_text("subscription_end", user_id=user_id, tariff_name=tariff_name)
                try:
                    await bot.send_message(
                        user_id,
                        notify_text,
                    )
                except Exception:
                    pass

                print(f"  [expiry] Подписка #{p['id']} user={user_id} «{tariff_name}» — expired")

            if expired:
                print(f"  [expiry] Обработано {len(expired)} истёкших подписок")

            expired_tariffs = await db.get_active_tariffs_with_expired_end_date()
            for tariff in expired_tariffs:
                tariff_id = tariff["id"]
                tariff_name = tariff["name"]

                purchases = await db.get_active_purchases_by_tariff(tariff_id)
                resources = await db.get_tariff_resources(tariff_id)
                for p in purchases:
                    uid = p["user_id"]
                    for res in resources:
                        ok = await bot.remove_chat_member(res["chat_id"], uid)
                        if ok:
                            print(f"  [end_date] Удалён user={uid} из chat={res['chat_id']} (тариф «{tariff_name}»)")
                    await db.mark_purchase_expired(p["id"])
                    notify_text = await db.get_bot_text("subscription_end", user_id=uid, tariff_name=tariff_name)
                    try:
                        await bot.send_message(uid, notify_text)
                    except Exception:
                        pass

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
                    if await _activate_purchase(bot, p):
                        await db.add_user_log(p["user_id"], "Оплатил")
                        print(f"  [payment] ✅ Платёж #{p['id']} user={p['user_id']} — оплачен")

                elif status == "canceled":
                    await db.add_user_log(p["user_id"], "Не оплатил (отмена)")
                    await db.cancel_purchase(p["id"])
                    try:
                        failed_text = await db.get_bot_text("payment_failed", user_id=p["user_id"])
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

async def check_warmup_messages(bot: MaxBot):
    """Фоновая задача: отправляет догревающие сообщения пользователям,
    которые начали оплату тарифа (purchase.status='pending'), но не завершили её."""
    while True:
        try:
            no_plan = await db.get_pending_purchases_without_plan()
            for p in no_plan:
                await db.ensure_warmup_plan(p["purchase_id"], p["tariff_id"])

            due_sends = await db.get_due_warmup_sends()

            for send in due_sends:
                purchase_id = send["purchase_id"]
                user_id = send["user_id"]

                current_status = await db.get_purchase_status(purchase_id)
                if current_status != "pending":
                    continue

                sent = False
                try:
                    warmup_buttons = send.get("buttons") or []
                    warmup_keyboard = build_inline_keyboard(warmup_buttons) if warmup_buttons else None
                    if send["media_url"]:
                        await bot.forward_attachment(
                            user_id, "image", send["media_url"], text=send["message_text"], keyboard=warmup_keyboard,
                        )
                    else:
                        await bot.send_message(user_id, send["message_text"], keyboard=warmup_keyboard)
                    sent = True
                    print(f"  [warmup] ✅ Отправлено purchase=#{purchase_id} user={user_id}")
                except Exception as e:
                    print(f"  [warmup] ❌ Ошибка отправки purchase=#{purchase_id}: {e}")

                if sent:
                    await db.mark_warmup_sent(purchase_id, send["message_id"])

        except Exception as e:
            print(f"  [warmup] Ошибка: {e}")

        await asyncio.sleep(WARMUP_CHECK_INTERVAL)
