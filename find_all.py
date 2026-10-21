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
    ("hacking", "🕵️ Hacking & Pen-Test", "hacking",
     "hacking penetration testing security",
     "Web pentest: recon (subfinder -> httpx -> katana crawl -> ffuf fuzz) "
     "-> vuln scan (nuclei, sqlmap SQLi) -> exploit (Metasploit). Network: "
     "nmap sweep. Mobile (apk) apps: jadx decompile -> frida/objection hook "
     "at runtime. All open-source; run only on hosts you're authorised."),
    ("reverse", "🔬 Reverse Engineering (apk)", "reverse engineering android apk",
     "reverse engineering decompiler",
     "Tear an apk/app down to see how it works: apktool/jadx unpack + "
     "decompile (smali/java), Ghidra disassembles native .so libs, "
     "frida/objection hook + explore at runtime, qbundler for React-Native. "
     "Recompile with apktool to test patched smali/dex."),
    ("termux", "📱 Termux & Chat Automation", "android ui automation",
     "android automation uiautomator",
     "Automate an Android phone from Termux: uiautomator2 taps/swipes by "
     "selector, Airtest matches by screenshot, scrcpy mirrors+controls, "
     "Appium drives iOS+Android, termux-api fires notifications. Full "
     "install steps are in the Termux menu (⚙️ pkg)."),
    ("termuxre", "🔬 Termux Reverse Engineering", "reverse engineering android apk",
     "reverse engineering android",
     "RE on the phone from Termux (verified against the live package "
     "index):\n"
     "• `pkg install radare2` → r2 CLI + rabin2/objdump2; `r2 -d` can even "
     "debug local processes.\n"
     "• `pkg install jadx apktool` → unpack + decompile APKs directly on "
     "the phone (GUI via the x11 repo + termux-x11).\n"
     "• Frida: `pkg install python` + `pip install frida-tools`, push "
     "frida-server (arm64) to /data/local/tmp, `chmod 755`, run it, then "
     "`frida -U`.\n"
     "• Ghidra: `pkg install openjdk-21 unzip`, download the Ghidra zip "
     "from GitHub, run `./ghidraRun` (Java app; needs X11 for the GUI).\n"
     "• `pkg install gdb strace` → low-level tracing. Tap a tool → zip."),
    ("tginfo", "🔎 Telegram Username Check", "telegram user info mtproto",
     "telegram bots chat",
     "Check a Telegram @username: (1) profile — open the @name; a real "
     "account/bot shows name, avatar, bio; bots have a verified ✓ and "
     "/start works. (2) id & join date — an MTProto client (Telethon, "
     "Pyrogram, MadelineProto) can fetch user_id, first/last seen and "
     "profile via api_id/api_hash. (3) history — t.me/NAME public preview "
     "shows channels' recent posts; check Telegram search + t.me/s/NAME. "
     "Scam signals: account age, reused photos, copy-paste bio, mass adds."),
    ("webscam", "🕸️ Download a Website (Scam Check)", "website mirror download",
     "website web",
     "Pull any site down to inspect it offline (scammer check): httrack "
     "mirrors the whole site (Linux/Termux/Android builds), the singleFile "
     "browser extension saves a page as one HTML, Wayback Machine archives "
     "it. Then look for red flags: whois/registrar + registration age "
     "(fresh domain = risk), SSL cert, real contact/phone/address, social "
     "proof, and 'pay via WhatsApp/Telegram first' or wallet-address "
     "payment = classic scam. Inspect the mirror offline so the site can't "
     "change what you're reviewing."),
    ("learn", "🎓 Learning & School Programs", "online learning lms spaced repetition",
     "learning education study",
     "Two paths: (1) LEARN A SKILL — follow a free structured curriculum "
     "(freeCodeCamp for coding, The Odin Project, exercism for mentored "
     "practice), lock it in with spaced repetition (Anki/AnkiDroid daily "
     "cards), keep a notes system (Obsidian/Joplin). (2) BUILD A SCHOOL "
     "PROGRAM — self-host a learning platform (LMS): Moodle is the most "
     "widely used open LMS, Open edX powers edX — both give courses, "
     "assignments, grading, certificates for a class/family/kids. Pair a "
     "curriculum + LMS + Anki and you have a complete school."),
    ("forex", "💱 Forex Trading (Info + Tools)", "forex trading bot backtest",
     "forex trading",
     "Forex = trading currency pairs (EUR/USD, GBP/USD, XAU/USD gold…). "
     "Workflow: pick a broker + platform (MetaTrader 4/5) -> learn the "
     "method (technical: RSI/MACD/moving averages + risk management: fixed "
     "% risk, stop-loss, position sizing) -> BACKTEST before live (backtrader, "
     "backtesting.py, Nautilus) -> automate with an EA (see /mql5 for "
     "trending Expert Advisors + indicators). Open data: Twelve Data, OANDA. "
     "Educational, not financial advice."),
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
    "hacking": [
        ("rapid7/metasploit-framework", "Metasploit: the standard penetration-testing framework", 39195),
        ("sqlmapproject/sqlmap", "Automatic SQL injection & database takeover", 38753),
        ("projectdiscovery/nuclei", "Fast, template-driven vulnerability scanner", 32168),
        ("projectdiscovery/katana", "Next-gen crawling & spidering framework", 17698),
        ("ffuf/ffuf", "Fast web fuzzer written in Go", 16922),
        ("projectdiscovery/subfinder", "Fast passive subdomain enumeration", 14630),
        ("nmap/nmap", "Nmap — the network mapper (port/service sweep)", 13836),
        ("projectdiscovery/httpx", "Fast multi-purpose HTTP toolkit (probe & fingerprint)", 10500),
    ],
    "reverse": [
        ("NationalSecurityAgency/ghidra", "Ghidra — software reverse-engineering suite (disassembler)", 92179),
        ("skylot/jadx", "DEX → Java decompiler for Android", 51133),
        ("iBotPeaches/apktool", "Reverse-engineer, decompile & recompile Android apk", 26386),
        ("frida/frida", "Frida — dynamic instrumentation / runtime hooking", 22397),
        ("appium/appium", "Cross-platform mobile automation (also drives RE'd apps)", 22114),
        ("sensepost/objection", "Runtime mobile exploration for iOS/Android (Frida-based)", 9453),
    ],
    "termux": [
        ("Genymobile/scrcpy", "Display & control an Android device over USB/Wi-Fi", 152663),
        ("airtestproject/airtest", "Image+touch UI automation for games & apps (by Tencent)", 9612),
        ("openatx/uiautomator2", "Android UI automation via Python (taps/swipes by selector)", 8433),
        ("appium/appium", "Cross-platform mobile automation (iOS + Android)", 22114),
        ("openatx/ATX-Agent", "HTTP daemon running on the Android device for automation", 802),
    ],
    "termuxre": [
        ("NationalSecurityAgency/ghidra", "Ghidra — SRE framework (run in Termux: pkg install openjdk-21)", 92373),
        ("skylot/jadx", "DEX → Java decompiler (Termux: pkg install jadx)", 51144),
        ("iBotPeaches/Apktool", "APK decompile + recompile (Termux: pkg install apktool)", 26435),
        ("radareorg/radare2", "radare2 — UNIX-like RE framework (Termux: pkg install radare2)", 25114),
        ("frida/frida", "Frida — runtime instrumentation (Termux: frida-server + pip frida-tools)", 22402),
        ("worawit/blutter", "blutter — Flutter/Dart AOT decompiler (reads libapp.so → pp.txt + decompiled Dart)", 2771),
        ("Kirlif/PPTool", "PPTool — find Dart object load addresses in libapp.so by pool-pointer offset", 17),
    ],
    "tginfo": [
        ("LonamiWebs/Telethon", "Python MTProto Telegram client — fetch user id, profile, history", 12067),
        ("pyrogram/pyrogram", "Elegant async Telegram MTProto framework (user/bot)", 4620),
        ("danog/MadelineProto", "Async PHP Telegram MTProto client (user_id, first/last seen)", 3540),
        ("gram-js/gramjs", "Node/Browser MTProto Telegram client", 1765),
        ("iggisv9t/tgcrawler", "Simple Telegram channel crawler (messages, members, files)", 19),
    ],
    "webscam": [
        ("ScrapeGraphAI/Scrapegraph-ai", "AI-powered Python scraper (content, metadata, screenshots)", 32044),
        ("D4Vinci/Scrapling", "Adaptive web-scraping framework (single request → structured data)", 88898),
        ("apify/crawlee", "Crawlee — web scraping + browser automation (Node.js)", 26202),
        ("xroche/httrack", "HTTrack Website Copier — mirror a whole site offline", 4795),
        ("zmh-program/next-whois", "Modern Whois lookup (domain age, registrar, owner)", 592),
        ("Moham3dRiahi/Th3inspector", "Th3Inspector — OSINT information gathering (people, domains, IPs)", 2673),
    ],
    "learn": [
        ("freeCodeCamp/freeCodeCamp", "freeCodeCamp — free coding curriculum + certificates", 457598),
        ("laurent22/joplin", "Joplin — privacy-focused note taking + sync (study notes)", 56820),
        ("ankitects/anki", "Anki — spaced-repetition flashcards (lock in any skill)", 32160),
        ("obsidianmd/obsidian-releases", "Obsidian — link your notes into a personal knowledge base", 22438),
        ("ankidroid/Anki-Android", "AnkiDroid — Anki flashcards on Android (daily drills)", 12066),
        ("openedx/openedx-platform", "Open edX — self-host a real LMS (courses, grading, certificates)", 8205),
        ("exercism/exercism", "Exercism — mentored coding practice in 60+ languages", 7594),
        ("moodle/moodle", "Moodle — the most widely used open-source LMS (build a school)", 7507),
        ("TheOdinProject/theodinproject", "The Odin Project — free full-stack web development path", 4662),
    ],
    "forex": [
        ("freqtrade/freqtrade", "Free open-source trading bot (data, backtest, live, web UI)", 55680),
        ("ccxt/ccxt", "Unified API for 100+ crypto/forex exchanges", 44491),
        ("nautechsystems/nautilus_trader", "Production-grade Rust-native trading engine (deterministic backtest/live)", 30395),
        ("mementum/backtrader", "Python backtesting library for trading strategies", 23529),
        ("kernc/backtesting.py", "Backtest trading strategies in Python (fast, clear results)", 9090),
        ("freqtrade/frequi", "Freqtrade web UI (strategy editor, backtest charts, live control)", 1097),
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
    lines.append("Tap an ebook → Send file / Link. Tap an app → its source "
                 "zip (link-only if >20 MB).")
    if n_books == 0:
        lines.append("· No open-licensed ebooks matched — I only return "
                     "Creative-Commons/public-domain books (rights gate), "
                     "so tool-focused topics like this one show 0 books "
                     "but the apps below are the real deliverable.")
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
