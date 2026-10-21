"""Unit tests for find_all (combined ebook + app discovery)."""
import unittest
from unittest import mock

import requests

import find_all as find_all_mod
from find_all import (apps_for, curated_apps, find_all, find_all_message,
                      find_all_keyboard, search_repos)


class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError("HTTP %d" % self.status_code)


def _items(*repos):
    return {"items": [
        {"full_name": full, "description": desc,
         "stargazers_count": stars}
        for full, desc, stars in repos
    ]}


class SearchReposTests(unittest.TestCase):
    def test_parses_and_orders_items(self):
        client = mock.Mock()
        client.get.return_value = FakeResponse(_items(
            ("a/one", "First", 10), ("b/two", "Second", 99),
            ("bad", "No slash", 1)))
        got = search_repos("ai agent", client=client)
        self.assertEqual([g["id"] for g in got], ["a/one", "b/two"])
        self.assertEqual(got[0]["stars"], 10)
        self.assertEqual(got[0]["url"], "https://github.com/a/one")
        self.assertTrue(got[0]["aid"])

    def test_empty_query(self):
        self.assertEqual(search_repos("   "), [])

    def test_limit(self):
        client = mock.Mock()
        client.get.return_value = FakeResponse(_items(
            *[(("r/%d" % i), "d", i) for i in range(10)]))
        self.assertEqual(len(search_repos("x", limit=3, client=client)), 3)


class AppsForTests(unittest.TestCase):
    def test_curated_plus_live_deduped(self):
        client = mock.Mock()
        # live returns one curated repo (firecrawl) + a new one
        client.get.return_value = FakeResponse(_items(
            ("firecrawl/firecrawl", "dup", 1), ("zbrand/new", "fresh", 5)))
        apps = apps_for("agents", "ai agent", client=client)
        ids = [a["id"] for a in apps]
        self.assertEqual(ids.count("firecrawl/firecrawl"), 1)
        self.assertIn("zbrand/new", ids)
        self.assertIn("langchain-ai/langchain", ids)

    def test_live_failure_keeps_curated(self):
        client = mock.Mock()
        client.get.side_effect = requests.ConnectionError("down")
        apps = apps_for("browser", "browser automation", client=client)
        self.assertEqual(len(apps), len(find_all_mod.CURATED_AI_REPOS["browser"]))

    def test_no_curated_for_unknown_key_uses_live_only(self):
        client = mock.Mock()
        client.get.return_value = FakeResponse(_items(("solo/x", "y", 1)))
        apps = apps_for(None, "solo", client=client)
        self.assertEqual([a["id"] for a in apps], ["solo/x"])


class FindAllTests(unittest.TestCase):
    def test_combines_ebooks_and_apps(self):
        client = mock.Mock()
        client.get.return_value = FakeResponse(_items(("x/app", "d", 3)))
        ebooks = [{"id": "b1", "title": "A Book",
                   "source_url": "https://www.gutenberg.org/ebooks/1.epub"}]
        result = find_all("ai agent", key="agents", client=client, ebooks=ebooks)
        self.assertEqual(result["topic"], "ai agent")
        self.assertEqual(result["ebooks"], ebooks)
        self.assertTrue(result["apps"])

    def test_empty_is_fine(self):
        client = mock.Mock()
        client.get.return_value = FakeResponse({"items": []})
        result = find_all("nothing", client=client)
        self.assertEqual(result["ebooks"], [])
        self.assertIsInstance(result["apps"], list)


class MessageKeyboardTests(unittest.TestCase):
    def _result(self, n_books=2, n_apps=3):
        return {
            "topic": "ai agent",
            "ebooks": [{"title": "Book %d" % i,
                        "source_url": "https://x.org/%d.epub" % i}
                       for i in range(n_books)],
            "apps": [{"title": "App %d" % i, "url": "https://github.com/a/%d" % i}
                     for i in range(n_apps)],
        }

    def test_message_counts(self):
        text = find_all_message(self._result(2, 3))
        self.assertIn("Open ebooks: 2", text)
        self.assertIn("Apps / source code: 3", text)
        self.assertIn("ai agent", text)

    def test_message_empty_note(self):
        text = find_all_message(self._result(0, 0))
        self.assertIn("No open-licensed ebooks matched", text)
        self.assertIn("No apps matched", text)

    def test_keyboard_buttons(self):
        kb = find_all_keyboard(self._result(2, 3), "abcdef123456")
        data = [btn["callback_data"] for row in kb["inline_keyboard"]
                for btn in row]
        self.assertIn("fae:abcdef123456", data)
        self.assertIn("fap:abcdef123456:0", data)
        self.assertIn("fap:abcdef123456:2", data)
        self.assertIn("fa:run", data)
        self.assertIn("ui:home", data)


    def test_studied_subtopic_includes_info(self):
        client = mock.Mock()
        client.get.return_value = FakeResponse(_items(("x/app", "d", 3)))
        result = find_all("website clone", key="cloning", client=client)
        self.assertIn("info", result)
        self.assertTrue(result["info"])  # how-cloning-works blurb
        text = find_all_message(result)
        self.assertIn("ℹ️", text)
        self.assertIn("mirror the site", text)

    def test_freeform_has_no_info(self):
        client = mock.Mock()
        client.get.return_value = FakeResponse(_items(("x/app", "d", 3)))
        result = find_all("some random topic", client=client)
        self.assertEqual(result.get("info", ""), "")
        self.assertNotIn("ℹ️", find_all_message(result))

    def test_cloning_curated_present(self):
        self.assertIn("cloning", find_all_mod.CURATED_AI_REPOS)
        self.assertTrue(any("cloner" in a[0].lower() or "clone" in a[1].lower()
                            for a in find_all_mod.CURATED_AI_REPOS["cloning"]))


if __name__ == "__main__":
    unittest.main()
