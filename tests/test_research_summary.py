"""Tests for research_summary: the digest (LLM + deterministic) must carry a
HOW TO APPLY section so the agent not only lists sources but teaches use."""
import unittest

from research_summary import build_source_lines, deterministic_digest


def _apps(n=6):
    return [{"id": "o/r%d" % i, "title": "r%d" % i,
             "desc": "desc %d" % i, "url": "https://github.com/o/r%d" % i,
             "stars": 100 - i} for i in range(n)]


class DeterministicDigestTests(unittest.TestCase):
    def test_includes_how_to_apply_section(self):
        d = deterministic_digest("machine learning", _apps(6),
                                 {"npm": [{"id": "pkg", "desc": "a pkg"}]})
        self.assertIn("HOW TO APPLY:", d)
        # points at the most-used item to start with
        self.assertIn("o/r0", d)
        self.assertIn("KEY RESOURCES:", d)
        self.assertIn("NOTES:", d)

    def test_empty_sources_still_says_no_sources(self):
        d = deterministic_digest("nonsense topic", [], {})
        self.assertIn("No sources", d)

    def test_how_to_apply_references_20mb_rule(self):
        d = deterministic_digest("web automation", _apps(8), {})
        self.assertIn("20 MB", d)


class BuildSourceLinesTests(unittest.TestCase):
    def test_flattens_apps_and_sources(self):
        lines = build_source_lines(_apps(3), {"crates": [{"id": "lib"}]})
        self.assertEqual(len(lines), 4)
        self.assertTrue(lines[0].startswith("[GitHub]"))
        self.assertIn("[crates] lib", lines[-1])


if __name__ == "__main__":
    unittest.main()
