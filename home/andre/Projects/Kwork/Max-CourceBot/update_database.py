#!/usr/bin/env python3

"""Скрипт для добавления функции get_subscribed_excluding_tariffs_user_ids в database.py"""

import re

# Читаем текущий файл
with open('database.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Новая функция для вставки после get_tariff_user_ids
new_function = """

async def get_subscribed_excluding_tariffs_user_ids(excluded_tariff_ids: list[int]) -> list[int]:
    \"\"\"Пользователи с активной подпиской НЕ на указанные тарифы.
    Если excluded_tariff_ids пуст — возвращает всех подписчиков (аналог get_paid_user_ids,
    но без DISTINCT, что может дать дубли при нескольких активных подписках).
    \"\"\"
    async with pool.acquire() as conn:
        if excluded_tariff_ids:
            # Исключаем пользователей с активными подписками на указанные тарифы
            rows = await conn.fetch(\"\"\"
                SELECT DISTINCT u.user_id FROM users u
                JOIN purchases p ON p.user_id = u.user_id
                WHERE p.status = 'active'
                  AND (p.expires_at IS NULL OR p.expires_at > NOW())
                  AND NOT EXISTS (
                      SELECT 1 FROM purchases p2
                      WHERE p2.user_id = p.user_id
                        AND p2.tariff_id = ANY($1::int[])
                        AND p2.status = 'active'
                        AND (p2.expires_at IS NULL OR p2.expires_at > NOW())
                  )
                  AND u.is_banned = FALSE
            \"\", excluded_tariff_ids)
        else:
            # Все подписчики без исключения
            rows = await conn.fetch(\"\"\"
                SELECT DISTINCT u.user_id FROM users u
                JOIN purchases p ON p.user_id = u.user_id
                WHERE p.status = 'active'
                  AND (p.expires_at IS NULL OR p.expires_at > NOW())
                  AND u.is_banned = FALSE
            \")
        return [r["user_id"] for r in rows]

"""

# Вставляем после функции get_tariff_user_ids, но перед комментарием # ── Покупки
pattern = r"(async def get_tariff_user_ids\(tariff_id: int\) -> list\[int\]:.*?return \[r\[\"user_id\"\] for r in rows\])"

match = re.search(pattern, content, re.DOTALL)
if match:
    insert_pos = match.end()
    new_content = content[:insert_pos] + new_function + content[insert_pos:]
    
    with open('database.py', 'w', encoding='utf-8') as f:
        f.write(new_content)
    print("✅ Функция добавлена в database.py")
else:
    print("❌ Не удалось найти позицию для вставки")
