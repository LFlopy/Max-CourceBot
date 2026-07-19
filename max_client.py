
import json
import asyncio
import aiohttp

API = "https://platform-api2.max.ru"
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30)


class MaxBot:
    """Client for the MAX Bot API."""
    def __init__(self, token: str):
        self.token = token
        self.headers = {
            "Authorization": token,
            "Content-Type": "application/json",
        }
        self._session: aiohttp.ClientSession | None = None

    async def start(self):
        """Call the MAX Bot API."""
        self._session = aiohttp.ClientSession(timeout=REQUEST_TIMEOUT)

    async def stop(self):
        """Call the MAX Bot API."""
        if self._session:
            await self._session.close()

    async def _request(self, method: str, path: str, **kwargs) -> tuple[int, dict]:
        url = f"{API}{path}"
        async with self._session.request(method, url, headers=self.headers, **kwargs) as r:
            try:
                data = await r.json()
            except Exception:
                data = {"raw": await r.text()}
            return r.status, data

    async def get_me(self) -> dict:
        """Call the MAX Bot API."""
        _, data = await self._request("GET", "/me")
        return data

    async def cleanup_webhooks(self):
        """Call the MAX Bot API."""
        _, data = await self._request("GET", "/subscriptions")
        subs = data.get("subscriptions", [])
        for sub in subs:
            url = sub.get("url", "")
            if url:
                await self._request("DELETE", "/subscriptions", params={"url": url})
                print(f"  Удалён webhook: {url}")
        if not subs:
            print("  Webhook-ов нет")

    async def subscribe_webhook(
        self,
        url: str,
        update_types: list[str] | None = None,
        secret: str | None = None,
    ) -> tuple[bool, dict]:
        """POST /subscriptions — подписывает бота на доставку обновлений
        через webhook. После активной подписки long polling не работает."""
        payload: dict = {"url": url}
        if update_types:
            payload["update_types"] = update_types
        if secret:
            payload["secret"] = secret
        status, data = await self._request("POST", "/subscriptions", json=payload)
        ok = status == 200 and data.get("success", True) is not False
        if not ok:
            print(f"  subscribe_webhook ERROR: status={status} data={data}")
        return ok, data

    async def unsubscribe_webhook(self, url: str) -> bool:
        """DELETE /subscriptions — отписывает бота от webhook'а."""
        status, data = await self._request(
            "DELETE", "/subscriptions", params={"url": url},
        )
        if status != 200:
            print(f"  unsubscribe_webhook ERROR: status={status} data={data}")
            return False
        return True

    async def send_message(
        self,
        chat_id: int,
        text: str,
        keyboard: dict | None = None,
        fmt: str | None = None,
    ) -> dict:
        """Call the MAX Bot API."""
        payload = {"text": text}
        if fmt:
            payload["format"] = fmt
        if keyboard:
            payload["attachments"] = [keyboard]

        status, data = await self._request(
            "POST", "/messages",
            params={"chat_id": chat_id},
            json=payload,
        )
        if status != 200:
            status, data = await self._request(
                "POST", "/messages",
                params={"user_id": chat_id},
                json=payload,
            )
        return data

    async def send_file_token(self, user_id: int, token: str, text: str = "") -> dict:
        """Отправляет ранее загруженный файл по token пользователю в личку."""
        payload = {
            "text": text,
            "attachments": [{"type": "file", "payload": {"token": token}}],
        }
        _, data = await self._request(
            "POST", "/messages",
            params={"user_id": user_id},
            json=payload,
        )
        return data

    async def forward_attachment(self, chat_id: int, att_type: str, token: str,
                                 text: str = "", keyboard: dict | None = None) -> dict:
        """Пересылает вложение (image/file/video/audio) по token."""
        payload: dict = {
            "text": text,
            "attachments": [{"type": att_type, "payload": {"token": token}}],
        }
        if keyboard:
            payload["attachments"].append(keyboard)
        status, data = await self._request(
            "POST", "/messages",
            params={"chat_id": chat_id},
            json=payload,
        )
        if status != 200:
            status, data = await self._request(
                "POST", "/messages",
                params={"user_id": chat_id},
                json=payload,
            )
        return data

    async def edit_message(
        self,
        message_id: str,
        text: str,
        keyboard: dict | None = None,
    ) -> bool:
        """Возвращает True при успехе, False при ошибке."""
        if not message_id:
            print("  edit_message: message_id пустой, пропускаем")
            return False
        payload = {"text": text}
        if keyboard:
            payload["attachments"] = [keyboard]

        status, data = await self._request(
            "PUT", "/messages",
            params={"message_id": message_id},
            json=payload,
        )
        if status != 200:
            print(f"  edit_message ERROR: status={status}, data={data}")
            return False
        return True

    async def upload_file(self, file_path: str, file_name: str,
                          file_type: str = "file") -> dict | None:
        """Загружает файл в два шага: получает URL, затем отправляет файл."""
        status, data = await self._request(
            "POST", "/uploads", params={"type": file_type},
        )
        upload_url = data.get("url")
        if not upload_url:
            print(f"  upload ERROR step1: status={status}, data={data}")
            return None

        headers = {"Authorization": self.token}
        with open(file_path, "rb") as f:
            form = aiohttp.FormData()
            form.add_field("data", f, filename=file_name,
                           content_type="application/octet-stream")
            async with self._session.post(upload_url, headers=headers, data=form) as r:
                if r.status == 200:
                    return await r.json()
                print(f"  upload ERROR step2: {r.status}, {await r.text()}")
                return None

    async def send_file(self, chat_id: int, file_path: str, file_name: str,
                        text: str = "") -> dict:
        """Загружает и отправляет файл пользователю."""
        upload = await self.upload_file(file_path, file_name)
        if not upload:
            return await self.send_message(chat_id, "Ошибка загрузки файла")
        token = upload.get("token", "")
        payload = {
            "text": text,
            "attachments": [{"type": "file", "payload": {"token": token}}],
        }

        for _ in range(3):
            status, data = await self._request(
                "POST", "/messages",
                params={"chat_id": chat_id},
                json=payload,
            )
            if status != 200:
                status, data = await self._request(
                    "POST", "/messages",
                    params={"user_id": chat_id},
                    json=payload,
                )
            if status == 200:
                return data
            if "not.ready" in str(data):
                await asyncio.sleep(2)
                continue
            break
        return data

    async def answer_callback(self, callback_id: str, text: str = ""):
        """Call the MAX Bot API."""
        payload = {"callback_id": callback_id}
        if text:
            payload["notification"] = text
        await self._request("POST", "/answers", json=payload)

    async def add_chat_member(self, chat_id: int, user_ids: list[int]) -> bool:
        """Call the MAX Bot API."""
        status, data = await self._request(
            "POST", f"/chats/{chat_id}/members",
            json={"user_ids": user_ids},
        )
        if status != 200:
            print(f"  add_member ERROR: chat={chat_id} status={status} data={data}")
            return False
        return True

    async def is_chat_member(self, chat_id: int, user_id: int) -> bool:
        """Call the MAX Bot API."""
        status, data = await self._request(
            "GET", f"/chats/{chat_id}/members",
            params={"user_ids": user_id},
        )
        if status != 200 or not data:
            return False
        members = data.get("members", [])
        for m in members:
            if m.get("user_id") == user_id:
                return True
        return False

    async def remove_chat_member(self, chat_id: int, user_id: int) -> bool:
        """Call the MAX Bot API."""
        status, data = await self._request(
            "DELETE", f"/chats/{chat_id}/members",
            params={"user_id": user_id},
        )
        if status != 200:
            print(f"  remove_member ERROR: chat={chat_id} user={user_id} status={status} data={data}")
            return False
        return True

    async def leave_chat(self, chat_id: int) -> bool:
        """Call the MAX Bot API."""
        status, data = await self._request(
            "DELETE", f"/chats/{chat_id}/members/me",
        )
        if status != 200:
            print(f"  leave_chat ERROR: chat={chat_id} status={status} data={data}")
            return False
        return True

    async def get_chats(self) -> list[dict]:
        """GET /chats — список всех чатов бота.
        ⚠️ MAX больше не поддерживает этот метод. Оставлен только для старых
        окружений, где endpoint ещё может отвечать. В рантайме используй
        локальный каталог db.get_all_bot_chats()."""
        _, data = await self._request("GET", "/chats")
        return data.get("chats", [])

    async def get_chat_info(self, chat_id: int) -> dict:
        """GET /chats/{chatId} — инфа по одному чату/каналу (title, link и т.д.).
        Используется на событии bot_added, т.к. само событие Update
        не содержит ни title, ни link — только chat_id и is_channel."""
        _, data = await self._request("GET", f"/chats/{chat_id}")
        return data

    async def poll(self, marker: int | None = None) -> dict:
        """Call the MAX Bot API."""
        params = {
            "timeout": 30,
            "types": "bot_started,message_created,message_callback",
        }
        if marker:
            params["marker"] = marker
        try:
            _, data = await self._request("GET", "/updates", params=params)
            print(f"  poll response: {str(data)[:600]}")
            return data
        except Exception as e:
            print(f"  poll error: {e}")
            await asyncio.sleep(3)
            return {}
