"""Find ALL: combined open-ebook + app/repo discovery for one topic.

Ebooks reuse the key-free verified search (IA + Gutenberg + Open Library) —
the caller passes the already-searched ebook list in. Apps come from
GitHub's search API (key-free, ~10 req/min unauthenticated), sorted by
stars. For the studied "AI agent integration + web automation" sub-topics a
hand-verified top-repo list is bundled, so that knowledge is available even
when the live search is rate-limited (fail-open: curated always, live augments).
"""
import hashlib

import requests

GITHUB_SEARCH = "https://api.github.com/search/repositories"
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
APP_LIMIT = 8

# Studied sub-topics of "AI agent integration + web automation".
# (key, label, github_query, ebook_topic, info)
AI_TOPICS = [
    ("agents", "🤖 AI Agents & Frameworks", "ai agent",
     "ai agent frameworks",
     "Agent frameworks orchestrate LLMs + tools into task-doing loops."),
    ("webauto", "🕸️ Web Automation", "web automation",
     "web automation scraping",
     "Automate browsers (Playwright/Puppeteer/Selenium) to act on the web."),
    ("browser", "🌐 Browser Automation", "browser automation",
     "browser automation playwright",
     "Drive a real headless browser for scraping, testing, agent actions."),
    ("rag", "📚 RAG & LLM Pipelines", "RAG LLM",
     "retrieval augmented generation LLM",
     "Retrieval-augmented generation: ground LLM answers in your data."),
    ("gui", "🖥️ Computer-Use / GUI Agents", "computer use agent",
     "computer use AI agent GUI",
     "Agents that click/type through a computer UI like a human."),
    ("orchest", "🧩 Workflow Orchestration", "AI workflow orchestration",
     "workflow orchestration",
     "Chain steps/tools/agents into reliable pipelines (Airflow, Haystack)."),
    ("marketing", "📣 AI Advertising & Marketing", "ai marketing",
     "ai marketing advertising",
     "AI agents for ad creative, copy, CRO, lead-gen and campaign data."),
    ("cloning", "🪞 Web & App Cloning", "website clone",
     "website cloning web scraping",
     "How it works: mirror the site (HTML/CSS/JS/assets) -> rebuild the "
     "structure -> compare to the original. AI-agent tools do this in one "
     "command (static or React); scrapers (Playwright/Scrapling) feed them. "
     "Always check the site's ToS before reusing assets."),
]

# Hand-verified top repos per AI sub-topic (study of GitHub search, 2026-10-20).
# Stars are approximate and only for display; they also order the curated list.
CURATED_AI_REPOS = {
    "agents": [
        ("firecrawl/firecrawl", "Web data for AI agents (crawl/scrape to markdown)", 193482),
        ("langchain-ai/langchain", "Agent engineering platform", 148154),
        ("msitarzewski/agency-agents", "Complete AI agency of expert roles", 162325),
        ("Shubhamsaboo/awesome-llm-apps", "100+ AI agents, skills and RAG apps", 142425),
        ("the-open-agent/openagent", "Personal AI assistant: LLM + RAG + agents", 5703),
    ],
    "webauto": [
        ("microsoft/playwright", "Web testing + automation for Chromium/Firefox/WebKit", 98173),
        ("puppeteer/puppeteer", "JS API to drive Chrome/Firefox", 95723),
        ("D4Vinci/Scrapling", "Adaptive web-scraping framework", 88877),
        ("JCodesMore/ai-website-cloner-template", "Clone any website with one command", 37056),
        ("apify/crawlee", "Web scraping + browser automation (Node.js)", 26201),
    ],
    "browser": [
        ("vercel-labs/agent-browser", "Browser-automation CLI for AI agents", 44335),
        ("lightpanda-io/browser", "Headless browser built for AI + automation", 36795),
        ("SeleniumHQ/selenium", "The classic browser-automation framework", 34564),
        ("Skyvern-AI/skyvern", "Automate browser workflows with AI", 23239),
    ],
    "rag": [
        ("langgenius/dify", "Agentic workflows + RAG pipelines + tool support", 159063),
        ("open-webui/open-webui", "Self-hosted AI interface (Ollama, OpenAI…)", 156300),
        ("infiniflow/ragflow", "Production-grade RAG engine", 92551),
        ("labring/FastGPT", "Knowledge-based LLM platform + workflows", 29880),
    ],
    "gui": [
        ("trycua/cua", "Computer-use 2.0: open drivers + cross-OS sandboxes", 30438),
        ("simular-ai/Agent-S", "Open agentic framework that uses a computer like a human", 12662),
        ("microsoft/fara", "Frontier computer-use agent models", 6221),
        ("Anil-matcha/open-dots", "Self-hosted AI agent workspace", 5902),
    ],
    "orchest": [
        ("apache/airflow", "Author + schedule data/AI pipelines as code", 47236),
        ("deepset-ai/haystack", "Open-source AI orchestration + RAG framework", 26794),
        ("Avaiga/taipy", "Turn data + AI algorithms into web apps", 19444),
    ],
    "marketing": [
        ("twentyhq/twenty", "Open alternative to Salesforce, built for AI", 58746),
        ("coreyhaines31/marketingskills", "Marketing skills for AI agents: CRO, copywriting, SEO", 55689),
        ("eracle/OpenOutreach", "Open-source AI agent for B2B lead generation", 3347),
        ("ParthJadhav/app-store-screenshots", "End-to-end AI app-store screenshot creation", 7476),
        ("YILS-LIN/short-video-factory", "AI short-video marketing + batch editing", 5824),
        ("yi1108/printfilm", "AI short-video marketing + short-drama platform", 5595),
        ("social-media-skills/skills", "106 social-media skills for AI agents", 176),
    ],
    "cloning": [
        ("JCodesMore/ai-website-cloner-template", "Clone any website with one command (AI coding agents)", 37059),
        ("firecrawl/open-lovable", "Clone + recreate any website as a modern React app in seconds", 28749),
        ("goclone-dev/goclone", "Website cloner using Go routines", 2286),
        ("Jane-xiaoer/claude-skill-web-clone", "Methodology for faithfully cloning any website (static/React)", 1065),
        ("boyang-hu/website-rebuild-skill", "Agent skill: mirror, line-by-line rebuild, auto-compare", 1539),
    ],
}

_TOPIC_LOOKUP = {key: (label, gh_query, book_topic, info)
                 for key, label, gh_query, book_topic, info in AI_TOPICS}


def _app(full, desc, stars):
    desc = (desc or "").strip().replace("\n", " ")
    title = full.split("/", 1)[1]
    shown = title if not desc else title + " — " + desc[:90]
    return {"id": full, "title": shown, "url": "https://github.com/" + full,
            "stars": int(stars or 0),
            "aid": hashlib.sha256(full.encode("utf-8")).hexdigest()[:16]}


def curated_apps(key):
    """Bundled top repos for an AI sub-topic (offline-available)."""
    repos = sorted(CURATED_AI_REPOS.get(key, ()), key=lambda r: -r[2])
    return [_app(full, desc, stars) for full, desc, stars in repos]


def search_repos(query, limit=APP_LIMIT, *, client=requests):
    """Live GitHub repo search, sorted by stars. Raises on network failure."""
    if not query or not query.strip():
        return []
    response = client.get(
        GITHUB_SEARCH,
        params={"q": query[:100], "sort": "stars", "order": "desc",
                "per_page": str(max(1, min(int(limit), 30)))},
        headers={"User-Agent": USER_AGENT,
                 "Accept": "application/vnd.github+json"},
        timeout=(5, 20))
    response.raise_for_status()
    items = response.json().get("items", [])
    out = []
    for it in items[:limit]:
        full = it.get("full_name")
        if not full or full.count("/") != 1:
            continue
        out.append(_app(full, it.get("description") or "",
                        it.get("stargazers_count", 0)))
    return out


def apps_for(key, query, *, client=requests):
    """Apps for a topic: curated (when the topic has a curated set) merged
    with live GitHub search. Live failure is non-fatal (curated remains)."""
    apps = curated_apps(key) if key else []
    seen = {a["id"] for a in apps}
    try:
        for app in search_repos(query, limit=APP_LIMIT, client=client):
            if app["id"] not in seen:
                seen.add(app["id"])
                apps.append(app)
            if len(apps) >= APP_LIMIT:
                break
    except requests.RequestException:
        pass
    return apps[:APP_LIMIT]


def find_all(topic, *, client=requests, ebooks=None, key=None):
    """One combined result: open ebooks + apps/repos for a topic. For a
    studied sub-topic (key) the 'info' (how-it-works) blurb is included."""
    gh_query = topic
    info = ""
    if key in _TOPIC_LOOKUP:
        gh_query = _TOPIC_LOOKUP[key][1]
        info = _TOPIC_LOOKUP[key][3]
    apps = apps_for(key, gh_query, client=client)
    return {"topic": str(topic)[:200], "ebooks": list(ebooks or []),
            "apps": apps, "info": info}


def find_all_message(result):
    n_books = len(result["ebooks"])
    n_apps = len(result["apps"])
    lines = ["🔎 Find ALL for “" + result["topic"] + "”",
             "",
             "📚 Open ebooks: " + str(n_books),
             "📱 Apps / source code: " + str(n_apps)]
    info = str(result.get("info") or "").strip()
    if info:
        lines.append("")
        lines.append("ℹ️ " + info)
    lines.append("")
    lines.append("Tap an ebook → Send file / Link. Tap an app → source zip "
                 "(link-only if >20 MB).")
    if n_books == 0:
        lines.append("· No open-licensed ebooks matched (rights gate).")
    if n_apps == 0:
        lines.append("· No apps matched (GitHub search).")
    return "\n".join(lines)


def find_all_keyboard(result, token):
    rows = []
    if result["ebooks"]:
        rows.append([{"text": "📚 Show all " + str(len(result["ebooks"]))
                      + " ebooks", "callback_data": "fae:" + token}])
    for i, app in enumerate(result["apps"][:5]):
        rows.append([{"text": "📱 " + str(app["title"])[:52],
                      "callback_data": "fap:" + token + ":" + str(i)}])
    rows.append([{"text": "🔎 Find another", "callback_data": "fa:run"},
                 {"text": "🏠 Home", "callback_data": "ui:home"}])
    return {"inline_keyboard": rows}
