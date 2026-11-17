import unittest
from runner import validate_worker_origin

class OriginTests(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(validate_worker_origin("https://worker.example"), "https://worker.example")
    def test_reject_invalid(self):
        for value in ("http://worker.example", "https://user@worker.example", "https://worker.example/path", "https://worker.example:8443", "https://worker.example/"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    validate_worker_origin(value)
