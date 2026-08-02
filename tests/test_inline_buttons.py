import unittest

from utils import build_inline_keyboard, parse_inline_button_lines


class InlineButtonTests(unittest.TestCase):
    def test_parse_inline_button_lines(self):
        buttons, invalid = parse_inline_button_lines(
            "Купить - https://example.com/buy\n"
            "Подробнее — https://example.com/info"
        )

        self.assertIsNone(invalid)
        self.assertEqual(
            buttons,
            [
                {"kind": "link", "text": "Купить", "url": "https://example.com/buy"},
                {"kind": "link", "text": "Подробнее", "url": "https://example.com/info"},
            ],
        )

    def test_parse_inline_button_lines_returns_invalid_line(self):
        buttons, invalid = parse_inline_button_lines("Некорректная строка")

        self.assertEqual(buttons, [])
        self.assertEqual(invalid, "Некорректная строка")

    def test_build_inline_keyboard_for_tariff_and_link_buttons(self):
        keyboard = build_inline_keyboard([
            {"kind": "tariff", "text": "Тариф Pro", "tariff_id": 15},
            {"kind": "link", "text": "Сайт", "url": "https://example.com"},
        ])

        self.assertEqual(keyboard["type"], "inline_keyboard")
        self.assertEqual(
            keyboard["payload"]["buttons"],
            [
                [{"type": "callback", "text": "Тариф Pro", "payload": "pay:15"}],
                [{"type": "link", "text": "Сайт", "url": "https://example.com"}],
            ],
        )


if __name__ == "__main__":
    unittest.main()
