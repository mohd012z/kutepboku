"""msasoup built-in agent: studies + learns from every search, levels up.

The bot is itself an AI agent. Each search it runs is *recorded* as study:
the topic, what it found, which sources yielded. Over time it accumulates a
skill level (XP), a map of the domains it has studied (with depth), per-topic
yield history ("learning" which phrasings work), and a study log. All of it is
surfaced in the menu ("🧠 Agent — L{N}"), so the agent visibly improves as you
use it.

Persistence is a small JSON file (state/agent_knowledge.json) — durable across
restarts, atomic on write, and fail-open: any corruption resets to a fresh
agent rather than crashing a search.
"""
import json
import os
import re
import time
from collections import OrderedDict

DEFAULT_PATH = os.path.join("state", "agent_knowledge.json")

# domain bucket -> keywords (highest keyword-hit count wins; "General" fallback)
DOMAINS = OrderedDict([
    ("AI & Agents", ("ai", "agent", "llm", "gpt", "rag", "neural",
                     "machine learning", "deep learning", "ml")),
    ("Web Automation", ("web automation", "web scrape", "web scraping",
                        "browser automation", "playwright", "selenium",
                        "puppeteer", "crawler", "crawling")),
    ("Hacking & Security", ("hack", "security", "pentest", "penetration",
                            "cryptography", "red team")),
    ("Android", ("android", "kotlin", "uiautomator", "scrcpy", "appium")),
    ("Trading & Finance", ("forex", "trading", "finance", "crypto", "fx",
                           "invest", "stock", "market")),
    ("Science", ("physics", "chemistry", "biology", "quantum", "mathematics",
                 "astronomy")),
    ("Marketing & Ads", ("marketing", "advertis", "seo", "growth", "brand")),
    ("Engineering", ("programming", "software", "database", "api", "coding",
                     "compiler", "algorithm")),
    ("Humanities", ("philosophy", "history", "psychology", "economics",
                    "society", "culture")),
])

# XP model: +10 per search, +25 for a new topic, +5 when a search is effective.
XP_PER_SEARCH = 10
XP_NEW_TOPIC = 25
XP_EFFECTIVE = 5
EFFECTIVE_MIN_RESULTS = 3
XP_PER_LEVEL = 150
LOG_CAP = 60


def _domain(topic):
    t = (topic or "").lower()
    best_name, best_score = "General", 0
    for name, words in DOMAINS.items():
        score = sum(1 for w in words if w in t)
        if score > best_score:
            best_name, best_score = name, score
    return best_name


class AgentSkills:
    """Persistent study/learning state for the built-in agent."""

    def __init__(self, path=DEFAULT_PATH):
        self.path = path
        self.data = self._load()

    def _load(self):
        default = {"xp": 0, "searches": 0, "first_seen": None,
                   "last_seen": None, "topics": {}, "domains": {},
                   "log": []}
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            if not isinstance(data, dict):
                return default
            for key, value in default.items():
                data.setdefault(key, value)
            return data
        except (OSError, ValueError, TypeError):
            return default

    def save(self):
        directory = os.path.dirname(self.path)
        try:
            if directory:
                os.makedirs(directory, exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(self.data, handle, ensure_ascii=False)
            os.replace(tmp, self.path)
        except OSError:
            return False
        return True

    # ---- learning ---------------------------------------------------------
    def record_search(self, topic, n_results=0, source="search"):
        """Record one search as study. Returns (gained_xp, new_level)."""
        topic = (topic or "").strip()[:200]
        now = int(time.time())
        d = self.data
        d["first_seen"] = d["first_seen"] or now
        d["last_seen"] = now
        d["searches"] += 1
        gained = XP_PER_SEARCH
        topic_key = re.sub(r"\s+", " ", topic.lower())
        prev = d["topics"].get(topic_key)
        if prev is None:
            gained += XP_NEW_TOPIC
            d["topics"][topic_key] = {"times": 1, "best": n_results,
                                      "domain": _domain(topic)}
        else:
            prev["times"] += 1
            prev["best"] = max(prev.get("best", 0), n_results)
        if n_results >= EFFECTIVE_MIN_RESULTS:
            gained += XP_EFFECTIVE
        domain = _domain(topic)
        d["domains"][domain] = d["domains"].get(domain, 0) + 1
        d["xp"] = d.get("xp", 0) + gained
        d["log"].insert(0, {"topic": topic, "n": int(n_results),
                            "src": source, "t": now})
        d["log"] = d["log"][:LOG_CAP]
        self.save()
        return gained, self.level()

    # ---- querying ---------------------------------------------------------
    def level(self):
        return 1 + int(self.data.get("xp", 0) // XP_PER_LEVEL)

    def progress(self):
        """(xp_into_level, xp_needed_for_level) for the current level."""
        xp = self.data.get("xp", 0)
        return (xp % XP_PER_LEVEL, XP_PER_LEVEL)

    def into(self):
        return self.data.get("xp", 0) % XP_PER_LEVEL

    def needed(self):
        return XP_PER_LEVEL

    @property
    def total_searches(self):
        return int(self.data.get("searches", 0))

    @property
    def distinct_topics(self):
        return len(self.data.get("topics", {}))

    def domains(self):
        """{domain: depth} sorted by depth desc."""
        items = sorted(self.data.get("domains", {}).items(),
                       key=lambda kv: -kv[1])
        return items

    def top_topics(self, limit=8):
        topics = self.data.get("topics", {})
        ranked = sorted(topics.items(),
                        key=lambda kv: (-kv[1].get("best", 0),
                                        -kv[1].get("times", 0)))
        return [(topic, meta) for topic, meta in ranked[:limit]]

    def study_log(self, limit=8):
        return self.data.get("log", [])[:limit]

    # ---- presentation -----------------------------------------------------
    def summary_text(self):
        lv = self.level()
        into, needed = self.progress()
        domains = self.domains()
        lines = [
            "🧠 Built-in agent — self-studying from every search",
            "",
            "🎖️ Skill level: **L%d**  (%d/%d XP to L%d)"
            % (lv, into, needed, lv + 1),
            "📊 Searches: %d   •   Topics learned: %d"
            % (self.total_searches, self.distinct_topics),
        ]
        if domains:
            lines.append("\nDomains studied:")
            for name, depth in domains[:8]:
                bar = "▮" * min(depth, 10) + "▯" * max(0, 10 - depth)
                lines.append("  • %s  %s  (x%d)" % (name, bar, depth))
        top = self.top_topics(5)
        if top:
            lines.append("\nStrongest topics (best yield):")
            for topic, meta in top:
                lines.append("  • %s — best %d, studied x%d"
                             % (topic[:44], meta.get("best", 0),
                                meta.get("times", 1)))
        lines.append("\nEvery search you run makes me learn. Level me up.")
        return "\n".join(lines)


_global = None


def agent_skills(path=DEFAULT_PATH):
    global _global
    if _global is None or (path != DEFAULT_PATH):
        _global = AgentSkills(path)
    return _global
