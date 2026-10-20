"""ai_msa conversational assistant layer: intent understanding, category menu,
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
    "🤖 ai_msa — open-license eBook agent\n\n"
    "Pick a category or just tell me what you need, e.g. "
    "\"find a quantum computing book\". I search Internet Archive, "
    "keep only open-licensed (CC) books, and can send the file straight to you."
)

HELP_TEXT = (
    "How I work:\n"
    "• Tap a category button — I search open-licensed books for it.\n"
    "• Or type any request — I understand plain language.\n"
    "• Pick a book from the list, then choose Send file (I download and "
    "send it) or Link (I send the archive.org link).\n"
    "• Commands: /start (menu), /cancel, /status (admin), /backup (admin)."
)

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
    left, right = [], []
    for index, (key, label, _topic) in enumerate(CATEGORIES):
        (left if index % 2 == 0 else right).append(
            {"text": label, "callback_data": "ui:cat:" + key})
        if len(left) == len(right):
            rows.append(left + right)
            left, right = [], []
    if left or right:
        rows.append(left + right)
    rows.append([{"text": "❓ How to use", "callback_data": "ui:help"}])
    rows.append([{"text": "❌ Cancel", "callback_data": "ui:cancel"}])
    return {"text": HOME_TEXT, "reply_markup": {"inline_keyboard": rows}}


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


def _chat_reply(intent_result, raw_text):
    if intent_result and intent_result["intent"] == "chat":
        return ("I'm ai_msa — I find open-licensed eBooks. Tell me a topic "
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
