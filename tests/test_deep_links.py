import unittest

from utils import build_tariff_deep_link, parse_tariff_start_payload


class DeepLinkTests(unittest.TestCase):
    def test_parse_tariff_start_payload_valid_values(self):
        self.assertEqual(parse_tariff_start_payload("tariff_1"), 1)
        self.assertEqual(parse_tariff_start_payload("tariff_15"), 15)
        self.assertEqual(parse_tariff_start_payload("tariff_999"), 999)
        self.assertEqual(parse_tariff_start_payload(" tariff_15 "), 15)

    def test_parse_tariff_start_payload_invalid_values(self):
        for payload in [
            "tariff_",
            "tariff_0",
            "tariff_-1",
            "tariff_test",
            "tariff_15_extra",
            "course_15",
            "https://example.com",
            "",
            "   ",
            None,
        ]:
            with self.subTest(payload=payload):
                self.assertIsNone(parse_tariff_start_payload(payload))

    def test_build_tariff_deep_link(self):
        self.assertEqual(
            build_tariff_deep_link("MyCourseBot", 15),
            "https://max.ru/MyCourseBot?start=tariff_15",
        )

    def test_build_tariff_deep_link_normalizes_username(self):
        for username in ["@MyCourseBot", " MyCourseBot "]:
            with self.subTest(username=username):
                self.assertEqual(
                    build_tariff_deep_link(username, 15),
                    "https://max.ru/MyCourseBot?start=tariff_15",
                )

    def test_build_tariff_deep_link_rejects_invalid_values(self):
        for bot_username, tariff_id in [
            ("", 15),
            ("MyCourseBot", 0),
            ("MyCourseBot", -1),
            ("MyCourseBot", "test"),
        ]:
            with self.subTest(bot_username=bot_username, tariff_id=tariff_id):
                with self.assertRaises(ValueError):
                    build_tariff_deep_link(bot_username, tariff_id)


if __name__ == "__main__":
    unittest.main()
