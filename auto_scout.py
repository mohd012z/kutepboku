"""Automation tool scout: trending + curated GitHub repos for hacking and
Android automation, delivered as source zip files to Telegram.

"Viral" signal: GitHub's own trending page (github.com/trending, no auth) is
the curation that defines what's viral right now; per-topic curated lists are
stable essentials (nuclei, sqlmap, nmap, uiautomator2, scrcpy, appium, ...).

Delivery: https://github.com/<owner>/<repo>/archive/refs/heads/<branch>.zip
validated as a PK zip, 20 MB bot-file cap. Anything larger (e.g. metasploit
framework ~89 MB) is link-only — Telegram bots cannot send >20 MB.
"""
import json
import re
from html import unescape
import time

import requests

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
MAX_BYTES = 20 * 1024 * 1024
TRENDING_URL = "https://github.com/trending?since=daily"
TRENDING_NOISE = ("sponsors", "trending", "topics", "features", "orgs",
                  "users", "about", "login", "signup")
REPO_TILE = re.compile(
    r'<h2[^>]*>.*?<a[^>]+href="/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)"', re.S)

# (key, label, topic). Topic is sent to verified_search (IA + CC gate + Minda).
AUTO_CATEGORIES = [
    ("hack", "🕵️ Hacking Automation", "hacking penetration testing automation"),
    ("android", "🤖 Android Automation", "android automation"),
]

# (key, label, owner/repo). Branch is resolved live from the GitHub API.
AUTO_TOOLS = [
    ("nuclei", "Nuclei — vulnerability scanner", "projectdiscovery/nuclei"),
    ("httpx", "HTTPX — HTTP toolkit", "projectdiscovery/httpx"),
    ("subfinder", "Subfinder — subdomain finder", "projectdiscovery/subfinder"),
    ("katana", "Katana — web crawling/spidering", "projectdiscovery/katana"),
    ("sqlmap", "SQLMap — SQL injection testing", "sqlmapproject/sqlmap"),
    ("ffuf", "FFUF — fast web fuzzer", "ffuf/ffuf"),
    ("nmap", "Nmap — network scanner", "nmap/nmap"),
    ("metasploit", "Metasploit framework", "rapid7/metasploit-framework"),
    ("uia2", "uiautomator2 — Android UI control", "openatx/uiautomator2"),
    ("atx", "ATX agent (on-device)", "openatx/atx-agent"),
    ("scrcpy", "Scrcpy — mirror/cast Android", "Genymobile/scrcpy"),
    ("appium", "Appium — mobile automation", "appium/appium"),
]

AUTO_TEXT = (
    "🛠️ Automation tools — hacking & Android\n"
    "🔥 Trending: GitHub's viral repos right now (searchable by topic).\n"
    "📦 Curated: classic automation tools — tap to get the source zip "
    "(link-only if it exceeds Telegram's 20 MB bot limit)."
)

_TOOL_LOOKUP = {key: (label, repo) for key, label, repo in AUTO_TOOLS}
_CAT_LOOKUP = {key: (label, topic) for key, label, topic in AUTO_CATEGORIES}


def trending_repos(limit=10, *, client=requests, timeout=25):
    """Top repos from GitHub's daily trending page. Returns
    [{id, title, url}] — raises on network/HTML failure."""
    response = client.get(TRENDING_URL, headers={"User-Agent": USER_AGENT},
                          timeout=(5, timeout))
    response.raise_for_status()
    seen, out = set(), []
    for match in REPO_TILE.finditer(response.text):
        full = match.group(1)
        if full.count("/") != 1 or full in seen:
            continue
        if full.split("/", 1)[0].lower() in TRENDING_NOISE:
            continue
        seen.add(full)
        out.append({"id": full, "title": full,
                    "url": "https://github.com/" + full})
        if len(out) >= limit:
            break
    if not out:
        raise ValueError("GitHub trending returned no repos (layout change?)")
    return out


def _default_branch(full, *, client=requests):
    response = client.get("https://api.github.com/repos/" + full,
                          headers={"User-Agent": USER_AGENT}, timeout=(5, 25))
    response.raise_for_status()
    return response.json().get("default_branch")


def download_zip(full, branch, *, session=requests, max_bytes=MAX_BYTES):
    """Fetch the repo source zip. Returns (data, url). Raises ValueError on
    bad signature/size — the caller falls back to link-only."""
    url = "https://github.com/" + full + "/archive/refs/heads/" + branch + ".zip"
    response = session.get(url, headers={"User-Agent": USER_AGENT},
                           stream=True, timeout=(10, 120))
    response.raise_for_status()
    chunks = bytearray()
    for chunk in response.iter_content(65536):
        chunks.extend(chunk)
        if len(chunks) > max_bytes:
            raise ValueError("Repo exceeds the 20 MB bot-file limit — link only")
    response.close()
    data = bytes(chunks)
    if len(data) < 512 or not data.startswith(b"PK\x03\x04"):
        raise ValueError("Not a valid repo zip")
    return data, url


def deliver_zip(token, chat_id, item, *, session=requests):
    """Download + sendDocument. Returns (size, url). Raises on any failure
    (router falls back to the repo link)."""
    full = str(item.get("id", ""))
    branch = str(item.get("branch", "main"))
    if full.count("/") != 1:
        raise ValueError("Invalid repo id")
    data, url = download_zip(full, branch, session=session)
    from agent import send
    safe_name = full.split("/", 1)[1] + "-" + branch + ".zip"
    send(session, token, chat_id, safe_name, data,
         "📦 " + str(item.get("title", full))[:300] + "\n" + item["url"]
         + "\n(source zip — " + str(round(len(data) / 1024)) + " KB)")
    return len(data), url
