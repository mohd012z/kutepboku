"""Tests for prompt_forge (strong, evidence-first prompt builder)."""
import unittest
from unittest import mock

import requests

import prompt_forge
from prompt_forge import (CAPABILITIES, forge_menu, forge_prompt, prompt_text)


def _no_llm_client():
    """A client whose POST raises -> forces the deterministic template path
    (also works with no MINDA key in env)."""
    client = mock.Mock()
    client.post.side_effect = requests.ConnectionError("no llm in test")
    return client


class ForgeCapabilityTests(unittest.TestCase):
    def test_known_capability_forges_prompt(self):
        result = forge_prompt("developer", "fix a race condition in my "
                          "python worker", client=_no_llm_client())
        self.assertIsNotNone(result)
        self.assertEqual(result["mode"], "template")
        self.assertEqual(result["capability"], "developer")
        for header in ("ROLE", "TASK", "CONTEXT", "METHOD", "EVIDENCE RULES",
                       "OUTPUT FORMAT", "QUALITY GATES"):
            self.assertIn(header, result["prompt"])
        self.assertGreaterEqual(result["sections"], 7)

    def test_unknown_capability_returns_none(self):
        self.assertIsNone(forge_prompt("nope", "do a thing"))

    def test_empty_goal_returns_none(self):
        self.assertIsNone(forge_prompt("developer", "   "))

    def test_all_requested_capabilities_present(self):
        keys = {k for k, *_ in CAPABILITIES}
        for want in ("automation", "research", "creator", "developer",
                     "finding", "analysis", "data", "photo", "video"):
            self.assertIn(want, keys)
        self.assertIn("general", keys)


class ForgeAiModeTests(unittest.TestCase):
    def test_uses_llm_output_when_strong(self):
        client = mock.Mock()
        response = mock.Mock()
        response.json.return_value = {"choices": [{
            "message": {"content": (
                "ROLE\nYou are X.\nTASK\nDo Y.\nCONTEXT\nNone.\nMETHOD\n1.\n"
                "EVIDENCE RULES\n- cite.\nOUTPUT FORMAT\nclear.\n"
                "QUALITY GATES\n- check.\n" + "word " * 30)}}]}
        response.raise_for_status.return_value = None
        client.get = None
        client.post.return_value = response
        result = forge_prompt("research", "study the market",
                              client=client, base_url="http://x",
                              api_key="k")
        self.assertEqual(result["mode"], "ai")
        self.assertIn("You are X.", result["prompt"])
        client.post.assert_called_once()

    def test_falls_back_to_template_when_llm_fails(self):
        client = mock.Mock()
        client.post.side_effect = requests.ConnectionError("down")
        result = forge_prompt("photo", "edit a portrait", client=client,
                              base_url="http://x", api_key="k")
        self.assertEqual(result["mode"], "template")
        self.assertIn("EVIDENCE RULES", result["prompt"])

    def test_falls_back_when_no_key(self):
        result = forge_prompt("data", "clean a csv", client=mock.Mock(),
                              base_url=None, api_key=None)
        self.assertEqual(result["mode"], "template")


class ContextTests(unittest.TestCase):
    def test_context_is_embedded(self):
        result = forge_prompt("developer", "refactor the parser",
                              context="It's Python 3.13, no external deps.",
                              client=_no_llm_client())
        self.assertIn("Python 3.13", result["prompt"])

    def test_context_truncated(self):
        big = "x" * 5000
        result = forge_prompt("analysis", "t", context=big, client=_no_llm_client())
        self.assertLessEqual(len(result["prompt"]), 6000)


class PresentationTests(unittest.TestCase):
    def test_prompt_text_wraps_in_code_block(self):
        result = forge_prompt("general", "summarize a report", client=_no_llm_client())
        text = prompt_text(result)
        self.assertIn("```", text)
        self.assertIn("Copy & paste", text)

    def test_forge_menu_has_capability_buttons(self):
        menu = forge_menu()
        data = [btn["callback_data"] for row in menu["reply_markup"]["inline_keyboard"]
                for btn in row]
        self.assertIn("pf:cap:developer", data)
        self.assertIn("pf:cap:video", data)
        self.assertIn("pf:cap:automation", data)
        self.assertIn("ui:home", data)


if __name__ == "__main__":
    unittest.main()
