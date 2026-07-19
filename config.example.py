
BOT_TOKEN = "YOUR_BOT_TOKEN"

ADMIN_IDS = {111111111}

DATABASE_URL = "postgresql://user:password@127.0.0.1:5432/dbname"
WEBHOOK_HOST = "0.0.0.0"
WEBHOOK_PORT = 8443
WEBHOOK_BASE_URL = "https://yourdomain.ru"

MAX_WEBHOOK_PATH = "/max/webhook"
MAX_WEBHOOK_URL = f"{WEBHOOK_BASE_URL}{MAX_WEBHOOK_PATH}"
MAX_WEBHOOK_SECRET = "CHANGE_ME_TO_RANDOM_SECRET"
MAX_UPDATE_TYPES = [
    "bot_started",
    "message_created",
    "message_callback",
    "bot_added",
    "bot_removed",
]

EXPIRY_CHECK_INTERVAL = 60
PAYMENT_CHECK_INTERVAL = 15
WARMUP_CHECK_INTERVAL = 60

OFERTA_URL = "https://yourdomain.ru/terms-of-use/"
PRIVACY_URL = "https://yourdomain.ru/confidential/"
