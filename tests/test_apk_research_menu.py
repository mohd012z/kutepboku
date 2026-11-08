import unittest
from apk_research_menu import TOPICS, keyboard, handle_callback

class ResearchMenuTests(unittest.TestCase):
    def test_six_topics(self):
        self.assertEqual(len(TOPICS), 6)
    def test_unique_callbacks(self):
        callbacks = [row[0]["callback_data"] for row in keyboard()["inline_keyboard"]]
        self.assertEqual(len(callbacks), len(set(callbacks)))
    def test_all_topics(self):
        for topic in TOPICS:
            with self.subTest(topic=topic):
                result = handle_callback("apk:v1:" + topic, user_id=10, allowed_user_ids={10})
                self.assertTrue(result["ok"])
                self.assertEqual(result["evidence"]["delivery"], "disabled")
    def test_unauthorized(self):
        self.assertFalse(handle_callback("apk:v1:tools", user_id=9, allowed_user_ids={10})["ok"])
    def test_unknown(self):
        self.assertFalse(handle_callback("apk:v1:unknown", user_id=10, allowed_user_ids={10})["ok"])
    def test_wrong_prefix(self):
        self.assertFalse(handle_callback("sr:tools", user_id=10, allowed_user_ids={10})["ok"])
    def test_oversize(self):
        self.assertFalse(handle_callback("apk:v1:" + "a"*100, user_id=10, allowed_user_ids={10})["ok"])
    def test_invalid_type(self):
        self.assertFalse(handle_callback(None, user_id=10, allowed_user_ids={10})["ok"])
    def test_deterministic(self):
        a = handle_callback("apk:v1:ads", user_id=10, allowed_user_ids={10})
        b = handle_callback("apk:v1:ads", user_id=10, allowed_user_ids={10})
        self.assertEqual(a, b)
    def test_no_sensitive_payload(self):
        r = handle_callback("apk:v1:security", user_id=10, allowed_user_ids={10})
        self.assertNotIn("token", str(r).lower())

if __name__ == "__main__":
    unittest.main()
