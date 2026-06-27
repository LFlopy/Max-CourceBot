"""PostgreSQL: пул соединений + CRUD для тарифов, категорий, ресурсов, пользователей, покупок."""

import asyncpg
from config import DATABASE_URL
from utils import build_user_name, build_user_template_context, format_template

pool: asyncpg.Pool | None = None


# ── Инициализация ─────────────────────────────────────────────

async def init_db():
    global pool
    pool = await asyncpg.create_pool(DATABASE_URL)
    await _create_tables()


async def close_db():
    if pool:
        await pool.close()


async def _create_tables():
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS categories (
                id          SERIAL PRIMARY KEY,
                name        VARCHAR(255) NOT NULL,
                position    INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS tariffs (
                id                      SERIAL PRIMARY KEY,
                name                    VARCHAR(255) NOT NULL,
                price                   NUMERIC(10,2) DEFAULT 0,
                old_price               NUMERIC(10,2),
                renewal_price           NUMERIC(10,2),
                active_renewal_price    NUMERIC(10,2),
                duration_days           INTEGER,
                duration_text           VARCHAR(100),
                is_free                 BOOLEAN DEFAULT FALSE,
                is_active               BOOLEAN DEFAULT TRUE,
                description             TEXT DEFAULT '',
                media_url               TEXT,
                category_id             INTEGER REFERENCES categories(id) ON DELETE SET NULL,
                position                INTEGER DEFAULT 0,
                start_date              TIMESTAMP,
                end_date                TIMESTAMP,
                start_day               INTEGER,
                check_name              VARCHAR(255),
                rejection_interval      INTEGER,
                success_text            TEXT,
                activation_limit        INTEGER,
                allowed_group           TEXT,
                show_price_in_name      BOOLEAN DEFAULT FALSE,
                payment_link            TEXT,
                channel_link            TEXT,
                created_at              TIMESTAMP DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS tariff_resources (
                id          SERIAL PRIMARY KEY,
                tariff_id   INTEGER REFERENCES tariffs(id) ON DELETE CASCADE,
                chat_id     BIGINT NOT NULL,
                chat_title  VARCHAR(255),
                invite_link TEXT
            );

            CREATE TABLE IF NOT EXISTS users (
                id              SERIAL PRIMARY KEY,
                user_id         BIGINT UNIQUE NOT NULL,
                first_name      VARCHAR(255) DEFAULT '',
                last_name       VARCHAR(255) DEFAULT '',
                username        VARCHAR(255) DEFAULT '',
                phone           VARCHAR(50) DEFAULT '',
                is_banned       BOOLEAN DEFAULT FALSE,
                first_seen      TIMESTAMP DEFAULT NOW(),
                last_active     TIMESTAMP DEFAULT NOW()
            );

            -- миграции
            ALTER TABLE users ADD COLUMN IF NOT EXISTS is_banned BOOLEAN DEFAULT FALSE;
            ALTER TABLE users ADD COLUMN IF NOT EXISTS phone VARCHAR(50) DEFAULT '';

            CREATE TABLE IF NOT EXISTS purchases (
                id              SERIAL PRIMARY KEY,
                user_id         BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                tariff_id       INTEGER NOT NULL REFERENCES tariffs(id) ON DELETE CASCADE,
                price_paid      NUMERIC(10,2) DEFAULT 0,
                is_free         BOOLEAN DEFAULT FALSE,
                status          VARCHAR(50) DEFAULT 'pending',
                purchased_at    TIMESTAMP DEFAULT NOW(),
                expires_at      TIMESTAMP,
                activated_at    TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS bot_texts (
                id          SERIAL PRIMARY KEY,
                key         VARCHAR(100) UNIQUE NOT NULL,
                text        TEXT NOT NULL,
                updated_at  TIMESTAMP DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS promo_codes (
                id                  SERIAL PRIMARY KEY,
                code                VARCHAR(100) UNIQUE NOT NULL,
                discount_percent    INTEGER NOT NULL,
                max_activations     INTEGER DEFAULT 0,
                max_per_user        INTEGER DEFAULT 1,
                expires_at          TIMESTAMP,
                promo_type          VARCHAR(50) DEFAULT 'general',
                allowed_tariffs     TEXT,
                allowed_group       TEXT,
                allowed_users       TEXT,
                created_at          TIMESTAMP DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS promo_activations (
                id              SERIAL PRIMARY KEY,
                promo_id        INTEGER REFERENCES promo_codes(id) ON DELETE CASCADE,
                user_id         BIGINT NOT NULL,
                tariff_id       INTEGER REFERENCES tariffs(id) ON DELETE SET NULL,
                paid            BOOLEAN DEFAULT FALSE,
                activated_at    TIMESTAMP DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS payment_methods (
                id          SERIAL PRIMARY KEY,
                name        VARCHAR(100) NOT NULL,
                provider    VARCHAR(50) NOT NULL,
                shop_id     VARCHAR(255) DEFAULT '',
                secret_key  VARCHAR(255) DEFAULT '',
                is_active   BOOLEAN DEFAULT TRUE,
                created_at  TIMESTAMP DEFAULT NOW()
            );

            -- 🎁 Гифт файлы
            CREATE TABLE IF NOT EXISTS gift_files (
                id          SERIAL PRIMARY KEY,
                file_token  TEXT NOT NULL,
                file_name   TEXT DEFAULT '',
                created_at  TIMESTAMP DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS gift_file_tariffs (
                id          SERIAL PRIMARY KEY,
                gift_id     INTEGER NOT NULL REFERENCES gift_files(id) ON DELETE CASCADE,
                tariff_id   INTEGER NOT NULL REFERENCES tariffs(id) ON DELETE CASCADE
            );

            -- миграции tariffs
            ALTER TABLE tariffs ADD COLUMN IF NOT EXISTS duration_minutes INTEGER;

            -- миграция типов курсов:
            -- Тип 1 (марафон, end_date): сбрасываем duration, чтобы поля не конфликтовали
            UPDATE tariffs
            SET duration_days = NULL, duration_minutes = NULL, duration_text = ''
            WHERE end_date IS NOT NULL
              AND (duration_days IS NOT NULL OR duration_minutes IS NOT NULL);

            -- миграции tariff_resources
            ALTER TABLE tariff_resources ADD COLUMN IF NOT EXISTS invite_link TEXT;

            -- миграции purchases
            ALTER TABLE purchases ADD COLUMN IF NOT EXISTS payment_id VARCHAR(255);
            ALTER TABLE purchases ADD COLUMN IF NOT EXISTS payment_method_id INTEGER;
            ALTER TABLE purchases ADD COLUMN IF NOT EXISTS promo_id INTEGER;
            ALTER TABLE purchases ADD COLUMN IF NOT EXISTS original_price NUMERIC(10,2);

            CREATE TABLE IF NOT EXISTS user_logs (
                id          SERIAL PRIMARY KEY,
                user_id     BIGINT NOT NULL,
                action      TEXT NOT NULL,
                created_at  TIMESTAMP DEFAULT NOW()
            );

            -- согласие с офертой и политикой конфиденциальности
            ALTER TABLE users ADD COLUMN IF NOT EXISTS terms_agreed BOOLEAN DEFAULT FALSE;
        """)


# ── Гифт файлы ─────────────────────────────────────────────────

async def create_gift_file(file_token: str, file_name: str, tariff_ids: list[int]) -> dict | None:
    """Создаёт гифт файл и привязывает к тарифам."""
    if not file_token:
        return None
    tariff_ids = [int(t) for t in tariff_ids if int(t) > 0]
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "INSERT INTO gift_files (file_token, file_name) VALUES ($1, $2) RETURNING *",
            file_token, file_name or "",
        )
        if not row:
            return None
        gift_id = row["id"]
        for tid in tariff_ids:
            await conn.execute(
                "INSERT INTO gift_file_tariffs (gift_id, tariff_id) VALUES ($1, $2)",
                gift_id, tid,
            )
        return dict(row)


async def get_gift_files_for_tariff(tariff_id: int) -> list[dict]:
    """Возвращает гифт файлы, привязанные к конкретному тарифу."""
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT gf.id, gf.file_token, gf.file_name, gf.created_at
            FROM gift_files gf
            JOIN gift_file_tariffs gft ON gft.gift_id = gf.id
            WHERE gft.tariff_id = $1
            ORDER BY gf.created_at DESC, gf.id DESC
        """, tariff_id)
        return [dict(r) for r in rows]


async def delete_gift_file(gift_id: int):
    """Удаляет гифт файл (каскадно удаляет привязки к тарифам)."""
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM gift_files WHERE id = $1", gift_id)


async def get_gift_files_for_tariffs(tariff_ids: list[int]) -> list[dict]:
    """Возвращает гифт файлы, привязанные к любому из tariff_ids."""
    tariff_ids = [int(t) for t in tariff_ids if int(t) > 0]
    if not tariff_ids:
        return []
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT DISTINCT gf.id, gf.file_token, gf.file_name, gf.created_at
            FROM gift_files gf
            JOIN gift_file_tariffs gft ON gft.gift_id = gf.id
            WHERE gft.tariff_id = ANY($1::int[])
            ORDER BY gf.created_at DESC, gf.id DESC
        """, tariff_ids)
        return [dict(r) for r in rows]


# ── Тарифы ────────────────────────────────────────────────────

async def create_tariff(
    name: str,
    price: float = 0,
    is_free: bool = False,
    duration_days: int | None = None,
    duration_minutes: int | None = None,
    duration_text: str = "",
) -> dict:
    async with pool.acquire() as conn:
        # position = max + 1
        max_pos = await conn.fetchval(
            "SELECT COALESCE(MAX(position), 0) FROM tariffs"
        )
        row = await conn.fetchrow("""
            INSERT INTO tariffs (name, price, is_free, duration_days, duration_minutes, duration_text, position)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            RETURNING *
        """, name, price, is_free, duration_days, duration_minutes, duration_text, max_pos + 1)
        return dict(row)


async def get_tariff(tariff_id: int) -> dict | None:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM tariffs WHERE id = $1", tariff_id)
        return dict(row) if row else None


async def list_tariffs() -> list[dict]:
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM tariffs ORDER BY position, id")
        return [dict(r) for r in rows]


async def get_active_tariffs_with_expired_end_date() -> list[dict]:
    """Тарифы, у которых end_date уже прошёл, но is_active=True (нужно деактивировать)."""
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT id, name FROM tariffs
            WHERE is_active = TRUE
              AND end_date IS NOT NULL
              AND end_date <= NOW()
        """)
        return [dict(r) for r in rows]


async def get_active_purchases_by_tariff(tariff_id: int) -> list[dict]:
    """Все активные покупки тарифа (для принудительного завершения)."""
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT p.id, p.user_id, t.name AS tariff_name
            FROM purchases p
            JOIN tariffs t ON t.id = p.tariff_id
            WHERE p.tariff_id = $1 AND p.status = 'active'
        """, tariff_id)
        return [dict(r) for r in rows]


async def update_tariff(tariff_id: int, **fields) -> dict | None:
    if not fields:
        return await get_tariff(tariff_id)
    sets = []
    vals = []
    for i, (k, v) in enumerate(fields.items(), start=2):
        sets.append(f"{k} = ${i}")
        vals.append(v)
    sql = f"UPDATE tariffs SET {', '.join(sets)} WHERE id = $1 RETURNING *"
    async with pool.acquire() as conn:
        row = await conn.fetchrow(sql, tariff_id, *vals)
        return dict(row) if row else None


async def delete_tariff(tariff_id: int):
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM tariffs WHERE id = $1", tariff_id)


async def swap_tariff_positions(id_a: int, id_b: int):
    """Меняет позиции двух тарифов местами."""
    async with pool.acquire() as conn:
        a = await conn.fetchrow("SELECT position FROM tariffs WHERE id = $1", id_a)
        b = await conn.fetchrow("SELECT position FROM tariffs WHERE id = $1", id_b)
        if a and b:
            await conn.execute("UPDATE tariffs SET position = $1 WHERE id = $2", b["position"], id_a)
            await conn.execute("UPDATE tariffs SET position = $1 WHERE id = $2", a["position"], id_b)


async def move_tariff_up(tariff_id: int):
    """Поднимает тариф на одну позицию вверх."""
    tariffs = await list_tariffs()
    for i, t in enumerate(tariffs):
        if t["id"] == tariff_id and i > 0:
            await swap_tariff_positions(tariff_id, tariffs[i - 1]["id"])
            break


async def move_tariff_down(tariff_id: int):
    """Опускает тариф на одну позицию вниз."""
    tariffs = await list_tariffs()
    for i, t in enumerate(tariffs):
        if t["id"] == tariff_id and i < len(tariffs) - 1:
            await swap_tariff_positions(tariff_id, tariffs[i + 1]["id"])
            break


# ── Категории ─────────────────────────────────────────────────

async def create_category(name: str) -> dict:
    async with pool.acquire() as conn:
        max_pos = await conn.fetchval(
            "SELECT COALESCE(MAX(position), 0) FROM categories"
        )
        row = await conn.fetchrow(
            "INSERT INTO categories (name, position) VALUES ($1, $2) RETURNING *",
            name, max_pos + 1,
        )
        return dict(row)


async def list_categories() -> list[dict]:
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM categories ORDER BY position, id")
        return [dict(r) for r in rows]


async def get_category(cat_id: int) -> dict | None:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM categories WHERE id = $1", cat_id)
        return dict(row) if row else None


async def delete_category(cat_id: int):
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM categories WHERE id = $1", cat_id)


# ── Ресурсы тарифа ────────────────────────────────────────────

async def set_tariff_resources(tariff_id: int, resources: list[dict]):
    """Перезаписывает ресурсы тарифа. resources = [{chat_id, chat_title, invite_link}, ...]"""
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM tariff_resources WHERE tariff_id = $1", tariff_id)
        for r in resources:
            await conn.execute(
                "INSERT INTO tariff_resources (tariff_id, chat_id, chat_title, invite_link) VALUES ($1, $2, $3, $4)",
                tariff_id, r["chat_id"], r.get("chat_title", ""), r.get("invite_link", ""),
            )


async def get_tariff_resources(tariff_id: int) -> list[dict]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM tariff_resources WHERE tariff_id = $1", tariff_id
        )
        return [dict(r) for r in rows]


async def get_resource_usage() -> dict[int, list[str]]:
    """Возвращает {chat_id: [tariff_name, ...]} — какие тарифы используют каждый ресурс."""
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT tr.chat_id, t.name AS tariff_name
            FROM tariff_resources tr
            JOIN tariffs t ON t.id = tr.tariff_id
            ORDER BY tr.chat_id
        """)
        usage: dict[int, list[str]] = {}
        for r in rows:
            usage.setdefault(r["chat_id"], []).append(r["tariff_name"])
        return usage


async def delete_resource_from_all_tariffs(chat_id: int):
    """Удаляет ресурс (чат) из всех тарифов."""
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM tariff_resources WHERE chat_id = $1", chat_id
        )


# ── Пользователи ───────────────────────────────────────────────

async def upsert_user(user_id: int, first_name: str = "",
                      last_name: str = "", username: str = "") -> dict:
    """Создаёт или обновляет пользователя (last_active обновляется всегда)."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO users (user_id, first_name, last_name, username)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (user_id) DO UPDATE
                SET first_name  = EXCLUDED.first_name,
                    last_name   = EXCLUDED.last_name,
                    username    = EXCLUDED.username,
                    last_active = NOW()
            RETURNING *
        """, user_id, first_name, last_name, username)
        return dict(row)


async def get_user(user_id: int) -> dict | None:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)
        return dict(row) if row else None


async def count_users() -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval("SELECT COUNT(*) FROM users")


async def ban_user(user_id: int):
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET is_banned = TRUE WHERE user_id = $1", user_id
        )


async def unban_user(user_id: int):
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET is_banned = FALSE WHERE user_id = $1", user_id
        )


async def save_user_phone(user_id: int, phone: str):
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET phone = $2 WHERE user_id = $1", user_id, phone
        )


async def has_terms_agreed(user_id: int) -> bool:
    async with pool.acquire() as conn:
        return bool(await conn.fetchval(
            "SELECT terms_agreed FROM users WHERE user_id = $1", user_id
        ))


async def set_terms_agreed(user_id: int):
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET terms_agreed = TRUE WHERE user_id = $1", user_id
        )


async def is_user_banned(user_id: int) -> bool:
    async with pool.acquire() as conn:
        val = await conn.fetchval(
            "SELECT is_banned FROM users WHERE user_id = $1", user_id
        )
        return bool(val)


# ── Группы пользователей (для рассылки) ───────────────────────

async def get_all_user_ids() -> list[int]:
    """Все пользователи."""
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT user_id FROM users WHERE is_banned = FALSE")
        return [r["user_id"] for r in rows]


async def get_paid_user_ids() -> list[int]:
    """Пользователи, оплатившие хотя бы один тариф."""
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT DISTINCT u.user_id FROM users u
            JOIN purchases p ON p.user_id = u.user_id
            WHERE p.status = 'active' AND u.is_banned = FALSE
        """)
        return [r["user_id"] for r in rows]


async def get_no_sub_user_ids() -> list[int]:
    """Пользователи без единой покупки."""
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT u.user_id FROM users u
            LEFT JOIN purchases p ON p.user_id = u.user_id
            WHERE p.id IS NULL AND u.is_banned = FALSE
        """)
        return [r["user_id"] for r in rows]


async def get_no_paid_sub_user_ids() -> list[int]:
    """Пользователи без активных платных подписок (нет активных покупок на платные тарифы)."""
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT u.user_id FROM users u
            WHERE u.is_banned = FALSE
              AND u.user_id NOT IN (
                  SELECT DISTINCT p.user_id FROM purchases p
                  JOIN tariffs t ON t.id = p.tariff_id
                  WHERE p.status = 'active' AND t.is_free = FALSE
              )
        """)
        return [r["user_id"] for r in rows]


async def get_pending_user_ids() -> list[int]:
    """Пользователи с pending-покупками (начали, но не оплатили)."""
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT DISTINCT u.user_id FROM users u
            JOIN purchases p ON p.user_id = u.user_id
            WHERE p.status = 'pending' AND u.is_banned = FALSE
              AND u.user_id NOT IN (
                  SELECT user_id FROM purchases WHERE status = 'active'
              )
        """)
        return [r["user_id"] for r in rows]


async def get_tariff_user_ids(tariff_id: int) -> list[int]:
    """Пользователи с активной подпиской на конкретный тариф."""
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT DISTINCT u.user_id FROM users u
            JOIN purchases p ON p.user_id = u.user_id
            WHERE p.tariff_id = $1 AND p.status = 'active'
              AND (p.expires_at IS NULL OR p.expires_at > NOW())
              AND u.is_banned = FALSE
        """, tariff_id)
        return [r["user_id"] for r in rows]


# ── Покупки ────────────────────────────────────────────────────

async def create_purchase(user_id: int, tariff_id: int,
                          price_paid: float = 0, is_free: bool = False,
                          expires_at=None) -> dict:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO purchases (user_id, tariff_id, price_paid, is_free,
                                   status, purchased_at, expires_at)
            VALUES ($1, $2, $3, $4, $5, NOW(), $6)
            RETURNING *
        """, user_id, tariff_id, price_paid, is_free,
            "active" if is_free else "pending", expires_at)
        return dict(row)


async def activate_purchase(purchase_id: int) -> dict | None:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            UPDATE purchases SET status = 'active', activated_at = NOW()
            WHERE id = $1 RETURNING *
        """, purchase_id)
        return dict(row) if row else None


async def get_user_purchases(user_id: int) -> list[dict]:
    """Все покупки пользователя с названием тарифа."""
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT p.*, t.name AS tariff_name
            FROM purchases p
            JOIN tariffs t ON t.id = p.tariff_id
            WHERE p.user_id = $1
            ORDER BY p.purchased_at DESC
        """, user_id)
        return [dict(r) for r in rows]


async def get_active_subscriptions(user_id: int) -> list[dict]:
    """Активные подписки пользователя (не истёкшие)."""
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT p.*, t.name AS tariff_name,
                   t.end_date AS tariff_end_date,
                   t.duration_days AS tariff_duration_days
            FROM purchases p
            JOIN tariffs t ON t.id = p.tariff_id
            WHERE p.user_id = $1
              AND p.status = 'active'
              AND (p.expires_at IS NULL OR p.expires_at > NOW())
            ORDER BY p.purchased_at DESC
        """, user_id)
        return [dict(r) for r in rows]


async def get_active_subscriptions_with_resources(user_id: int) -> list[dict]:
    """Активные подписки с ресурсами (invite_link) для каждой."""
    subs = await get_active_subscriptions(user_id)
    for s in subs:
        s["resources"] = await get_tariff_resources(s["tariff_id"])
    return subs


async def get_pending_subscriptions(user_id: int) -> list[dict]:
    """Покупки пользователя в статусе pending (оплата не подтверждена)."""
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT p.id, p.user_id, p.tariff_id, p.price_paid,
                   p.purchased_at, p.payment_id,
                   t.name AS tariff_name
            FROM purchases p
            JOIN tariffs t ON t.id = p.tariff_id
            WHERE p.user_id = $1
              AND p.status = 'pending'
            ORDER BY p.purchased_at DESC
        """, user_id)
        return [dict(r) for r in rows]


async def get_active_tariff_ids(user_id: int) -> set[int]:
    """Возвращает set id тарифов, на которые у пользователя есть активная подписка."""
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT DISTINCT tariff_id FROM purchases
            WHERE user_id = $1
              AND status = 'active'
              AND (expires_at IS NULL OR expires_at > NOW())
        """, user_id)
        return {r["tariff_id"] for r in rows}


async def get_unlocked_tariff_ids(user_id: int) -> set[int]:
    """Р’РѕР·РІСЂР°С‰Р°РµС‚ set id С‚Р°СЂРёС„РѕРІ, РєРѕС‚РѕСЂС‹Рµ СѓР¶Рµ РєРѕРіРґР°-С‚Рѕ Р±С‹Р»Рё Р°РєС‚РёРІРЅС‹ Сѓ РїРѕР»СЊР·РѕРІР°С‚РµР»СЏ."""
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT DISTINCT tariff_id FROM purchases
            WHERE user_id = $1
              AND status IN ('active', 'expired')
        """, user_id)
        return {r["tariff_id"] for r in rows}


async def get_expired_purchases() -> list[dict]:
    """Покупки со статусом 'active', у которых expires_at уже прошёл.
    Возвращает purchase + tariff_name + user_id для обработки."""
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT p.id, p.user_id, p.tariff_id, p.expires_at,
                   t.name AS tariff_name
            FROM purchases p
            JOIN tariffs t ON t.id = p.tariff_id
            WHERE p.status = 'active'
              AND p.expires_at IS NOT NULL
              AND p.expires_at <= NOW()
        """)
        return [dict(r) for r in rows]


async def mark_purchase_expired(purchase_id: int):
    """Помечает покупку как expired (обработана)."""
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE purchases SET status = 'expired' WHERE id = $1", purchase_id
        )


async def set_purchase_expires_at(purchase_id: int, expires_at):
    """Проставляет expires_at у покупки (без смены статуса)."""
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE purchases SET expires_at = $2 WHERE id = $1", purchase_id, expires_at
        )


async def update_active_purchases_expiry(tariff_id: int, expires_at):
    """Обновляет expires_at у всех активных покупок данного тарифа."""
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE purchases SET expires_at = $2 WHERE tariff_id = $1 AND status = 'active'",
            tariff_id, expires_at,
        )


async def get_active_purchases_missing_expiry() -> list[dict]:
    """Активные покупки без expires_at (нужно дозаполнить по длительности тарифа)."""
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT p.id, p.user_id, p.tariff_id, p.purchased_at, p.activated_at,
                   t.name AS tariff_name, t.duration_days, t.duration_minutes, t.duration_text,
                   t.end_date AS tariff_end_date
            FROM purchases p
            JOIN tariffs t ON t.id = p.tariff_id
            WHERE p.status = 'active'
              AND p.expires_at IS NULL
        """)
        return [dict(r) for r in rows]


def filter_tariffs_by_allowed_group(tariffs: list[dict], access_tariff_ids: set[int]) -> list[dict]:
    """Фильтрует тарифы: оставляет те, у которых allowed_group пуст
    или пользователь имеет подписку на один из тарифов из allowed_group."""
    result = []
    for t in tariffs:
        ag = t.get("allowed_group")
        if not ag:
            result.append(t)
            continue
        required_ids = {int(x) for x in ag.split(",") if x.strip()}
        if required_ids & access_tariff_ids:
            result.append(t)
    return result


# ── Статистика ─────────────────────────────────────────────────

async def stats_summary() -> dict:
    """Общая статистика для админ-панели."""
    async with pool.acquire() as conn:
        total_users = await conn.fetchval("SELECT COUNT(*) FROM users")
        new_users_30d = await conn.fetchval(
            "SELECT COUNT(*) FROM users WHERE first_seen >= NOW() - INTERVAL '30 days'"
        )
        total_purchases = await conn.fetchval(
            "SELECT COUNT(*) FROM purchases WHERE status = 'active'"
        )
        purchases_30d = await conn.fetchval(
            "SELECT COUNT(*) FROM purchases WHERE purchased_at >= NOW() - INTERVAL '30 days'"
        )
        revenue_30d = await conn.fetchval(
            "SELECT COALESCE(SUM(price_paid), 0) FROM purchases "
            "WHERE status = 'active' AND purchased_at >= NOW() - INTERVAL '30 days'"
        )
        return {
            "total_users": total_users,
            "new_users_30d": new_users_30d,
            "total_purchases": total_purchases,
            "purchases_30d": purchases_30d,
            "revenue_30d": float(revenue_30d),
        }


async def tariff_purchase_count(tariff_id: int) -> int:
    """Количество покупок конкретного тарифа."""
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT COUNT(*) FROM purchases WHERE tariff_id = $1 AND status = 'active'",
            tariff_id,
        )


# ── Расширенная статистика подписчиков ─────────────────────────

async def subscribers_stats() -> dict:
    """Статистика для раздела «Подписчики»."""
    async with pool.acquire() as conn:
        total_users = await conn.fetchval("SELECT COUNT(*) FROM users")
        active_subs = await conn.fetchval(
            "SELECT COUNT(DISTINCT user_id) FROM purchases "
            "WHERE status = 'active' AND (expires_at IS NULL OR expires_at > NOW())"
        )
        expired = await conn.fetchval(
            "SELECT COUNT(DISTINCT user_id) FROM purchases "
            "WHERE status = 'active' AND expires_at IS NOT NULL AND expires_at <= NOW()"
        )
        bought = await conn.fetchval(
            "SELECT COUNT(DISTINCT user_id) FROM purchases"
        )
        never_bought = total_users - bought
        return {
            "total_users": total_users,
            "active_subs": active_subs,
            "expired": expired,
            "bought": bought,
            "never_bought": never_bought,
        }


async def user_profile(user_id: int) -> dict | None:
    """Профиль пользователя со статистикой покупок."""
    async with pool.acquire() as conn:
        user = await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)
        if not user:
            return None
        purchases = await conn.fetch("""
            SELECT p.*, t.name AS tariff_name
            FROM purchases p
            JOIN tariffs t ON t.id = p.tariff_id
            WHERE p.user_id = $1
            ORDER BY p.purchased_at DESC
        """, user_id)
        total_paid = await conn.fetchval(
            "SELECT COALESCE(SUM(price_paid), 0) FROM purchases WHERE user_id = $1",
            user_id,
        )
        count = len(purchases)
        avg_check = float(total_paid) / count if count > 0 else 0
        return {
            **dict(user),
            "purchases": [dict(p) for p in purchases],
            "total_count": count,
            "total_paid": float(total_paid),
            "avg_check": avg_check,
        }


async def all_users_with_purchases() -> list[dict]:
    """Все пользователи с детальной информацией (для xlsx)."""
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT u.user_id, u.first_name, u.last_name, u.phone,
                   COUNT(p.id) AS purchase_count,
                   COALESCE(SUM(p.price_paid), 0) AS total_paid,
                   STRING_AGG(
                       DISTINCT t.name || CASE
                           WHEN p.status = 'active'
                                AND (p.expires_at IS NULL OR p.expires_at > NOW())
                           THEN ' ✅'
                           ELSE ' ❌'
                       END,
                       ', ' ORDER BY t.name || CASE
                           WHEN p.status = 'active'
                                AND (p.expires_at IS NULL OR p.expires_at > NOW())
                           THEN ' ✅'
                           ELSE ' ❌'
                       END
                   ) AS purchases
            FROM users u
            LEFT JOIN purchases p ON p.user_id = u.user_id
            LEFT JOIN tariffs t ON t.id = p.tariff_id
            GROUP BY u.user_id, u.first_name, u.last_name, u.phone
            ORDER BY total_paid DESC
        """)
        return [dict(r) for r in rows]


async def tariff_subscribers() -> list[dict]:
    """Активные подписчики по тарифам (для xlsx «Список подписчиков»)."""
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT t.name AS tariff_name, t.price AS tariff_price,
                   u.user_id, u.first_name, u.last_name,
                   u.phone, p.purchased_at, p.expires_at, p.price_paid
            FROM purchases p
            JOIN tariffs t ON t.id = p.tariff_id
            JOIN users u ON u.user_id = p.user_id
            WHERE p.status = 'active'
              AND (p.expires_at IS NULL OR p.expires_at > NOW())
            ORDER BY t.name, u.last_name, u.first_name
        """)
        return [dict(r) for r in rows]


async def tariff_expired_subscribers() -> list[dict]:
    """Подписчики с истёкшими подписками (для xlsx «Список не продливших»)."""
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT t.name AS tariff_name, u.user_id, u.first_name, u.last_name,
                   u.phone, p.purchased_at, p.expires_at
            FROM purchases p
            JOIN tariffs t ON t.id = p.tariff_id
            JOIN users u ON u.user_id = p.user_id
            WHERE p.status = 'active'
              AND p.expires_at IS NOT NULL
              AND p.expires_at <= NOW()
              AND u.user_id NOT IN (
                  SELECT p2.user_id FROM purchases p2
                  WHERE p2.tariff_id = p.tariff_id
                    AND p2.status = 'active'
                    AND (p2.expires_at IS NULL OR p2.expires_at > NOW())
              )
            ORDER BY t.name, p.expires_at DESC
        """)
        return [dict(r) for r in rows]


async def grant_subscription(user_id: int, tariff_id: int, expires_at=None) -> dict:
    """Выдать подписку пользователю (бесплатно, от админа)."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO purchases (user_id, tariff_id, price_paid, is_free,
                                   status, purchased_at, activated_at, expires_at)
            VALUES ($1, $2, 0, TRUE, 'active', NOW(), NOW(), $3)
            RETURNING *
        """, user_id, tariff_id, expires_at)
        return dict(row)


async def revoke_subscription(user_id: int, tariff_id: int):
    """Обнулить (отменить) подписку."""
    async with pool.acquire() as conn:
        await conn.execute("""
            UPDATE purchases SET status = 'revoked'
            WHERE user_id = $1 AND tariff_id = $2 AND status = 'active'
        """, user_id, tariff_id)


async def transfer_subscription(from_user: int, to_user: int, tariff_id: int):
    """Передать подписку от одного пользователя другому."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT id, expires_at FROM purchases
            WHERE user_id = $1 AND tariff_id = $2 AND status = 'active'
            ORDER BY purchased_at DESC LIMIT 1
        """, from_user, tariff_id)
        if not row:
            return False
        await conn.execute(
            "UPDATE purchases SET status = 'transferred' WHERE id = $1", row["id"]
        )
        await conn.execute("""
            INSERT INTO purchases (user_id, tariff_id, price_paid, is_free,
                                   status, purchased_at, activated_at, expires_at)
            VALUES ($1, $2, 0, TRUE, 'active', NOW(), NOW(), $3)
        """, to_user, tariff_id, row["expires_at"])
        return True


# ── Тексты бота ───────────────────────────────────────────────

DEFAULT_BOT_TEXTS = {
    "welcome": "Добро пожаловать в путеводитель стройной и здоровой фигуры!",
    "tariff_selection": (
        "👩🏻\u200d⚕️ Я, Чунтонова Ольга Валерьевна, дипломированный диетолог-психолог, "
        "эксперт в области питания с 2017 года.\n\n"
        "Вашему вниманию представлены групповые и самостоятельные онлайн курсы "
        "стройности и мой сборник пп-рецептов\n\n"
        "Если у вас остались вопросы вы можете задать мне их лично -> "
        "Чунтонова Ольга Валерьевна\n\n"
        "Выберите подходящий и ознакомьтесь ОБЯЗАТЕЛЬНО "
        "с описанием курса до регистрации 👇"
    ),
    "feedback": (
        "Если у вас остались вопросы - напишите мне, "
        "я с удовольствием отвечу как освобожусь.\n"
        "Чунтонова Ольга Валерьевна, ваш диетолог."
    ),
    "no_active_subs": (
        "📋 У вас пока нет активных подписок.\n\n"
        "Выберите курс в разделе «Курсы стройности»."
    ),
    "payment_success": "✅ Оплата прошла успешно! Спасибо за покупку.",
    "free_activation_success": (
        "✅ Вы успешно подписались на бесплатный канал с гайдами.\n\n"
        "Чтобы получить доступ к ресурсам нажмите кнопки ниже 👇"
    ),
    "activation_links": "🔗 Ссылки для доступа к курсу 👇",
    "notify_1day": "⏰ До окончания вашей подписки «{tariff_name}» остался 1 день.",
    "notify_3days": "⏰ До окончания вашей подписки «{tariff_name}» осталось 3 дня.",
    "subscription_end": "❌ Ваша подписка «{tariff_name}» закончилась.",
    "mandatory_channels": "Для продолжения подпишитесь на обязательные каналы.",
    "payment_invoice": (
        "✅ Счёт создан!\n\n"
        "Тариф: **{tariff_name}**\n"
        "Сумма: **{price}₽**\n"
        "Способ: {method_name}\n\n"
        "Нажмите «Перейти к оплате» и оплатите.\n"
        "После оплаты нажмите «Проверить оплату»."
    ),
    "payment_processing": "⏳ Оплата ещё обрабатывается.\nПодождите и нажмите «Проверить оплату» снова.",
    "payment_failed": "❌ Оплата не прошла, попробуйте снова.",
    "feedback_reply": "На ваш вопрос пришёл ответ из администрации:\n{reply}",
    "promo_activation": (
        "💳 Оплата тарифа «{Название}»\n"
        "Сумма: **{сумма}**\n\n"
        "Если у вас есть промокод — отправьте его сообщением.\n"
        "Или нажмите «Продолжить»."
    ),
    "unknown_message": (
        "Чтобы отправить сообщение нужно перейти в личном кабинете в обратную связь."
    ),
    # Тексты кнопок ЛК
    "btn_courses": "🍏 Курсы",
    "btn_my_subs": "📋 Мои подписки",
    "btn_get_bonus": "🎁 Получить бонус",
    "btn_oferta": "📄 Договор оферты",
    "btn_feedback": "💬 Обратная связь",
    "btn_cabinet": "👤 Личный кабинет",
    # Тексты кнопок оплаты
    "btn_pay_go": "💳 Перейти к оплате",
    "btn_pay_check": "🔄 Проверить оплату",
    # Описания
    "desc_catalog": "Выберите подходящий курс 👇",
    "desc_cabinet": "👤 Личный кабинет:",
}

BOT_TEXT_LABELS = {
    "welcome": "Приветствие",
    "tariff_selection": "Выбор тарифов",
    "feedback": "Обратная связь",
    "no_active_subs": "Нет активных подписок",
    "payment_success": "Успешный платёж",
    "free_activation_success": "Успешная активация бесплатного тарифа",
    "activation_links": "Сообщение со ссылками после активации курса",
    "notify_1day": "Уведомление за 1 день",
    "notify_3days": "Уведомление за 3 дня",
    "subscription_end": "Конец подписки",
    "mandatory_channels": "Обязательные каналы",
    "payment_invoice": "Счёт на оплату",
    "payment_processing": "Оплата обрабатывается",
    "payment_failed": "Платёж не прошёл",
    "feedback_reply": "Ответ администрации пользователю",
    "promo_activation": "Активация промокода",
    "unknown_message": "Неизвестное сообщение",
}

# Метки для кнопок ЛК
BUTTON_TEXT_LABELS = {
    "btn_courses": "Курсы",
    "btn_my_subs": "Мои подписки",
    "btn_get_bonus": "Получить бонус",
    "btn_oferta": "Договор оферты",
    "btn_feedback": "Обратная связь",
    "btn_cabinet": "Личный кабинет",
    "btn_pay_go": "Кнопка «Перейти к оплате»",
    "btn_pay_check": "Кнопка «Проверить оплату»",
}

# Метки для описаний
DESC_TEXT_LABELS = {
    "desc_catalog": "Сообщение при выводе каталога тарифов",
    "desc_cabinet": "Сообщение в Личном кабинете",
}


async def get_button_texts() -> dict[str, str]:
    """Загружает все тексты кнопок ЛК из БД (или дефолтные)."""
    result = {}
    for key in BUTTON_TEXT_LABELS:
        result[key] = await get_bot_text(key)
    return result


async def get_bot_text(key: str) -> str:
    """Возвращает текст бота из БД или дефолтный."""
    async with pool.acquire() as conn:
        val = await conn.fetchval(
            "SELECT text FROM bot_texts WHERE key = $1", key
        )
        return val if val is not None else DEFAULT_BOT_TEXTS.get(key, "")


async def set_bot_text(key: str, text: str):
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO bot_texts (key, text) VALUES ($1, $2)
            ON CONFLICT (key) DO UPDATE SET text = $2, updated_at = NOW()
        """, key, text)


# ── Промокоды ─────────────────────────────────────────────────

async def create_promo(code: str, discount_percent: int,
                       max_activations: int = 0,
                       promo_type: str = "general") -> dict:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO promo_codes (code, discount_percent, max_activations, promo_type)
            VALUES ($1, $2, $3, $4) RETURNING *
        """, code, discount_percent, max_activations, promo_type)
        return dict(row)


async def get_promo(promo_id: int) -> dict | None:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM promo_codes WHERE id = $1", promo_id)
        return dict(row) if row else None


async def get_promo_by_code(code: str) -> dict | None:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM promo_codes WHERE LOWER(code) = LOWER($1)", code
        )
        return dict(row) if row else None


async def list_promos(promo_type: str | None = None) -> list[dict]:
    async with pool.acquire() as conn:
        if promo_type:
            rows = await conn.fetch(
                "SELECT * FROM promo_codes WHERE promo_type = $1 ORDER BY created_at DESC",
                promo_type,
            )
        else:
            rows = await conn.fetch(
                "SELECT * FROM promo_codes ORDER BY created_at DESC"
            )
        return [dict(r) for r in rows]


async def update_promo(promo_id: int, **fields) -> dict | None:
    if not fields:
        return await get_promo(promo_id)
    sets, vals = [], []
    for i, (k, v) in enumerate(fields.items(), start=2):
        sets.append(f"{k} = ${i}")
        vals.append(v)
    sql = f"UPDATE promo_codes SET {', '.join(sets)} WHERE id = $1 RETURNING *"
    async with pool.acquire() as conn:
        row = await conn.fetchrow(sql, promo_id, *vals)
        return dict(row) if row else None


async def delete_promo(promo_id: int):
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM promo_codes WHERE id = $1", promo_id)


async def add_promo_activation(promo_id: int, user_id: int,
                               tariff_id: int | None = None,
                               paid: bool = False) -> dict:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO promo_activations (promo_id, user_id, tariff_id, paid)
            VALUES ($1, $2, $3, $4) RETURNING *
        """, promo_id, user_id, tariff_id, paid)
        return dict(row)


async def count_promo_activations(promo_id: int) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT COUNT(*) FROM promo_activations WHERE promo_id = $1", promo_id
        )


async def count_user_promo_activations(promo_id: int, user_id: int) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT COUNT(*) FROM promo_activations WHERE promo_id = $1 AND user_id = $2",
            promo_id, user_id,
        )


async def get_promo_activations(promo_id: int) -> list[dict]:
    """Все активации промокода с данными пользователя."""
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT pa.*, u.first_name, u.last_name
            FROM promo_activations pa
            LEFT JOIN users u ON u.user_id = pa.user_id
            WHERE pa.promo_id = $1
            ORDER BY pa.activated_at DESC
        """, promo_id)
        return [dict(r) for r in rows]


# ── Способы оплаты ───────────────────────────────────────────

async def list_payment_methods(active_only: bool = False) -> list[dict]:
    async with pool.acquire() as conn:
        if active_only:
            rows = await conn.fetch(
                "SELECT * FROM payment_methods WHERE is_active = TRUE ORDER BY id"
            )
        else:
            rows = await conn.fetch("SELECT * FROM payment_methods ORDER BY id")
        return [dict(r) for r in rows]


async def get_payment_method(method_id: int) -> dict | None:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM payment_methods WHERE id = $1", method_id
        )
        return dict(row) if row else None


async def create_payment_method(name: str, provider: str,
                                shop_id: str, secret_key: str) -> dict:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO payment_methods (name, provider, shop_id, secret_key)
            VALUES ($1, $2, $3, $4) RETURNING *
        """, name, provider, shop_id, secret_key)
        return dict(row)


async def toggle_payment_method(method_id: int) -> dict | None:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            UPDATE payment_methods SET is_active = NOT is_active
            WHERE id = $1 RETURNING *
        """, method_id)
        return dict(row) if row else None


async def delete_payment_method(method_id: int):
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM payment_methods WHERE id = $1", method_id)


# ── Покупки: расширенные функции ──────────────────────────────

async def create_paid_purchase(user_id: int, tariff_id: int,
                               price_paid: float, payment_id: str,
                               payment_method_id: int,
                               promo_id: int | None = None,
                               original_price: float | None = None,
                               expires_at=None) -> dict:
    """Создаёт покупку со статусом pending и привязкой к платежу."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO purchases (user_id, tariff_id, price_paid, status,
                                   payment_id, payment_method_id, promo_id,
                                   original_price, purchased_at, expires_at)
            VALUES ($1, $2, $3, 'pending', $4, $5, $6, $7, NOW(), $8)
            RETURNING *
        """, user_id, tariff_id, price_paid, payment_id,
            payment_method_id, promo_id, original_price, expires_at)
        return dict(row)


async def confirm_purchase(purchase_id: int, expires_at=None):
    """Активирует покупку после успешной оплаты."""
    async with pool.acquire() as conn:
        await conn.execute("""
            UPDATE purchases SET status = 'active', activated_at = NOW(),
                   expires_at = COALESCE($2, expires_at)
            WHERE id = $1
        """, purchase_id, expires_at)


async def cancel_purchase(purchase_id: int):
    """Отменяет покупку."""
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE purchases SET status = 'canceled' WHERE id = $1", purchase_id
        )


async def get_pending_payments() -> list[dict]:
    """Покупки с payment_id и статусом pending (для фоновой проверки)."""
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT p.id, p.user_id, p.tariff_id, p.payment_id,
                   p.payment_method_id, p.price_paid, p.promo_id,
                   t.name AS tariff_name, t.duration_days
            FROM purchases p
            JOIN tariffs t ON t.id = p.tariff_id
            WHERE p.status = 'pending'
              AND p.payment_id IS NOT NULL
              AND p.payment_id != ''
        """)
        return [dict(r) for r in rows]


async def get_pending_purchase_by_payment_id(payment_id: str) -> dict | None:
    """Находит pending-покупку по payment_id (order_id)."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT p.*, t.name AS tariff_name, t.duration_days
            FROM purchases p
            JOIN tariffs t ON t.id = p.tariff_id
            WHERE p.payment_id = $1 AND p.status = 'pending'
        """, payment_id)
        return dict(row) if row else None


async def get_purchase(purchase_id: int) -> dict | None:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT p.*, t.name AS tariff_name, t.duration_days
            FROM purchases p
            JOIN tariffs t ON t.id = p.tariff_id
            WHERE p.id = $1
        """, purchase_id)
        return dict(row) if row else None


async def get_user_tariff_status(user_id: int, tariff_id: int) -> str:
    """Статус подписки: 'active', 'expired', 'none'."""
    async with pool.acquire() as conn:
        active = await conn.fetchval("""
            SELECT 1 FROM purchases
            WHERE user_id = $1 AND tariff_id = $2
              AND status = 'active'
              AND (expires_at IS NULL OR expires_at > NOW())
            LIMIT 1
        """, user_id, tariff_id)
        if active:
            return "active"
        has_any = await conn.fetchval("""
            SELECT 1 FROM purchases
            WHERE user_id = $1 AND tariff_id = $2
              AND status IN ('active', 'expired')
            LIMIT 1
        """, user_id, tariff_id)
        if has_any:
            return "expired"
        return "none"


# ── Логирование действий пользователей ────────────────────────

async def add_user_log(user_id: int, action: str):
    """Записывает лог действия пользователя."""
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO user_logs (user_id, action) VALUES ($1, $2)",
            user_id, action,
        )


async def get_user_logs(user_id: int, limit: int = 50) -> list[dict]:
    """Возвращает логи пользователя."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM user_logs WHERE user_id = $1 ORDER BY created_at DESC LIMIT $2",
            user_id, limit,
        )
        return [dict(r) for r in rows]


async def is_new_user(user_id: int) -> bool:
    """Проверяет, есть ли пользователь в БД (до upsert)."""
    async with pool.acquire() as conn:
        val = await conn.fetchval(
            "SELECT 1 FROM users WHERE user_id = $1", user_id
        )
        return val is None


async def get_user_name(user_id: int, fallback: str = "") -> str:
    """Возвращает отображаемое имя пользователя."""
    user = await get_user(user_id)
    return build_user_name(user, fallback=fallback or str(user_id))


async def get_button_texts(user_id: int | None = None, **context) -> dict[str, str]:
    """Загружает тексты кнопок ЛК из БД (или дефолтные)."""
    if user_id is not None:
        user = await get_user(user_id)
        user_context = build_user_template_context(user, fallback=str(user_id))
        user_context.update(context)
        context = user_context

    result = {}
    for key in BUTTON_TEXT_LABELS:
        result[key] = await get_bot_text(key, **context)
    return result


async def get_bot_text(key: str, user_id: int | None = None, **context) -> str:
    """Возвращает текст бота из БД или дефолтный."""
    async with pool.acquire() as conn:
        val = await conn.fetchval(
            "SELECT text FROM bot_texts WHERE key = $1", key
        )

    text = val if val is not None else DEFAULT_BOT_TEXTS.get(key, "")
    if user_id is not None:
        user = await get_user(user_id)
        user_context = build_user_template_context(user, fallback=str(user_id))
        user_context.update(context)
        context = user_context
    return format_template(text, **context)
