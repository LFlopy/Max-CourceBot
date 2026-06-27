"""Клиент MAX Bot API — проверенный формат."""

import json
import asyncio
import aiohttp

API = "https://platform-api.max.ru"


class MaxBot:
    def __init__(self, token: str):
        self.token = token
        self.headers = {
            "Authorization": token,
            "Content-Type": "application/json",
        }
        self._session: aiohttp.ClientSession | None = None

    async def start(self):
        self._session = aiohttp.ClientSession()

    async def stop(self):
        if self._session:
            await self._session.close()

    # ── Базовый запрос ───────────────────────────────────────
    async def _request(self, method: str, path: str, **kwargs) -> tuple[int, dict]:
        url = f"{API}{path}"
        async with self._session.request(method, url, headers=self.headers, **kwargs) as r:
            try:
                data = await r.json()
            except:
                data = {"raw": await r.text()}
            return r.status, data

    # ── Инфо о боте ──────────────────────────────────────────
    async def get_me(self) -> dict:
        _, data = await self._request("GET", "/me")
        return data

    # ── Удаление webhook-ов ──────────────────────────────────
    async def cleanup_webhooks(self):
        _, data = await self._request("GET", "/subscriptions")
        subs = data.get("subscriptions", [])
        for sub in subs:
            url = sub.get("url", "")
            if url:
                await self._request("DELETE", "/subscriptions", params={"url": url})
                print(f"  Удалён webhook: {url}")
        if not subs:
            print("  Webhook-ов нет")

    # ── Подписка на webhook ──────────────────────────────────
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

    # ── Отправка сообщения ───────────────────────────────────
    async def send_message(
        self,
        chat_id: int,
        text: str,
        keyboard: dict | None = None,
        fmt: str | None = None,
    ) -> dict:
        payload = {"text": text}
        if fmt:
            payload["format"] = fmt
        if keyboard:
            payload["attachments"] = [keyboard]

        # Пробуем chat_id, потом user_id
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

    # ── Редактирование сообщения ─────────────────────────────
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

    # ── Загрузка файла ───────────────────────────────────────
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

    # ── Отправка файла ─────────────────────────────────────────
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

    # ── Ответ на callback ────────────────────────────────────
    async def answer_callback(self, callback_id: str, text: str = ""):
        payload = {"callback_id": callback_id}
        if text:
            payload["notification"] = text
        await self._request("POST", "/answers", json=payload)

    # ── Добавление участника в чат ────────────────────────────
    async def add_chat_member(self, chat_id: int, user_ids: list[int]) -> bool:
        status, data = await self._request(
            "POST", f"/chats/{chat_id}/members",
            json={"user_ids": user_ids},
        )
        if status != 200:
            print(f"  add_member ERROR: chat={chat_id} status={status} data={data}")
            return False
        return True

    # ── Проверка участия в чате ──────────────────────────────
    async def is_chat_member(self, chat_id: int, user_id: int) -> bool:
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

    # ── Удаление участника из чата ────────────────────────────
    async def remove_chat_member(self, chat_id: int, user_id: int) -> bool:
        status, data = await self._request(
            "DELETE", f"/chats/{chat_id}/members",
            params={"user_id": user_id},
        )
        if status != 200:
            print(f"  remove_member ERROR: chat={chat_id} user={user_id} status={status} data={data}")
            return False
        return True

    # ── Выход из чата ────────────────────────────────────────
    async def leave_chat(self, chat_id: int) -> bool:
        status, data = await self._request(
            "DELETE", f"/chats/{chat_id}/members/me",
        )
        if status != 200:
            print(f"  leave_chat ERROR: chat={chat_id} status={status} data={data}")
            return False
        return True

    # ── Получить чаты бота ───────────────────────────────────
    async def get_chats(self) -> list[dict]:
        _, data = await self._request("GET", "/chats")
        return data.get("chats", [])

    # ── Long polling ─────────────────────────────────────────
    async def poll(self, marker: int | None = None) -> dict:
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