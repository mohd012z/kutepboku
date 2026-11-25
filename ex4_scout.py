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

# --- curated indicators (verified file posts, full-history scrape 2026-11-25) --
# The channel is a daily feed; only the ~20 latest posts are in the /s/ preview,
# so older indicator drops are pinned by post number. Every (name, post,
# filename, size) was verified against the full 2023-2026 scrape of the
# channel before being listed. Descriptions are mechanism writeups, not the
# sellers' marketing.
# (name, file_post, filename, size, mechanism_note)
INDICATORS = [
    ("Wolf Wave", 232, "Wolf Wave MT4.mq4", "16.7 KB",
     "ZigZag-based wedge pattern (down-tilt to buy, up-tilt to sell). The "
     "only file in this channel shipped as decompiled .mq4 source rather "
     "than just the compiled .ex4 — open it straight in MetaEditor."),
    ("TTM Scalper (with subswings)", 246, "ttm-scalper-with-subswings-mt4.ex4",
     "72 KB",
     "Reversal-pattern swing signals for M1-H4; spots price flips and "
     "converts them into swing entries; multi-timeframe by design."),
    ("Solar Wind", 230, "Solar Wind.ex4", "52 KB",
     "Trend-following histogram: direction + strength, for entry/exit "
     "timing or as a confirmation layer on other strategies."),
    ("Band Moving Average (BMA)", 239, "BMA Trend mt4.ex4", "60.8 KB",
     "Custom 3-line MA: a central SMA/EMA/SMMA/WMA with upper/lower lines "
     "shifted +/-2% acting as support/resistance bands."),
    ("DDFX Fast Trend v3", 243, "DDFX Fast Trend v3 mt4.ex4", "50.4 KB",
     "Trend filter around a 'golden line': buy setups only above it, sell "
     "setups only below it."),
    ("Trend Direction & Force Index", 210,
     "Trend direction & force index full.ex4", "58.3 KB",
     "Tracks price change plus the relative force behind it; recommended "
     "as a filter alongside price action."),
    ("SAMURAI v3", 222, "Samuray_v3.ex4", "72.5 KB",
     "Multi-indicator trend composite (MA/RSI/Bollinger/MACD family)."),
    ("ADXR", 227, "ADXR.ex4", "50.6 KB",
     "Smoothed ADX — a trend-strength rating rather than a direction call."),
    ("Binary MoneyArrow", 237, "Binary MoneyArrow mt4.ex4", "52.5 KB",
     "Buy/sell arrow signals for binary options from a trend + oscillator "
     "+ S/R combination."),
    ("GoldRush Trend Arrow Signal", 374, "GoldRush Trend Arrow Signal.ex4",
     "77.8 KB",
     "Trend arrow signals for XAUUSD."),
    ("Trend SniperX MT4", 389, "Trend SniperX MT4.ex4", "183.6 KB",
     "Trend-following sniper entries (large file — extra strategy logic)."),
    ("Multi Sniper", 465, "Multi Sniper mq.ex4", "91.5 KB",
     "Multi-symbol scalping entries; no-grid/no-martingale per the "
     "channel's post (seller's claim, unverified)."),
    ("Solo Sniper Pro", 471, "Solo Sniper Pro mw.ex4", "65 KB",
     "M15 scalping with compound risk management per the channel's post "
     "(seller's claim, unverified)."),
]

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


def _indicator_item(name, post_no, filename, size, note, posts):
    """One curated indicator, enriched when it is in the recent preview."""
    recent = None
    for info in (posts or {}).values():
        if info.get("filename") and info.get("post") == post_no:
            recent = info
            break
    desc = note
    if recent and recent.get("desc") and len(recent["desc"]) > len(note):
        desc = recent["desc"]
    return {
        "name": name,
        "type": "MT4 INDICATOR",
        "recent": bool(recent),
        "filename": (recent or {}).get("filename", filename),
        "size": (recent or {}).get("size") or size,
        "desc": desc,
        "url": TG_BASE + "/" + str(post_no),
        "post": str(post_no),
    }


def ex4_fetch_listing(mode, client=requests):
    """mode 'recent' -> latest channel posts (filename + size guaranteed);
    mode 'ind' -> the curated indicator list (verified file posts, newest
    first; works even when those posts have left the /s/ preview);
    mode 'full' -> the complete site catalogue merged with recent posts.
    Returns a list of items (see _item / _indicator_item). Raises when the
    primary source for the mode is unavailable (recent=channel,
    full=catalogue). The *other* source degrading is non-fatal: full works
    with an empty recent set and recent works with only the live doc posts.
    """
    if mode == "ind":
        try:
            posts = scrape_channel(client)
        except Exception:
            posts = {}  # enrichment is optional; the list is pinned
        return [_indicator_item(name, post_no, filename, size, note, posts)
                for name, post_no, filename, size, note in
                sorted(INDICATORS, key=lambda t: -t[1])]
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
    """Full caption text of one post, keyless, for the WHOLE channel history.

    The single-post page (t.me/<channel>/<post>) is server-rendered and its
    og:description carries the complete post text (verified: 895-char
    descriptions returned intact). The /s/ preview by contrast only holds
    the ~20 latest posts and its document pages omit the text markup, so
    this is the reliable path for older posts. Returns "" when the post has
    no text body (e.g. a pure file post's caption).
    """
    now = time.time()
    hit = _desc_cache.get(post_no)
    if hit and now - hit[1] < _CACHE_TTL:
        return hit[0]
    html = _fetch(TG_BASE + "/" + str(post_no), client)
    m = re.search(r'property="og:description" content="([^"]*)"', html or "")
    text = _strip(m.group(1)) if m else ""
    _desc_cache[post_no] = (text, now)
    return text


def _name_ok(name, text):
    """Guard against grabbing the *neighbouring* item's description: the
    paired text post must mention the item's own name. Token match (not
    substring — "trade" must not match "trader"): at least half of the
    name's significant tokens (len>=3) must appear as tokens in the text."""
    tokens = re.compile(r"[a-z0-9]+")
    nt = {w for w in tokens.findall((name or "").lower()) if len(w) >= 3}
    if not nt:
        return True
    tt = set(tokens.findall((text or "").lower()))
    return len(nt & tt) * 2 >= len(nt)


def ex4_item_detail(item, client=requests):
    """(text, keyboard) for one EA/indicator. Downloads the long description
    from the paired post-1 on first tap (15-min cache); falls back to the
    mechanism note / catalogue blurb when the fetch fails or is shorter."""
    lines = ["🧬 " + str(item.get("name", "EA"))[:90]]
    if item.get("recent"):
        lines.append("✅ decompiled + just posted to the channel")
    lines.append("📐 " + str(item.get("type", "MT4 EXPERT ADVISOR")))
    if item.get("filename"):
        lines.append("📄 " + str(item["filename"])
                     + ("  ·  " + str(item["size"]) if item.get("size") else ""))
    desc = str(item.get("desc", "")).strip()
    post = int(item.get("post") or 0)
    # Long description from the paired text post, for ANY item with a post to
    # read. The channel usually posts description BEFORE the file (post-1);
    # a few drops have it after (post+1/+2, e.g. Wolf Wave at +2). Scan the
    # +/-2 window, keep the longest post that passes the name guard (so the
    # neighbouring item's description is never picked up). Only upgrades to
    # the seller's full text when it is longer than what we already carry.
    if post > 1:
        best = ""
        for off in (-1, 1, -2, 2):
            try:
                got = _fetch_desc(post + off, client=client)
            except Exception:
                continue
            if len(got) > len(best) and _name_ok(item.get("name"), got):
                best = got
        if len(best) > len(desc):
            desc = best
    if desc:
        d = re.sub(r"\s+", " ", desc).strip()
        if len(d) > MAX_DESC:
            d = d[:MAX_DESC].rstrip() + "…"
        lines.append("\n📝 " + d)
    if item.get("url"):
        if "INDICATOR" in str(item.get("type", "")).upper():
            dest = "MQL4/Indicators"
            extra = (" then recompile it to read the source (most ship as "
                     ".ex4; Wolf Wave ships as .mq4).")
        else:
            dest = "MQL4/Experts"
            extra = " and recompile the decompiled .mq4 to read the source."
        lines.append(
            "\n📥 The .ex4 is a Telegram channel document (tg:// protocol — "
            "no public CDN). Open the post below to save it, then drop it in "
            + dest + " of MT4" + extra)
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
    heading = {"recent": "recent decompiled EAs",
               "ind": "decompiled indicators",
               "full": "full EA catalogue"}
    return {
        "text": ("📦 EX4 decompiler — "
                 + heading.get(mode, "full EA catalogue")
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
        [{"text": "📊 Decompiled indicators (" + str(len(INDICATORS)) + ")",
          "callback_data": "ex4:ind"}],
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
    "Daily decompiled MT4 Expert Advisors AND indicators from "
    "ex4tomq4decompiler.com — 145 files since 2023 (full history scraped).\n"
    "Browse: recent drops · a curated list of the decompiled indicators "
    "(Wolf Wave, TTM Scalper, Solar Wind, BMA, DDFX…) · the 83-EA site "
    "catalogue · how the decompilation works.\n"
    "Tap an item for full details + a one-tap link to the exact Telegram "
    "file post (that is how you save the .ex4 — no public CDN; the msasoup "
    "bot is not a channel member)."
)

EX4_STUDY_TEXT = (
    "🧪 Method study — how EX4 → MQ4 decompilation works\n\n"
    "• What a .ex4 is: MT4 Expert Advisors/indicators/scripts compiled to a "
    "Windows PE (DLL-style) binary. Before MT4 build 600 (Feb 2014) the "
    "compiler left enough structure that the classic standalone decompiler "
    "(ex4tomq4 v4.0.427.4) could fully restore .mq4 in seconds. From build "
    "600 on, MetaQuotes compile to native code with optimization + "
    "obfuscation — automatic decompilation became impossible.\n\n"
    "• So it's done now: manual RE — disassembly of the native code, "
    "memory dumps of the running terminal, a real-time debugger, and "
    "overcoming MQL runtime virtualization. That is why services price per "
    "file/complexity (the channel's companion site, ex4tomq4decompiler.com, "
    "sells 'EX4 TO MQ4 DECOMPILER 2027 Pro' + a paid decompilation service; "
    "the free catalogue = what they decompile and drop on the channel). "
    "MT5 .ex5 is harder still (different runtime), hence the MT4 focus.\n\n"
    "• What you can recover: string table, metadata, function skeletons, "
    "and — after a paid decompilation — the decompiled .mq4 logic. Names "
    "are usually mangled; recompile in MetaEditor to read/tweak. Static "
    "extraction only tells you what's observable; signal logic inside "
    "protected builds is not readable without the decompilation itself.\n\n"
    "• Why the file needs Telegram: the .ex4/.mq4 are channel documents "
    "(tg:// file protocol). There is NO public HTTP/CDN link and the msasoup "
    "bot is not a channel member (Bot API getChatMessage → not found), so "
    "the bot gives you the exact post deep link — tap 'Get it on Telegram', "
    "save the file, done. To automate byte-delivery, add the msasoup bot "
    "(or any member bot) as a channel admin with post rights.\n\n"
    "• Quality caveat: '90% win rate / no martingale' claims are the "
    "seller's marketing, not verified stats — backtest in the MT4 strategy "
    "tester before trusting any of them.\n\n"
    "• License note: decompiled copies of third-party products, free for "
    "personal research via the channel — not open-source."
)
