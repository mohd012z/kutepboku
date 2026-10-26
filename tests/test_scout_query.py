import unittest

from agent import resolve_scout_query


class ScoutQueryTests(unittest.TestCase):
    def test_manual_override_has_priority(self):
        self.assertEqual(resolve_scout_query({"CUSTOM_QUERY": " Embedded Rust ", "SCOUT_QUERY": "python"}),
                         "Embedded Rust")

    def test_scheduled_query_fallback(self):
        self.assertEqual(resolve_scout_query({"CUSTOM_QUERY": " ", "SCOUT_QUERY": "systems design"}),
                         "systems design")

    def test_default(self):
        self.assertEqual(resolve_scout_query({}), "python programming")

    def test_rejects_excessive_query(self):
        with self.assertRaises(ValueError):
            resolve_scout_query({"CUSTOM_QUERY": "x" * 201})
