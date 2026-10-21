"""Tests for agent_skills: the built-in agent that studies + levels up."""
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from agent_skills import (AgentSkills, XP_EFFECTIVE, XP_NEW_TOPIC,
                          XP_PER_LEVEL, XP_PER_SEARCH)


def _agent(tmp):
    return AgentSkills(str(Path(tmp) / "state" / "agent_knowledge.json"))


class RecordSearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_first_search_gains_base_plus_new_topic(self):
        a = _agent(self.tmp.name)
        gained, level = a.record_search("machine learning", 5)
        self.assertEqual(gained, XP_PER_SEARCH + XP_NEW_TOPIC + XP_EFFECTIVE)
        self.assertEqual(level, 1)
        self.assertEqual(a.total_searches, 1)
        self.assertEqual(a.distinct_topics, 1)

    def test_repeat_same_topic_no_new_topic_bonus(self):
        a = _agent(self.tmp.name)
        a.record_search("machine learning", 1)
        gained, _ = a.record_search("machine learning", 1)
        # base only (1 result < effective min, topic already known)
        self.assertEqual(gained, XP_PER_SEARCH)
        self.assertEqual(a.distinct_topics, 1)

    def test_domain_bucketing(self):
        a = _agent(self.tmp.name)
        a.record_search("forex trading", 1)
        a.record_search("android automation", 1)
        domains = dict(a.domains())
        self.assertIn("Trading & Finance", domains)
        self.assertIn("Android", domains)

    def test_persists_across_instances(self):
        path = str(Path(self.tmp.name) / "agent.json")
        a = AgentSkills(path)
        a.record_search("quantum physics", 4)
        xp = a.data["xp"]
        b = AgentSkills(path)  # reloaded
        self.assertEqual(b.data["xp"], xp)
        self.assertEqual(b.distinct_topics, 1)

    def test_corrupt_file_fails_open(self):
        path = str(Path(self.tmp.name) / "agent.json")
        a = AgentSkills(path)
        a.record_search("a", 1)
        with open(path, "w") as fh:
            fh.write("{not valid json")
        b = AgentSkills(path)
        self.assertEqual(b.total_searches, 0)  # reset, not crash

    def test_study_log_capped_and_ordered(self):
        a = _agent(self.tmp.name)
        for i in range(80):
            a.record_search("topic %d" % i, 0)
        self.assertLessEqual(len(a.study_log(8)), 8)
        self.assertEqual(len(a.data["log"]), 60)  # LOG_CAP


class LevelTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_level_1_at_start(self):
        a = _agent(self.tmp.name)
        self.assertEqual(a.level(), 1)
        self.assertEqual(a.into(), 0)
        self.assertEqual(a.needed(), XP_PER_LEVEL)

    def test_level_up_at_threshold(self):
        a = _agent(self.tmp.name)
        a.data["xp"] = XP_PER_LEVEL - 1
        a.save()
        self.assertEqual(a.level(), 1)
        # one effective new-topic search crosses the boundary
        gained, level = a.record_search("brand new domain", 5)
        self.assertGreaterEqual(level, 2)
        self.assertEqual(a.into(), a.data["xp"] % XP_PER_LEVEL)


class SummaryTextTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_summary_has_core_fields(self):
        a = _agent(self.tmp.name)
        a.record_search("forex trading", 4)
        text = a.summary_text()
        self.assertIn("Skill level", text)
        self.assertIn("L1", text)
        self.assertIn("Domains studied", text)
        self.assertIn("Trading & Finance", text)
        self.assertIn("forex trading", text)

    def test_summary_empty_state(self):
        a = _agent(self.tmp.name)
        text = a.summary_text()
        self.assertIn("Skill level", text)
        self.assertIn("L1", text)
        self.assertNotIn("Domains studied", text)


if __name__ == "__main__":
    unittest.main()
