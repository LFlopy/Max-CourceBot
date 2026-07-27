
import hmac
import hashlib
import json
import uuid
import logging
from collections.abc import Mapping
import aiohttp

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=10)

ALFABANK_BASE_URL = "https://payment.alfabank.ru/payment/rest"


_shared_session: aiohttp.ClientSession | None = None


def _get_session() -> aiohttp.ClientSession:
    global _shared_session
    if _shared_session is None or _shared_session.closed:
        _shared_session = aiohttp.ClientSession(timeout=DEFAULT_TIMEOUT)
    return _shared_session


async def close_session() -> None:
    """Close the shared payments HTTP session."""
    global _shared_session
    if _shared_session and not _shared_session.closed:
        await _shared_session.close()
    _shared_session = None


async def _request_json(
    session: aiohttp.ClientSession,
    method: str,
    url: str,
    *,
    params: dict | None = None,
    json: dict | None = None,
    auth: aiohttp.BasicAuth | None = None,
    headers: dict | None = None,
    retries: int = 3,
) -> tuple[int, dict | None]:
    last_exc: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            async with session.request(
                method,
                url,
                params=params,
                json=json,
                auth=auth,
                headers=headers,
            ) as r:
                status = r.status
                try:
                    data = await r.json(content_type=None)
                except Exception:
                    raw = await r.text()
                    logger.warning("Non-JSON response %s %s: %s", method, url, raw[:500])
                    return status, None
                return status, data if isinstance(data, dict) else None
        except Exception as e:
            last_exc = e
            logger.exception("HTTP error (attempt %s/%s): %s %s", attempt, retries, method, url)
    if last_exc:
        logger.error("HTTP failed after retries: %s %s (%s)", method, url, last_exc)
    return 0, None


class PaymentProvider:
    """Базовый класс платёжной системы."""

    async def create_payment(self, amount: float, description: str,
                             metadata: dict | None = None) -> dict | None:
        """Создаёт платёж.
        Возвращает {"payment_id": str, "payment_url": str} или None."""
        raise NotImplementedError

    async def check_payment(self, payment_id: str) -> str:
        """Проверяет статус. Возвращает 'pending' | 'succeeded' | 'canceled'."""
        raise NotImplementedError


class YooKassaProvider(PaymentProvider):
    """ЮКасса (yookassa.ru)."""

    API = "https://api.yookassa.ru/v3"

    def __init__(self, shop_id: str, secret_key: str, session: aiohttp.ClientSession):
        self.shop_id = shop_id
        self.secret_key = secret_key
        self.session = session

    async def create_payment(self, amount: float, description: str,
                             metadata: dict | None = None) -> dict | None:
        """Create a payment with the provider."""
        payload = {
            "amount": {"value": f"{amount:.2f}", "currency": "RUB"},
            "confirmation": {"type": "redirect", "return_url": "https://max.ru"},
            "capture": True,
            "description": description[:128],
        }
        if metadata:
            payload["metadata"] = {str(k): str(v) for k, v in metadata.items()}

        auth = aiohttp.BasicAuth(self.shop_id, self.secret_key)
        headers = {
            "Content-Type": "application/json",
            "Idempotence-Key": str(uuid.uuid4()),
        }

        try:
            status, data = await _request_json(
                self.session,
                "POST",
                f"{self.API}/payments",
                json=payload,
                auth=auth,
                headers=headers,
            )
            if status in (200, 201) and data:
                pid = data.get("id")
                confirmation = data.get("confirmation") or {}
                url = confirmation.get("confirmation_url")
                if pid and url:
                    return {"payment_id": str(pid), "payment_url": str(url)}
            logger.warning("[yookassa] create error: status=%s data=%s", status, data)
            return None
        except Exception as e:
            logger.exception("[yookassa] exception: %s", e)
            return None

    async def check_payment(self, payment_id: str) -> str:
        """Check payment status with the provider."""
        auth = aiohttp.BasicAuth(self.shop_id, self.secret_key)
        try:
            status_code, data = await _request_json(
                self.session,
                "GET",
                f"{self.API}/payments/{payment_id}",
                auth=auth,
            )
            if status_code == 200 and data:
                st = (data.get("status") or "pending").lower()
                if st == "succeeded":
                    return "succeeded"
                if st in ("canceled", "cancelled"):
                    return "canceled"
            return "pending"
        except Exception as e:
            logger.exception("[yookassa] check exception: %s", e)
            return "pending"


class ProdamusProvider(PaymentProvider):
    """
    Prodamus.

    Примечание по настройкам:
    - shop_id: ожидаем URL вашей payform, например "https://your.payform.ru/"
    - secret_key: может быть пустым (если не требуется), иначе передадим как token/signature если поддерживается

    Ссылка формируется через payform (do=link). payment_id = order_id.
    """

    def __init__(self, shop_id: str, secret_key: str, session: aiohttp.ClientSession,
                 webhook_url: str = ""):
        self.payform_url = (shop_id or "").strip()
        self.secret_key = (secret_key or "").strip()
        self.session = session
        self.webhook_url = webhook_url

    async def create_payment(self, amount: float, description: str,
                             metadata: dict | None = None) -> dict | None:
        """Create a payment with the provider."""
        if not self.payform_url.startswith("http"):
            logger.error("[prodamus] shop_id должен быть payform URL, получено: %r", self.payform_url)
            return None

        order_id = str(uuid.uuid4())

        params: dict[str, str] = {
            "do": "link",
            "order_id": order_id,
            "customer_extra": description[:128] if description else "",
            "products[0][name]": description[:128] if description else "Оплата",
            "products[0][price]": f"{amount:.2f}",
            "products[0][quantity]": "1",
            "products[0][currency]": "rub",
        }
        if self.webhook_url:
            params["urlNotification"] = self.webhook_url
        if metadata:
            for k, v in metadata.items():
                params[f"meta_{k}"] = str(v)
        if self.secret_key:
            params["signature"] = self.create_signature(params, self.secret_key)

        url = self.payform_url.rstrip("/")
        try:
            async with self.session.get(url, params=params) as r:
                text = (await r.text()).strip()
                if r.status in (200, 201) and text.startswith("http"):
                    return {"payment_id": order_id, "payment_url": text}
                logger.warning("[prodamus] create error: status=%s body=%s", r.status, text[:500])
                return None
        except Exception as e:
            logger.exception("[prodamus] exception: %s", e)
            return None

    async def check_payment(self, payment_id: str) -> str:
        """Check payment status with the provider."""
        return "pending"

    @staticmethod
    def _stringify_values(value):
        if isinstance(value, Mapping):
            return {str(k): ProdamusProvider._stringify_values(v) for k, v in value.items()}
        if isinstance(value, list):
            return [ProdamusProvider._stringify_values(v) for v in value]
        return "" if value is None else str(value)

    @staticmethod
    def _sort_recursive(value):
        if isinstance(value, Mapping):
            if value and all(str(key).isdigit() for key in value.keys()):
                ordered_keys = sorted(value.keys(), key=lambda key: int(str(key)))
                if ordered_keys == [str(i) for i in range(len(ordered_keys))]:
                    return [
                        ProdamusProvider._sort_recursive(value[key])
                        for key in ordered_keys
                    ]
            return {
                key: ProdamusProvider._sort_recursive(value[key])
                for key in sorted(value.keys())
            }
        if isinstance(value, list):
            return [ProdamusProvider._sort_recursive(v) for v in value]
        return value

    @staticmethod
    def _insert_bracket_value(target: dict, key: str, value: str) -> None:
        if "[" not in key:
            target[key] = value
            return

        head, rest = key.split("[", 1)
        parts = [head]
        for part in rest.split("["):
            parts.append(part.rstrip("]"))

        current = target
        for part in parts[:-1]:
            current = current.setdefault(part, {})
        current[parts[-1]] = value

    @staticmethod
    def _prepare_signature_data(data: Mapping) -> dict:
        prepared: dict = {}
        items = data.items()
        for key, value in items:
            if str(key).lower() in ("sign", "signature"):
                continue
            ProdamusProvider._insert_bracket_value(prepared, str(key), value)
        return ProdamusProvider._sort_recursive(
            ProdamusProvider._stringify_values(prepared)
        )

    @staticmethod
    def create_signature(data: Mapping, secret_key: str) -> str:
        """Создаёт подпись Prodamus: sorted data -> JSON_UNESCAPED_UNICODE -> escaped slashes -> HMAC-SHA256."""
        prepared = ProdamusProvider._prepare_signature_data(data)
        payload = json.dumps(prepared, ensure_ascii=False, separators=(",", ":"))
        payload = payload.replace("/", "\\/")
        return hmac.new(secret_key.encode(), payload.encode(), hashlib.sha256).hexdigest()

    @staticmethod
    def verify_signature(data: Mapping, secret_key: str, signature: str) -> bool:
        """Проверяет подпись webhook от Prodamus по алгоритму Hmac.php."""
        if not signature:
            return False
        expected = ProdamusProvider.create_signature(data, secret_key)
        return hmac.compare_digest(expected, signature.strip().lower())


class AlfaBankProvider(PaymentProvider):
    """Альфа-Банк (совместимый REST API со Сбер: register.do / getOrderStatusExtended.do)."""

    def __init__(self, shop_id: str, secret_key: str, session: aiohttp.ClientSession):
        self.userName = shop_id
        self.password = secret_key
        self.session = session

    async def create_payment(self, amount: float, description: str,
                             metadata: dict | None = None) -> dict | None:
        """Create a payment with the provider."""
        order_number = str(uuid.uuid4())
        amount_int = int(round(float(amount) * 100))  # копейки

        params: dict[str, str] = {
            "userName": str(self.userName),
            "password": str(self.password),
            "orderNumber": order_number,
            "amount": str(amount_int),
            "returnUrl": "https://max.ru",
            "description": (description or "")[:128],
        }
        if metadata:
            params["jsonParams"] = str({str(k): str(v) for k, v in metadata.items()})

        try:
            status, data = await _request_json(
                self.session,
                "POST",
                f"{ALFABANK_BASE_URL}/register.do",
                params=params,
            )
            if status == 200 and data:
                order_id = data.get("orderId")
                form_url = data.get("formUrl")
                if order_id and form_url:
                    return {"payment_id": str(order_id), "payment_url": str(form_url)}
            logger.warning("[alfabank] register error: status=%s data=%s", status, data)
            return None
        except Exception as e:
            logger.exception("[alfabank] exception: %s", e)
            return None

    async def check_payment(self, payment_id: str) -> str:
        """Check payment status with the provider."""
        params = {
            "userName": str(self.userName),
            "password": str(self.password),
            "orderId": str(payment_id),
        }
        try:
            status, data = await _request_json(
                self.session,
                "POST",
                f"{ALFABANK_BASE_URL}/getOrderStatusExtended.do",
                params=params,
            )
            if status != 200 or not data:
                return "pending"

            # В зависимости от версии API поле может называться orderStatus или orderStatusExtended.
            raw = data.get("orderStatus")
            if raw is None:
                raw = data.get("orderStatusExtended")
            try:
                st = int(raw) if raw is not None else None
            except Exception:
                st = None

            if st == 2:
                return "succeeded"
            if st in (0, 1, None):
                return "pending"
            if st in (3, 6):
                return "canceled"
            return "pending"
        except Exception as e:
            logger.exception("[alfabank] check exception: %s", e)
            return "pending"



PROVIDERS = {
    "yookassa": ("ЮКасса", YooKassaProvider),
    "prodamus": ("Prodamus", ProdamusProvider),
    "alfabank": ("Альфа-Банк", AlfaBankProvider),
}


def get_provider(provider_key: str, shop_id: str, secret_key: str,
                 webhook_url: str = "") -> PaymentProvider | None:
    """Создаёт экземпляр провайдера по ключу."""
    entry = PROVIDERS.get(provider_key)
    if entry:
        _, cls = entry
        if cls is ProdamusProvider:
            return cls(shop_id, secret_key, _get_session(), webhook_url=webhook_url)
        return cls(shop_id, secret_key, _get_session())
    return None


def provider_names() -> dict[str, str]:
    """Возвращает {key: display_name} доступных провайдеров."""
    return {k: v[0] for k, v in PROVIDERS.items()}
