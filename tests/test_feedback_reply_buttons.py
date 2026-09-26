import sys
import types
import unittest
from unittest.mock import AsyncMock, patch

if "config" not in sys.modules:
    config_stub = types.ModuleType("config")
    config_stub.ADMIN_IDS = {101}
    config_stub.DATABASE_URL = "postgresql://test:test@localhost/test"
    sys.modules["config"] = config_stub

from admin_panel.handlers import handle_admin_callback, handle_admin_message
from fsm import set_state, user_states


class FeedbackReplyButtonsTests(unittest.IsolatedAsyncioTestCase):
    admin_id = 101
    target_id = 202

    def setUp(self):
        user_states.clear()

    def tearDown(self):
        user_states.clear()

    async def test_reply_is_staged_before_sending(self):
        bot = AsyncMock()
        set_state(self.admin_id, "adm_reply_feedback", target_user_id=self.target_id)

        handled = await handle_admin_message(
            bot,
            self.admin_id,
            self.admin_id,
            "Ответ пользователю",
            attachments=[{"type": "image", "payload": {"token": "image-token"}}],
        )

        self.assertTrue(handled)
        self.assertEqual(user_states[self.admin_id]["state"], "adm_feedback_add_buttons")
        self.assertEqual(user_states[self.admin_id]["feedback_text"], "Ответ пользователю")
        self.assertEqual(
            user_states[self.admin_id]["feedback_media"],
            [{"type": "image", "token": "image-token"}],
        )
        bot.send_message.assert_awaited_once()
        self.assertEqual(bot.send_message.await_args.args[0], self.admin_id)

    async def test_send_feedback_reply_with_link_button(self):
        bot = AsyncMock()
        set_state(
            self.admin_id,
            "adm_feedback_buttons_added",
            target_user_id=self.target_id,
            feedback_text="Ответ пользователю",
            feedback_media=[],
            feedback_buttons=[
                {"kind": "link", "text": "Подробнее", "url": "https://example.com"},
            ],
        )
        update = {
            "callback": {
                "callback_id": "callback-id",
                "payload": "adm:fb_send_with_btns",
                "user": {"user_id": self.admin_id},
            },
            "message": {
                "body": {"mid": "message-id"},
                "recipient": {"chat_id": self.admin_id},
            },
        }

        with (
            patch("admin_panel.handlers.is_admin", return_value=True),
            patch(
                "admin_panel.handlers.db.get_bot_text",
                new=AsyncMock(return_value="Ответ администрации: Ответ пользователю"),
            ),
        ):
            handled = await handle_admin_callback(bot, update)

        self.assertTrue(handled)
        user_message = next(
            call for call in bot.send_message.await_args_list
            if call.args[0] == self.target_id
        )
        keyboard = user_message.kwargs["keyboard"]
        self.assertEqual(
            keyboard["payload"]["buttons"],
            [[{"type": "link", "text": "Подробнее", "url": "https://example.com"}]],
        )
        self.assertEqual(user_states[self.target_id]["state"], "waiting_feedback")
        self.assertNotIn(self.admin_id, user_states)

    async def test_tariff_button_is_added_to_feedback_reply(self):
        bot = AsyncMock()
        bot.edit_message.return_value = True
        set_state(
            self.admin_id,
            "adm_feedback_add_buttons",
            target_user_id=self.target_id,
            feedback_text="Ответ пользователю",
            feedback_media=[],
            feedback_buttons=[],
        )
        update = {
            "callback": {
                "callback_id": "callback-id",
                "payload": "adm:fb_btn_tariff:15",
                "user": {"user_id": self.admin_id},
            },
            "message": {
                "body": {"mid": "message-id"},
                "recipient": {"chat_id": self.admin_id},
            },
        }

        with (
            patch("admin_panel.handlers.is_admin", return_value=True),
            patch(
                "admin_panel.handlers.db.get_tariff",
                new=AsyncMock(return_value={"id": 15, "name": "Тариф Pro"}),
            ),
        ):
            handled = await handle_admin_callback(bot, update)

        self.assertTrue(handled)
        self.assertEqual(user_states[self.admin_id]["state"], "adm_feedback_buttons_added")
        self.assertEqual(
            user_states[self.admin_id]["feedback_buttons"],
            [{"kind": "tariff", "text": "Тариф Pro", "tariff_id": 15}],
        )


if __name__ == "__main__":
    unittest.main()
