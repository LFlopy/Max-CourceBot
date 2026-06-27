"""Настройки бота."""

BOT_TOKEN = "f9LHodD0cOLrb_H4TrMzjdykAgG8Vr4YHUcH0TTJJL6ljeYtX1SnMuDo7QiUvJnPTCTkPQbG7KAOLzpK7Y2H"

# user_id админов (можно несколько)
ADMIN_IDS = {211433012, 41670843, 79660947}

# PostgreSQL
DATABASE_URL = "postgresql://courcebot_user:courcebot123@127.0.0.1:5432/courcebot"
# Локальный HTTP-сервер для приёма webhook-ов (MAX + платёжные системы)
WEBHOOK_HOST = "0.0.0.0"
WEBHOOK_PORT = 8443
# Публичный URL сервера (без / в конце), например "https://yourdomain.ru"
WEBHOOK_BASE_URL = "https://ovchuntonova.ru/max"

# ── MAX Webhook (с 2026-05-11 long polling ограничен, нужен webhook) ──
# MAX требует HTTPS на порту 443 с валидным TLS-сертификатом.
# Настройте TLS-терминацию (nginx/Caddy) с проксированием на WEBHOOK_HOST:WEBHOOK_PORT.
MAX_WEBHOOK_PATH = "/max/webhook"
# Полный публичный URL, который MAX будет вызывать (https, порт 443 не указывается).
MAX_WEBHOOK_URL = "https://ovchuntonova.ru/max/webhook"
# Секрет для проверки заголовка X-Max-Bot-Api-Secret. 5–256 символов: A-Z a-z 0-9 - _
# Рекомендуется сгенерировать случайный, например: secrets.token_urlsafe(32)
MAX_WEBHOOK_SECRET = "PYbieBgT1kfoDbRTXyS3vs_Mxu3OB_WXXsHnxshNOgY"
# Типы обновлений, на которые подписываемся (None — все)
MAX_UPDATE_TYPES = ["message_created", "bot_started", "message_callback"]

# Ссылки из оферты
OFERTA_URL = "https://fitnessppeda.ru/book/terms-of-use/"
PRIVACY_URL = "https://fitnessppeda.ru/book/confidential/"
