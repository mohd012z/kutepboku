"""msasoup conversational assistant layer: intent understanding, category menu,
and Telegram file delivery for open-licensed eBooks.

Design (fail-closed on rights, fail-open to search on LLM):
  * ask_intent(): one Minda chat call, strict JSON. Returns None when the LLM
    is unavailable so callers fall back to treating the raw text as a topic.
  * home_menu(): button grid (categories + free search).
  * delivery: download + sendDocument with signature/size validation reused
    from agent.py (safe_url host/IP policy, PDF/EPUB magic bytes, 20 MB cap).
"""
import json
import os
import re

import requests

from agent import download, send
from search_pagination import build_search_keyboard, new_search_session

# (key, label, search topic). Keys are short — callback_data must fit 64 bytes.
CATEGORIES = [
    ("ml", "🤖 Machine Learning", "machine learning"),
    ("ai", "🧠 Artificial Intelligence", "artificial intelligence"),
    ("cs", "💻 Computer Science", "computer science"),
    ("math", "📐 Mathematics", "mathematics"),
    ("phys", "⚛️ Physics", "physics"),
    ("chem", "🧪 Chemistry", "chemistry"),
    ("bio", "🧬 Biology", "biology"),
    ("phil", "📜 Philosophy", "philosophy"),
    ("hist", "🏛️ History", "history"),
    ("econ", "📈 Economics", "economics"),
    ("psych", "🧩 Psychology", "psychology"),
    ("med", "🩺 Medicine", "medicine"),
]

HOME_TEXT = (
    "🤖 msasoup — open-license eBook agent\n\n"
    "Pick a category or just tell me what you need, e.g. "
    "\"find a quantum computing book\". I search the whole open web "
    "(Internet Archive, Project Gutenberg, Open Library), keep only "
    "open-licensed books, and can send the file straight to you."
)

HELP_TEXT = (
    "How I work:\n"
    "• Tap a category button — I search open-licensed books for it.\n"
    "• Or type any request — I understand plain language.\n"
    "• I search across the whole open web: Internet Archive, Project "
    "Gutenberg and Open Library — only openly licensed books are offered "
    "(fail-closed: rather than hand you an unlicensed file, I return nothing).\n"
    "• Pick a book from the list, then choose Send file (I download and "
    "send it) or Link (I send the direct download link).\n"
    "• ✨ Find ALL — one topic → open ebooks AND the best apps / source "
    "code (GitHub, by stars) together.\n"
    "• 🪄 Prompt Forge — build a strong, evidence-first prompt for ANY AI "
    "(automation, research, developer, data science, photo, video…). Tap it, "
    "pick a capability, describe your task — I craft a ready-to-paste prompt "
    "with hard evidence rules (cite, label FACT/INFER/ASSUME, never "
    "fabricate) and quality gates.\n"
    "• 📣 AI Marketing — a ready-made agent: AI ad/marketing ebooks + the "
    "top AI marketing / ad-automation tools.\n"
    "• 🪞 Web & App Cloning (/clone) — how website/app cloning works + the "
    "top cloner tools (one-command AI site-to-app, React rebuilders, Go "
    "cloner) + related ebooks.\n"
    "• 🕵️ Hacking & Pen-Test (/hacking) — the recon→scan→exploit workflow + "
    "top tools (Metasploit, SQLMap, Nuclei, Katana, ffuf, subfinder, Nmap, "
    "httpx) + security ebooks.\n"
    "• 🔬 Reverse Engineering /apk (/reverse) — how to tear an apk/app down "
    "(jadx, apktool, Ghidra, Frida, objection) + related ebooks.\n"
    "• 📱 Termux & Chat Automation (/termux) — script an Android phone from "
    "Termux (uiautomator2, Airtest, ATX-Agent, scrcpy, Appium) — the "
    "DANA-Kaget / earning-bot pattern.\n"
    "• 🔎 Telegram Username Check (/tginfo) — how to look up a @username's "
    "details (id, profile, history) + scam-signal checklist.\n"
    "• 🕸️ Download a Website (Scam Check) (/webscam) — mirror any site "
    "offline (HTTrack, singleFile, Wayback) + red-flag checklist.\n"
    "• 🎓 Learning & School Programs (/learn) — how to learn a skill "
    "(free curricula + Anki spaced repetition + notes) and how to build a "
    "school program (self-hosted LMS: Moodle, Open edX).\n"
    "• 🧠 Agent — I'm a built-in AI agent that studies every search and "
    "levels up; open it to see my skill level, domains learned, and strongest "
    "topics.\n"
    "• Bottom-left ⋮ menu = quick commands (see below).\n"
    "\nCommands:\n"
    "/start — main menu\n"
    "/find — Find ALL (ebooks + apps) for a topic\n"
    "/prompt — Prompt Forge (strong AI prompts for any capability)\n"
    "/marketing — AI advertising & marketing (ebooks + apps)\n"
    "/clone — web & app cloning: info + tools\n"
    "/hacking — hacking & pen-test: info + tools\n"
    "/reverse — reverse engineering (apk): info + tools\n"
    "/termux — Termux menu (install + chat automation + related)\n"
    "/tginfo — check a Telegram username: info + tools\n"
    "/webscam — download any website (scam check): info + tools\n"
    "/learn — learning skill + school programs: info + tools\n"
    "/agent — my skill level & what I've learned\n"
    "/forex — forex trading: info + tools + books\n"
    "/android — android automation books\n"
    "/mql5 — trending EAs & indicators (MQL5)\n"
    "/tools — automation tools (hacking + Android)\n"
    "/help — this help\n"
    "/cancel — stop current action\n"
    "/status — admin diagnostics")

# (command, description, action). Single source of truth for the Telegram
# command menu (setMyCommands — the bottom-left ⋮ menu) and router dispatch.
BOT_COMMANDS = [
    ("start", "Open the main menu", "home"),
    ("forex", "Forex trading — info + tools + books", "find:forex"),
    ("hacking", "Hacking & pen-test — info + tools", "find:hacking"),
    ("reverse", "Reverse engineering (apk) — info + tools", "find:reverse"),
    ("termux", "Termux menu — install + chat automation + related", "termux_menu"),
    ("android", "Android automation books", "search:android automation"),
    ("mql5", "Trending EAs & indicators (MQL5)", "mql5_menu"),
    ("tools", "Automation tools (hacking + Android)", "auto_menu"),
    ("find", "Find ALL ebooks + apps for a topic", "find_menu"),
    ("prompt", "Prompt Forge — strong AI prompts for any capability",
     "prompt_menu"),
    ("marketing", "AI advertising & marketing agent (ebooks + apps)",
     "find:marketing"),
    ("clone", "Web & app cloning — info + top tools", "find:cloning"),
    ("tginfo", "Check a Telegram username (details + scam signals)", "find:tginfo"),
    ("webscam", "Download any website to check for scams", "find:webscam"),
    ("learn", "Learning skill + school programs (curricula + LMS)", "find:learn"),
    ("agent", "Built-in agent: skill level & what it has learned", "agent"),
    ("help", "Instructions & how to use", "help"),
    ("cancel", "Stop the current action", "cancel"),
    ("status", "Admin diagnostics (admin only)", "admin"),
]


def bot_command_markup():
    """Payload for Bot API setMyCommands."""
    return [{"command": command, "description": description}
            for command, description, _action in BOT_COMMANDS]


def command_action(name):
    """Action string for a command name, or None if not a bot command."""
    for command, _description, action in BOT_COMMANDS:
        if command == name:
            return action
    return None

_INTENT_PROMPT = (
    "You are the intent parser of an eBook assistant. "
    "Classify the USER message into ONE intent:\n"
    "search - user wants to find eBooks (with a book topic)\n"
    "home - user wants the main menu / to start over\n"
    "cancel - user wants to stop the current action\n"
    "help - user asks how the assistant works\n"
    "chat - anything else (greeting, small talk, question not about books)\n"
    "For intent=search extract the BOOK TOPIC (nouns that describe the book "
    "content; drop filler words like 'find me a', 'search', 'ebook'). "
    "topic must be null unless intent=search.\n"
    'Reply ONLY JSON: {"intent": "...", "topic": "..." or null}\n'
    "USER: "
)


def _parse_intent(payload):
    if not isinstance(payload, dict):
        return None
    intent = payload.get("intent")
    topic = payload.get("topic")
    if intent not in ("search", "home", "cancel", "help", "chat"):
        return None
    if intent == "search" and not (isinstance(topic, str) and topic.strip()):
        return None  # a search intent without a topic is unusable
    return {"intent": intent,
            "topic": str(topic)[:200] if isinstance(topic, str) and topic.strip() else None}


def ask_intent(text, *, client=requests, base_url=None, api_key=None,
               model=None, timeout=20):
    """Classify a user message. Returns a parsed intent dict, or None when the
    LLM is unavailable / malformed (caller falls back to raw-topic search)."""
    base_url = base_url if base_url is not None else os.getenv("MINDA_BASE_URL")
    api_key = api_key if api_key is not None else os.getenv("MINDA_API_KEY")
    model = model if model is not None else os.getenv("MINDA_MODEL", "llm_model_fp8")
    if not base_url or not api_key or not text or not text.strip():
        return None
    try:
        response = client.post(
            base_url.rstrip("/") + "/chat/completions",
            headers={"Authorization": "Bearer " + api_key,
                     "Content-Type": "application/json"},
            json={"model": model, "max_tokens": 60,
                  "chat_template_kwargs": {"enable_thinking": False},
                  "messages": [{"role": "user",
                                "content": _INTENT_PROMPT + text[:300]}]},
            timeout=timeout)
        response.raise_for_status()
        raw = response.json()["choices"][0]["message"]["content"].strip()
        # tolerate a ```json fence
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.S)
        return _parse_intent(json.loads(raw))
    except Exception:
        # best-effort intent: any failure falls back to raw-topic search
        return None


def home_menu():
    rows = []
    rows.append([{"text": "✨ Find ALL (ebooks + apps)",
                  "callback_data": "fa:menu"}])
    left, right = [], []
    for index, (key, label, _topic) in enumerate(CATEGORIES):
        (left if index % 2 == 0 else right).append(
            {"text": label, "callback_data": "ui:cat:" + key})
        if len(left) == len(right):
            rows.append(left + right)
            left, right = [], []
    if left or right:
        rows.append(left + right)
    rows.append([{"text": "🏷️ MQL5 EAs/Indicators", "callback_data": "mql5:menu"}])
    rows.append([{"text": "🛠️ Automation Tools", "callback_data": "auto:menu"}])
    rows.append([
        {"text": "📣 AI Marketing", "callback_data": "fa:run:marketing"},
        {"text": "🪞 Web & App Cloning", "callback_data": "fa:run:cloning"}])
    rows.append([
        {"text": "🕵️ Hacking & Pen-Test", "callback_data": "fa:run:hacking"},
        {"text": "🔬 Reverse Engineering", "callback_data": "fa:run:reverse"}])
    rows.append([
        {"text": "📱 Termux (menu)", "callback_data": "termux:menu"},
        {"text": "🔎 Telegram User Check", "callback_data": "fa:run:tginfo"}])
    rows.append([
        {"text": "🕸️ Download Site (Scam)", "callback_data": "fa:run:webscam"},
        {"text": "🎓 Learning & School", "callback_data": "fa:run:learn"}])
    rows.append([
        {"text": "💱 Forex (info+tools+books)", "callback_data": "fa:run:forex"}])
    rows.append([{"text": "🪄 Prompt Forge (any AI)", "callback_data": "pf:menu"}])
    rows.append([{"text": "🧠 Agent (level & learning)", "callback_data": "ui:agent"}])
    rows.append([{"text": "❓ How to use", "callback_data": "ui:help"}])
    rows.append([{"text": "❌ Cancel", "callback_data": "ui:cancel"}])
    return {"text": HOME_TEXT, "reply_markup": {"inline_keyboard": rows}}


def find_menu():
    """Find ALL entry: a curated AI-agent / web-automation sub-topic grid plus
    a free-form prompt. Pressing a sub-topic runs the combined ebook+app
    search for that studied area."""
    from find_all import AI_TOPICS
    text = (
        "✨ Find ALL — ebooks + apps for one topic\n\n"
        "Pick a studied AI-agent / web-automation area, or tap "
        "“✍️ Ask for any topic” and type what you want. I gather open "
        "ebooks AND the best apps / source code together."
    )
    rows = [[{"text": "✍️ Ask for any topic", "callback_data": "fa:run"}]]
    for key, label, _gh, _bt, _info in AI_TOPICS:
        if key == "termux":  # has its own menu (termux:menu) now
            continue
        rows.append([{"text": label[:60], "callback_data": "fa:run:" + key}])
    rows.append([{"text": "🏠 Home", "callback_data": "ui:home"}])
    return {"text": text, "reply_markup": {"inline_keyboard": rows}}


def mql5_menu():
    from mql5_scout import MQL5_LISTINGS, MQL5_TEXT
    rows = [[{"text": label, "callback_data": "mql5:" + key}]
            for key, label, _market, _kind in MQL5_LISTINGS]
    rows.append([{"text": "🏠 Home", "callback_data": "ui:home"}])
    return {"text": MQL5_TEXT, "reply_markup": {"inline_keyboard": rows}}


def auto_menu():
    from auto_scout import AUTO_TOOLS, AUTO_TEXT
    rows = [[{"text": "🔥 Trending on GitHub (right now)", "callback_data": "auto:trend"}]]
    rows.append([{"text": "🕵️ Hacking & Pen-Test (info + tools)", "callback_data": "fa:run:hacking"}])
    rows.append([{"text": "📱 Termux (menu: install + automation)", "callback_data": "termux:menu"}])
    for key, label, _repo in AUTO_TOOLS:
        rows.append([{"text": label[:60], "callback_data": "auto:tool:" + key}])
    rows.append([{"text": "🏠 Home", "callback_data": "ui:home"}])
    return {"text": AUTO_TEXT, "reply_markup": {"inline_keyboard": rows}}


TERMUX_MENU_TEXT = (
    "📱 Termux — turn your Android phone into a dev + automation box\n\n"
    "Install Termux from F-Droid (the Play Store build is outdated), run "
    "`termux-setup-storage`, and set the battery to Unrestricted so "
    "scripts don't get killed. Every chat-automation bot you'll ever run "
    "(DANA-Kaget claim, CapCut events, earning games, uiautomator2, "
    "scrcpy, Appium) runs from here.\n\n"
    "Pick what you want:"
)


def termux_menu():
    """Dedicated Termux menu: install basics + related studied areas."""
    rows = [
        [{"text": "💬 Chat & UI Automation (tools)", "callback_data": "fa:run:termux"}],
        [{"text": "🔬 Reverse Engineering apk (tools)", "callback_data": "fa:run:reverse"}],
        [{"text": "🪞 Web & App Cloning (tools)", "callback_data": "fa:run:cloning"}],
        [{"text": "🕵️ Hacking & Pen-Test (tools)", "callback_data": "fa:run:hacking"}],
        [{"text": "⚙️ pkg: install python/node/git/jdk", "callback_data": "termux:pkg"}],
        [{"text": "📖 Termux + chat-automation books", "callback_data": "termux:books"}],
        [{"text": "🔁 Back to Find ALL", "callback_data": "fa:menu"}],
        [{"text": "🏠 Home", "callback_data": "ui:home"}],
    ]
    return {"text": TERMUX_MENU_TEXT, "reply_markup": {"inline_keyboard": rows}}


def category_topic(key):
    for item in CATEGORIES:
        if item[0] == key:
            return item[2]
    return None


def delivery_keyboard():
    return {"inline_keyboard": [
        [{"text": "📥 Send file here", "callback_data": "dl:f"}],
        [{"text": "🔗 Link only", "callback_data": "dl:l"}],
        [{"text": "🏠 Home", "callback_data": "ui:home"}],
    ]}


def delivery_nav_keyboard():
    """Shown after a file/link delivery: go back to the same results list
    or start a fresh search."""
    return {"inline_keyboard": [
        [{"text": "🔙 Back to results", "callback_data": "dlb:back"}],
        [{"text": "🔎 Search more", "callback_data": "dlb:more"}],
    ]}


def _chat_reply(intent_result, raw_text):
    if intent_result and intent_result["intent"] == "chat":
        return ("I'm msasoup — I find open-licensed eBooks. Tell me a topic "
                "(e.g. \"quantum computing\") or tap a category above. "
                "Use ❓ How to use for details.")
    return None


def deliver_file(token, chat_id, book, *, session=requests):
    """Download the book's file and send it as a document. Returns (ext, url).

    Reuses agent.download (safe_url, PDF/EPUB signature, 20 MB cap) and
    agent.send (sendDocument 200+ok check). Raises on any failure."""
    url = book["source_url"]
    ext, data = download(session, url)
    name = "book." + ext
    caption = str(book.get("title", "Open eBook"))[:800] + "\n" + url
    send(session, token, chat_id, name, data, caption)
    return ext, url
