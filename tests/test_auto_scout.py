import unittest
from unittest import mock
from unittest.mock import MagicMock

import auto_scout
from auto_scout import (AUTO_CATEGORIES, AUTO_TOOLS, deliver_zip,
                        download_zip, trending_repos)

TREND_HTML = """
<article class="Box-row"> <h2> <a href="/MadsLorentzen/ai-job-search">A</a></h2> </article>
<article class="Box-row"> <h2> <a href="/cloudflare/security-audit-skill">B</a></h2> </article>
<article class="Box-row"> <h2> <a href="/MadsLorentzen/ai-job-search">dup</a></h2> </article>
<article class="Box-row"> <h2> <a href="/stablyai/orca">C</a></h2> </article>
"""


class TrendingTests(unittest.TestCase):
    def _client(self, text):
        client = MagicMock()
        response = MagicMock()
        response.raise_for_status = MagicMock()
        response.text = text
        client.get = MagicMock(return_value=response)
        return client

    def test_parses_and_dedupes(self):
        items = trending_repos(limit=10, client=self._client(TREND_HTML))
        self.assertEqual([i["id"] for i in items],
                         ["MadsLorentzen/ai-job-search",
                          "cloudflare/security-audit-skill", "stablyai/orca"])
        self.assertEqual(items[0]["url"], "https://github.com/MadsLorentzen/ai-job-search")

    def test_respects_limit(self):
        items = trending_repos(limit=2, client=self._client(TREND_HTML))
        self.assertEqual(len(items), 2)

    def test_no_repos_raises(self):
        with self.assertRaises(ValueError):
            trending_repos(client=self._client("<html></html>"))


class DefaultBranchTests(unittest.TestCase):
    def test_returns_branch(self):
        client = MagicMock()
        response = MagicMock()
        response.raise_for_status = MagicMock()
        response.json = MagicMock(return_value={"default_branch": "dev"})
        client.get = MagicMock(return_value=response)
        self.assertEqual(auto_scout._default_branch("owner/repo", client=client), "dev")

    def test_network_error_propagates(self):
        client = MagicMock()
        client.get = MagicMock(side_effect=Exception("boom"))
        with self.assertRaises(Exception):
            auto_scout._default_branch("owner/repo", client=client)


class DownloadZipTests(unittest.TestCase):
    def _session(self, data, status=200):
        session = MagicMock()
        response = MagicMock()
        response.status_code = status
        response.iter_content = MagicMock(return_value=iter([data]))
        response.close = MagicMock()
        response.raise_for_status = MagicMock()
        session.get = MagicMock(return_value=response)
        return session

    def test_valid_zip(self):
        data = b"PK\x03\x04" + b"z" * 600
        data2, url = download_zip("owner/repo", "main", session=self._session(data))
        self.assertEqual(data2, data)
        self.assertEqual(url, "https://github.com/owner/repo/archive/refs/heads/main.zip")

    def test_too_large_raises(self):
        big = b"PK\x03\x04" + b"x" * (21 * 1024 * 1024)
        with self.assertRaises(ValueError):
            download_zip("o/r", "main", session=self._session(big),
                         max_bytes=20 * 1024 * 1024)

    def test_bad_signature_raises(self):
        with self.assertRaises(ValueError):
            download_zip("o/r", "main", session=self._session(b"NOTAZIP" + b"z" * 600))


class DeliverZipTests(unittest.TestCase):
    def test_delivers(self):
        item = {"id": "owner/repo", "title": "Tool", "branch": "main",
                "url": "https://github.com/owner/repo"}
        data = b"PK\x03\x04" + b"z" * 500
        session = MagicMock()
        with mock.patch.object(auto_scout, "download_zip",
                               return_value=(data, "https://x/r.zip")) as dz, \
             mock.patch("agent.send") as snd:
            size, url = deliver_zip("123:T", "456", item, session=session)
        self.assertEqual(size, len(data))
        snd.assert_called_once()
        self.assertEqual(snd.call_args.args[3], "repo-main.zip")

    def test_invalid_id_raises(self):
        with self.assertRaises(ValueError):
            deliver_zip("123:T", "456", {"id": "bad"}, session=MagicMock())


class ConfigTests(unittest.TestCase):
    def test_categories_have_topics(self):
        for key, label, topic in AUTO_CATEGORIES:
            self.assertTrue(topic.strip())
        self.assertEqual(AUTO_CATEGORIES[0][0], "hack")
        self.assertEqual(AUTO_CATEGORIES[1][0], "android")

    def test_tools_have_repo_paths(self):
        for key, label, repo in AUTO_TOOLS:
            self.assertEqual(repo.count("/"), 1)


if __name__ == "__main__":
    unittest.main()
