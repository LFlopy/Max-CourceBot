import unittest

from admin_panel.keyboards import admin_tariff_settings


class RepeatableTariffTests(unittest.TestCase):
    def test_admin_keyboard_displays_repeat_setting(self):
        keyboard = admin_tariff_settings(7, True, allow_repeat=True)
        buttons = keyboard["payload"]["buttons"]

        repeat_button = next(
            row[0] for row in buttons
            if row[0]["payload"] == "adm:toggle_repeat:7"
        )
        self.assertEqual(repeat_button["text"], "🔁 Повторное получение: да")


if __name__ == "__main__":
    unittest.main()
