"""Настройки бота. Скопируйте этот файл в config.py и заполните своими значениями."""

BOT_TOKEN = "YOUR_BOT_TOKEN"

# user_id админов (можно несколько)
ADMIN_IDS = {111111111}

# PostgreSQL
DATABASE_URL = "postgresql://user:password@127.0.0.1:5432/dbname"
# Webhook-сервер для приёма уведомлений от платёжных систем
WEBHOOK_HOST = "0.0.0.0"
WEBHOOK_PORT = 8443
# Публичный URL сервера (без / в конце), например "https://yourdomain.ru"
WEBHOOK_BASE_URL = "https://yourdomain.ru/prodamus/webhook"

# Ссылки из оферты
OFERTA_URL = "https://yourdomain.ru/terms-of-use/"
PRIVACY_URL = "https://yourdomain.ru/confidential/"
