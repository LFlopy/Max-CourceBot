# MAX Course Bot

Бот для мессенджера MAX, который продаёт доступ к онлайн-курсам, принимает платежи, выдаёт пользователей в закрытые чаты/каналы и автоматически завершает подписки.

## Возможности

### Для пользователя

- Каталог активных курсов с описанием, ценой, длительностью и медиа.
- Бесплатные и платные тарифы.
- Два типа доступа:
  - курс до фиксированной даты окончания;
  - курс на заданное количество дней или минут с момента активации.
- Промокоды со скидкой и ограничениями по тарифам, пользователям, сроку действия и числу активаций.
- Оплата через подключённые платёжные методы.
- Автоматическая выдача доступа в ресурсы тарифа после успешной оплаты.
- Личный кабинет со списком активных подписок.
- Бонусные файлы, привязанные к тарифам.
- Обратная связь с администратором, включая вложения.
- Догревающие сообщения для pending-покупок.

### Для администратора

- Создание, редактирование, скрытие и удаление тарифов.
- Настройка цен: основная, старая, цена продления, цена продления активной подписки.
- Настройка дат, длительности, лимитов активации и групп доступа.
- Привязка чатов/каналов MAX к тарифам.
- Управление бонусными файлами.
- Управление промокодами и списком активаций.
- Добавление и отключение платёжных методов.
- Ручная выдача, отзыв и перенос подписок.
- Блокировка пользователей.
- Рассылки по группам пользователей и тарифам.
- Экспорт пользователей, подписчиков и истёкших подписок в `.xlsx`.
- Редактирование пользовательских текстов бота из админ-панели.

## Стек

- Python 3.10+
- aiohttp
- asyncpg
- PostgreSQL
- openpyxl

## Структура проекта

```text
bot.py                         # Точка входа, webhook-сервер и bootstrap приложения
services/background_jobs.py     # Фоновые задачи: истечение подписок, polling платежей, прогрев
user_handlers/core.py           # Пользовательские сценарии бота
admin_panel/handlers.py         # Сценарии админ-панели
user_interface/keyboards.py     # Пользовательские inline-клавиатуры
admin_panel/keyboards.py        # Админские inline-клавиатуры
persistence/postgres.py         # PostgreSQL schema/bootstrap и запросы
payments.py                     # Провайдеры оплаты
max_client.py                   # Клиент MAX Bot API
fsm.py                          # In-memory FSM
utils.py                        # Общие утилиты
config.example.py               # Пример конфигурации
requirements.txt                # Python-зависимости
```

Файлы `handlers.py`, `admin_handlers.py`, `keyboards.py`, `admin_keyboards.py` и `database.py` оставлены как совместимые фасады для старых импортов.

## Платёжные провайдеры

| Провайдер | Интеграция | Подтверждение оплаты |
|---|---|---|
| ЮКасса | REST API | polling |
| Prodamus | Payform link | webhook |
| Альфа-Банк | REST API, Sber-compatible endpoint | polling |

Prodamus webhook проверяется по подписи, если у платёжного метода задан `secret_key`.

## Webhook-и и фоновые задачи

Приложение поднимает aiohttp-сервер и регистрирует маршруты:

- `MAX_WEBHOOK_PATH` для событий MAX.
- `/prodamus/webhook` для уведомлений Prodamus.

Фоновые задачи:

- проверка истёкших подписок;
- проверка pending-платежей у провайдеров с polling;
- отправка догревающих сообщений для pending-покупок.

Интервалы настраиваются через `EXPIRY_CHECK_INTERVAL`, `PAYMENT_CHECK_INTERVAL` и `WARMUP_CHECK_INTERVAL`.

## База данных

Таблицы создаются автоматически при старте приложения через `database.init_db()`.

Основные таблицы:

| Таблица | Назначение |
|---|---|
| `users` | Пользователи |
| `tariffs` | Тарифы/курсы |
| `categories` | Категории тарифов |
| `tariff_resources` | Чаты/каналы, привязанные к тарифам |
| `purchases` | Покупки и подписки |
| `payment_methods` | Платёжные методы |
| `promo_codes` | Промокоды |
| `promo_activations` | Активации промокодов |
| `gift_files` | Бонусные файлы |
| `gift_file_tariffs` | Связь бонусных файлов и тарифов |
| `bot_texts` | Редактируемые тексты |
| `user_logs` | Логи действий пользователей |
| `bot_chats` | Локальный каталог чатов/каналов MAX |
| `tariff_warmup_messages` | Догревающие сообщения тарифов |
| `warmup_plan` | План догрева для pending-покупки |
| `warmup_sends` | Факт отправки догревающих сообщений |

## Установка

1. Установить зависимости:

```bash
pip install -r requirements.txt
```

2. Создать конфиг:

```bash
cp config.example.py config.py
```

3. Заполнить `config.py`.

4. Создать PostgreSQL-базу:

```bash
psql -U postgres -c "CREATE DATABASE dbname;"
```

5. Запустить бота:

```bash
python bot.py
```

## Конфигурация

Все параметры задаются в `config.py`. За основу используйте `config.example.py`.

| Параметр | Описание |
|---|---|
| `BOT_TOKEN` | Токен MAX-бота |
| `ADMIN_IDS` | Set пользовательских ID администраторов |
| `DATABASE_URL` | PostgreSQL DSN |
| `WEBHOOK_HOST` | Интерфейс, на котором слушает aiohttp-сервер |
| `WEBHOOK_PORT` | Порт aiohttp-сервера |
| `WEBHOOK_BASE_URL` | Публичный базовый URL без path |
| `MAX_WEBHOOK_PATH` | Локальный path MAX webhook |
| `MAX_WEBHOOK_URL` | Публичный HTTPS URL MAX webhook |
| `MAX_WEBHOOK_SECRET` | Секрет MAX webhook |
| `MAX_UPDATE_TYPES` | Список типов событий MAX |
| `EXPIRY_CHECK_INTERVAL` | Интервал проверки истёкших подписок, секунды |
| `PAYMENT_CHECK_INTERVAL` | Интервал проверки pending-платежей, секунды |
| `WARMUP_CHECK_INTERVAL` | Интервал проверки догревающих сообщений, секунды |
| `OFERTA_URL` | Ссылка на оферту |
| `PRIVACY_URL` | Ссылка на политику конфиденциальности |

Пример:

```python
BOT_TOKEN = "YOUR_BOT_TOKEN"
ADMIN_IDS = {111111111}
DATABASE_URL = "postgresql://user:password@127.0.0.1:5432/dbname"

WEBHOOK_HOST = "0.0.0.0"
WEBHOOK_PORT = 8443
WEBHOOK_BASE_URL = "https://example.com"

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
```

## Эксплуатационные замечания

- `config.py` не должен попадать в git.
- Для MAX webhook нужен публичный HTTPS URL.
- Для Prodamus публичный URL уведомлений: `WEBHOOK_BASE_URL + "/prodamus/webhook"`.
- FSM хранится в памяти процесса, поэтому незавершённые диалоги сбрасываются при рестарте.
- Схема БД создаётся при старте приложения; отдельной системы миграций в проекте нет.

## Проверка

Минимальная проверка синтаксиса:

```bash
python -m py_compile bot.py handlers.py admin_handlers.py database.py max_client.py payments.py keyboards.py admin_keyboards.py fsm.py utils.py
```
