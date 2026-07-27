import unittest
import sys
import types

if "aiohttp" not in sys.modules:
    aiohttp_stub = types.ModuleType("aiohttp")
    aiohttp_stub.ClientSession = object
    aiohttp_stub.BasicAuth = object
    aiohttp_stub.ClientTimeout = lambda *args, **kwargs: None
    sys.modules["aiohttp"] = aiohttp_stub

from payments import ProdamusProvider


class ProdamusSignatureTests(unittest.TestCase):
    def test_signature_uses_sorted_post_data_and_escaped_slashes(self):
        data = {
            "status": "success",
            "products[0][price]": "100.00",
            "products[0][name]": "Course / Basic",
            "order_id": "abc-123",
            "sign": "received-signature",
        }

        self.assertEqual(
            ProdamusProvider._prepare_signature_data(data),
            {
                "order_id": "abc-123",
                "products": [{"name": "Course / Basic", "price": "100.00"}],
                "status": "success",
            },
        )
        self.assertEqual(
            ProdamusProvider.create_signature(data, "secret"),
            "032eef2d56743a158409cffa4e1e27f3fd6b5f2b4346be293c1cf73d32fb16f2",
        )

    def test_verify_signature_allows_header_value_case_and_spaces(self):
        data = {"order_id": "abc-123", "status": "success"}
        signature = ProdamusProvider.create_signature(data, "secret")

        self.assertTrue(
            ProdamusProvider.verify_signature(data, "secret", f" {signature.upper()} ")
        )
        self.assertFalse(ProdamusProvider.verify_signature(data, "wrong", signature))


if __name__ == "__main__":
    unittest.main()
