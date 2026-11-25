"""EX4-to-MQ4 decompiler channel scout (t.me/ex4tomq4decompilercom).

Source study (2026-11-25): the channel is a daily "decompiled EA" feed from the
ex4tomq4decompiler.com service (MT4 EX4 -> MQ4). Each EA ships as TWO posts:
a description post (image + full description, odd id) immediately followed by a
file post (the ``.ex4`` document + size, even id). The companion site
``/free-mt4-robots`` holds the full catalogue (JSON-LD ItemList + product
cards) mapping every EA name to its t.me post link.

Delivery model (honest): the ``.ex4`` bytes are pushed to the channel over
Telegram's ``tg://`` document protocol — there is no public CDN/HTTP file URL
and the msasoup bot is NOT a member of the channel (getChat -> 400), so the bot
cannot pull the raw file. A tap therefore sends a rich detail card (name,
type, file name + size when recently posted, full description, the decompiler
method study) plus a one-tap "open in Telegram" deep link to the exact file
post. That is the actual download path for a Telegram user.
"""
import json
import re
import time
from html import unescape

import requests

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
CHANNEL = "ex4tomq4decompilercom"
TG_BASE = "https://t.me/" + CHANNEL
S = "https://t.me/s/" + CHANNEL
SITE = "https://ex4tomq4decompiler.com/free-mt4-robots"

PER_PAGE = 3
MAX_DESC = 320
_TAG = re.compile(r"<[^>]+>")
_SPLIT = re.compile(r'data-post="' + re.escape(CHANNEL) + r'/(\d+)"')

_desc_cache = {}  # post_no -> (text, fetched_at); recent items only
_CACHE_TTL = 900


def _strip(text):
    return unescape(_TAG.sub("", text or "")).strip()


# --- t.me channel preview (t.me/s) -------------------------------------------

def parse_channel_posts(html):
    """Parse the public channel preview into a {post_no: info} map.

    Document posts yield {filename, size, post}; each doc's paired
    description post (post-1) is folded in as {desc}. The preview DOM is
    ordered oldest->newest, so a desc post can precede its doc — a two-pass
    fold handles either order. A pinned post yields neither.
    """
    parts = _SPLIT.split(html or "")
    blocks = []  # (post, filename|None, size, text)
    for i in range(1, len(parts) - 1, 2):
        try:
            post = int(parts[i])
        except ValueError:
            continue
        chunk = parts[i + 1]
        fn = re.search(
            r'tgme_widget_message_document_title[^>]*>([^<]+)</div>', chunk)
        sz = re.search(
            r'tgme_widget_message_document_extra[^>]*>([^<]+)</div>', chunk)
        text = ""
        for t in re.findall(
                r'class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>',
                chunk, re.S):
            cleaned = _strip(t)
            if len(cleaned) > len(text):
                text = cleaned
        blocks.append((post,
                       unescape(fn.group(1)).strip() if fn else None,
                       unescape(sz.group(1)).strip() if sz else "",
                       text))
    texts_by_post = {p: t for p, _f, _s, t in blocks}
    posts = {}
    for post, filename, size, _text in blocks:
        if filename:
            posts[post] = {"filename": filename, "size": size, "post": post}
    for post, filename, _size, text in blocks:
        if filename:
            desc = texts_by_post.get(post - 1, "")
            if desc:
                posts[post]["desc"] = desc
    return posts


def _fetch(url, client, *, timeout=25, retries=3):
    """GET with a small retry for t.me/CDN flakiness. Raises on final failure."""
    last = None
    for attempt in range(retries):
        try:
            resp = client.get(url, headers={"User-Agent": USER_AGENT},
                              timeout=(5, timeout), allow_redirects=True)
            resp.raise_for_status()
            return resp.text
        except Exception as err:
            last = err
            if attempt < retries - 1:
                time.sleep(1.5 * (attempt + 1))
    if last is None:
        raise ValueError("fetch failed with no error")
    raise last


def scrape_channel(client=requests):
    """Recent channel posts -> {post_no: info}. Raises on network/HTML failure."""
    posts = parse_channel_posts(_fetch(S, client))
    if not posts:
        raise ValueError("Channel preview returned no posts (layout change?)")
    return posts


# --- ex4tomq4decompiler.com catalogue ----------------------------------------

_CARD = re.compile(
    r'<article class="product-card"[^>]*>.*?'
    r'<span class="product-type">([^<]+)</span>.*?'
    r'<h2 class="product-title"[^>]*>([^<]+)</h2>.*?'
    r'<p class="product-seo-description">([^<]+)</p>.*?'
    r'href="(https://t\.me/' + re.escape(CHANNEL) + r'/\d+)"', re.S)


def parse_site_catalog(html):
    """Catalogue EAs from the free-mt4-robots page.

    Returns (names_in_catalogue_order, {norm_name: card}) where a card is
    {name, type, file_url, post, desc}.
    """
    m = re.search(r'<script type="application/ld\+json">(.*?)</script>',
                  html or "", re.S)
    names = []
    if m:
        try:
            for it in json.loads(m.group(1)).get("itemListElement", []):
                n = unescape(it.get("name", "")).strip()
                if n:
                    names.append(n)
        except ValueError:
            names = []
    cards = {}
    for ptype, title, desc, url in _CARD.findall(html or ""):
        name = unescape(title).replace(" Decompiled", "").replace("\U0001F4B0", "").strip()
        cards[_norm(name)] = {"name": name,
                              "type": unescape(ptype).strip(),
                              "file_url": url,
                              "post": url.rsplit("/", 1)[-1],
                              "desc": _strip(desc)}
    return names, cards


def scrape_catalog(client=requests):
    """Site catalogue -> (names, cards). Raises on network/HTML failure."""
    return parse_site_catalog(_fetch(SITE, client))


# --- merge -------------------------------------------------------------------

def _norm(name):
    return re.sub(r"\s+", " ",
                  (name or "").lower().replace(" decompiled", "")
                  .replace("\U0001F4B0", "")).strip()


def _item(name, card, recent):
    recent = recent or {}
    file_url = card.get("file_url") or (
        TG_BASE + "/" + str(recent["post"]) if recent else "")
    desc = card.get("desc") or recent.get("desc") or ""
    return {
        "name": name,
        "type": card.get("type", "MT4 EXPERT ADVISOR"),
        "recent": bool(recent),
        "filename": recent.get("filename", ""),
        "size": recent.get("size", ""),
        "desc": desc,
        "url": file_url,
        "post": str(recent.get("post") or card.get("post") or ""),
    }


def _merge(names, cards, posts):
    """Catalogue order, recently-posted EAs floated to the top.

    Every catalogue EA is returned (even without a live file post); any live
    document posts whose name is not in the catalogue are appended at the end.
    """
    recent_by_norm = {_norm(info["filename"].rsplit(".", 1)[0]): info
                      for info in posts.values() if info.get("filename")}
    items, seen = [], set()
    for name in names:
        key = _norm(name)
        if key in seen:
            continue
        seen.add(key)
        items.append(_item(name, cards.get(key, {}),
                           recent_by_norm.get(key)))
    # live posts not represented in the catalogue
    for key, info in recent_by_norm.items():
        if key in seen:
            continue
        seen.add(key)
        name = info["filename"].rsplit(".", 1)[0]
        items.append(_item(name, {}, info))
    items.sort(key=lambda x: (0 if x["recent"] else 1))
    return items


def ex4_fetch_listing(mode, client=requests):
    """mode 'recent' -> latest channel posts (filename + size guaranteed);
    mode 'full' -> the complete site catalogue merged with recent posts.
    Returns a list of items (see _item). Raises when the primary source for
    the mode is unavailable (recent=channel, full=catalogue). The *other*
    source degrading is non-fatal: full works with an empty recent set and
    recent works with only the live doc posts."""
    posts = {}
    if mode == "recent":
        posts = scrape_channel(client)
        docs = [i for i in posts.values() if i.get("filename")]
        if not docs:
            raise ValueError("Channel returned no .ex4 posts (layout change?)")
        docs.sort(key=lambda i: i["post"], reverse=True)
        return [_item(i["filename"].rsplit(".", 1)[0], {}, i) for i in docs]
    try:
        posts = scrape_channel(client)
    except Exception:
        posts = {}  # recent enrichment is optional for the catalogue
    names, cards = scrape_catalog(client)
    if not names and not cards:
        raise ValueError("Catalogue returned no items (layout change?)")
    items = _merge(names, cards, posts)
    if not items:
        raise ValueError("Catalogue returned no items (layout change?)")
    return items


# --- descriptions (detail view) ----------------------------------------------

def _fetch_desc(post_no, client=requests):
    """Long description from the paired post-1 (image + text)."""
    now = time.time()
    hit = _desc_cache.get(post_no)
    if hit and now - hit[1] < _CACHE_TTL:
        return hit[0]
    html = _fetch(S + str(post_no), client)
    parts = _SPLIT.split(html)
    text = ""
    for i in range(1, len(parts) - 1, 2):
        if parts[i] == str(post_no):
            for t in re.findall(
                    r'class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>',
                    parts[i + 1], re.S):
                cleaned = _strip(t)
                if len(cleaned) > len(text):
                    text = cleaned
            break
    _desc_cache[post_no] = (text, now)
    return text


def ex4_item_detail(item, client=requests):
    """(text, keyboard) for one EA. Downloads the long description from the
    paired post-1 on first tap (15-min cache); falls back to the catalogue
    blurb when the fetch fails or there is no post to read."""
    lines = ["🧬 " + str(item.get("name", "EA"))[:90]]
    if item.get("recent"):
        lines.append("✅ decompiled + just posted to the channel")
    lines.append("📐 " + str(item.get("type", "MT4 EXPERT ADVISOR")))
    if item.get("filename"):
        lines.append("📄 " + str(item["filename"])
                     + ("  ·  " + str(item["size"]) if item.get("size") else ""))
    desc = str(item.get("desc", "")).strip()
    post = int(item.get("post") or 0)
    if item.get("recent") and post > 1 and len(desc) <= MAX_DESC:
        try:
            got = _fetch_desc(post - 1, client=client)
            if len(got) > len(desc):
                desc = got
        except Exception:
            pass  # catalogue blurb (or nothing) is the fallback
    if desc:
        d = re.sub(r"\s+", " ", desc).strip()
        if len(d) > MAX_DESC:
            d = d[:MAX_DESC].rstrip() + "…"
        lines.append("\n📝 " + d)
    if item.get("url"):
        lines.append(
            "\n📥 The .ex4 is a Telegram channel document (tg:// protocol — "
            "no public CDN). Open the post below to save it, then drop it in "
            "MQL4/Experts of MT4 and recompile the decompiled .mq4 to read "
            "the source.")
    keyboard = {"inline_keyboard": [
        [{"text": "📥 Get it on Telegram", "url": str(item["url"])}],
        [{"text": "⬅️ Back to list", "callback_data": "ex4:back"},
         {"text": "🏠 Home", "callback_data": "ui:home"}]]}
    return "\n".join(lines), keyboard


# --- paging / keyboard --------------------------------------------------------

def _pages(count):
    return max(1, (count + PER_PAGE - 1) // PER_PAGE)


def ex4_listing_message(items, page, mode):
    start = page * PER_PAGE
    titles = "\n".join(
        str(start + i + 1) + ". " + str(it["name"])[:56]
        + ("  ⚡" + str(it["size"]) if it.get("size") else "")
        + ("  (recent)" if it.get("recent") else "")
        for i, it in enumerate(items[start:start + PER_PAGE]))
    return {
        "text": ("📦 EX4 decompiler — "
                 + ("recent decompiled EAs" if mode == "recent" else
                    "full catalogue")
                 + " (page " + str(page + 1) + "/" + str(_pages(len(items)))
                 + ")\n\n" + titles
                 + "\n\nTap a title for details + the file post:")
                if items else
                "📦 EX4 decompiler — no items found right now.",
        "reply_markup": _keyboard(items, page, mode),
    }


def _keyboard(items, page, mode):
    pages = _pages(len(items))
    rows = []
    for i, it in enumerate(items[page * PER_PAGE:page * PER_PAGE + PER_PAGE]):
        rows.append([{"text": str(it["name"])[:48],
                      "callback_data": "ex4i:" + str(page * PER_PAGE + i)}])
    nav = []
    if page > 0:
        nav.append({"text": "⬅️ Prev", "callback_data": "ex4p:" + str(page - 1)})
    if page + 1 < pages:
        nav.append({"text": "Next ➡️", "callback_data": "ex4p:" + str(page + 1)})
    nav.append({"text": "🏠 Home", "callback_data": "ui:home"})
    rows.append(nav)
    return {"inline_keyboard": rows}


def ex4_item_by_index(items, index_str):
    if not re.fullmatch(r"\d+", str(index_str)):
        raise ValueError("bad item index")
    index = int(index_str)
    if index < 0 or index >= len(items):
        raise ValueError("item index out of range")
    return items[index]


# --- menu ----------------------------------------------------------------------

def ex4_menu():
    rows = [
        [{"text": "🆕 Recent decompiled EAs (10 latest)",
          "callback_data": "ex4:recent"}],
        [{"text": "📚 Full catalogue (83 EAs)", "callback_data": "ex4:full"}],
        [{"text": "🧪 How the decompiler works (method study)",
          "callback_data": "ex4:study"}],
        [{"text": "🏠 Home", "callback_data": "ui:home"}],
    ]
    return {"text": EX4_TEXT, "reply_markup": {"inline_keyboard": rows}}


def ex4_study():
    return {"text": EX4_STUDY_TEXT,
            "reply_markup": {"inline_keyboard": [
                [{"text": "🏠 Home", "callback_data": "ui:home"}]]}}


EX4_TEXT = (
    "🧬 EX4 → MQ4 decompiler channel (t.me/ex4tomq4decompilercom)\n"
    "Daily decompiled MT4 Expert Advisors from ex4tomq4decompiler.com. Each "
    "EA ships as a .ex4 file + a decompiled .mq4. Tap an EA for the full "
    "details + a one-tap link to the Telegram file post (that is how you save "
    "the .ex4 — the bytes go through Telegram's document protocol, no public "
    "CDN). Browse recent drops or the full 83-EA catalogue."
)

EX4_STUDY_TEXT = (
    "🧪 Method study — how EX4 → MQ4 decompilation works\n\n"
    "• What a .ex4 is: MT4 Expert Advisors/indicators are compiled to .ex4 "
    "(bytecode + resources). The channel's service (ex4tomq4decompiler.com) "
    "disassembles that back to readable .mq4 — the 'EX4 TO MQ4 Decompiler'.\n\n"
    "• The decompiler family: MT4 .ex4 decompilation (the channel's niche) is "
    "a paid niche — tools like Ex4 to Mq4 (builds 224/225/226) run ~$12–800. "
    "MT5's .ex5 is significantly harder (different bytecode), which is why "
    "this channel focuses on MT4.\n\n"
    "• Quality caveat: decompiled .mq4 usually has mangled local names and "
    "sometimes inlined/obfuscated logic; recompile it in MetaEditor to read "
    "and tweak it. '90% win rate' style marketing claims in the posts are the "
    "seller's, not a verified stat.\n\n"
    "• Why the file needs Telegram: the .ex4 is delivered as a Telegram "
    "channel document (tg:// file protocol). There is no public HTTP/CDN "
    "link and the msasoup bot is not a channel member, so the bot hands you "
    "the deep link + full details rather than the raw bytes.\n\n"
    "• The catalogue: the companion site /free-mt4-robots lists all 83 EAs "
    "(JSON-LD + product cards) each mapped to its channel post — that is the "
    "source for 'full catalogue'.\n\n"
    "• License note: these are decompiled copies of third-party EAs, free via "
    "the channel for personal research — not open-source; respect the "
    "original author when redistributing."
)
