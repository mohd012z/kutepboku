"""MQL5 Code Base scout: trending/viral free EA + indicator source files.

Source: https://www.mql5.com/en/code/{mt5|mt4}/{experts|indicators} — the
MQL5 community code base. Listings are MQL5's own curated/trending order
(no public download-count ranking exists). Files are free community source;
unlike the Internet Archive book pipeline they carry no CC license metadata,
so they are delivered as source files (not open-license books).

Delivery: direct source file when the item page advertises one (.mq5/.mq4),
otherwise the universal <id>.zip bundle. Magic-byte validated, 20 MB cap.
"""
import re
from html import unescape
from urllib.parse import quote

import requests

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
MAX_BYTES = 20 * 1024 * 1024
ITEM_ID = re.compile(r"^\d{4,}$")
INDEX_RE = re.compile(r"^\d+$")
TILE = re.compile(
    r'<div class="title">\s*<a href="(/en/code/(\d+))" title="([^"]+)"')
PER_PAGE = 3

# (key, label, market, kind)
MQL5_LISTINGS = [
    ("mt5:ea", "📈 Trending EAs (MT5)", "mt5", "experts"),
    ("mt5:ind", "📊 Indicators (MT5)", "mt5", "indicators"),
    ("mt4:ea", "📈 Trending EAs (MT4)", "mt4", "experts"),
    ("mt4:ind", "📊 Indicators (MT4)", "mt4", "indicators"),
]

MQL5_TEXT = (
    "🤖 MQL5 Code Base — trending free EAs & indicators\n"
    "These are viral/community MT4/MT5 source files (MQL5's own trending "
    "order). Pick one → I download the .mq5/.mq4 (or full zip) and send it."
)


def listing_url(market, kind):
    return "https://www.mql5.com/en/code/" + market + "/" + kind


def _http_get(url, *, client=requests, timeout=25):
    response = client.get(url, headers={"User-Agent": USER_AGENT},
                          timeout=(5, timeout), allow_redirects=True)
    response.raise_for_status()
    return response


def parse_tiles(html):
    """(id, title) pairs from a code-base listing page."""
    out = []
    for href, item_id, title in TILE.findall(html or ""):
        if not ITEM_ID.fullmatch(item_id):
            continue
        out.append((item_id, unescape(title)[:160]))
    return out


def scrape_trending(market, kind, *, client=requests):
    """Trending listing -> [{id, title, url}]. Raises on network/HTML failure."""
    response = _http_get(listing_url(market, kind), client=client)
    items = parse_tiles(response.text)
    if not items:
        raise ValueError("MQL5 listing returned no items (layout change?)")
    return [{"id": item_id, "title": title,
             "url": "https://www.mql5.com/en/code/" + item_id}
            for item_id, title in items]


def resolve_file(mql5_id, *, client=requests):
    """Pick the deliverable file for an item: direct source file when the item
    page advertises one, else the universal <id>.zip. Returns
    {url, filename, kind}. Raises ValueError when nothing usable is found."""
    response = _http_get("https://www.mql5.com/en/code/" + mql5_id, client=client)
    html = response.text
    m = re.search(r'href="(/en/code/download/' + re.escape(mql5_id)
                  + r'/[^"]+\.(?:mq5|mq4))"', html)
    if m:
        return {"url": "https://www.mql5.com" + m.group(1),
                "filename": m.group(1).rsplit("/", 1)[-1], "kind": "source"}
    # fallback: probe the universal bundle
    bundle = "https://www.mql5.com/en/code/download/" + mql5_id + ".zip"
    head = _http_get(bundle, client=client)
    if head.status_code == 200:
        return {"url": bundle, "filename": mql5_id + ".zip", "kind": "zip"}
    raise ValueError("No downloadable file found for MQL5 item " + mql5_id)


def deliver_file(token, chat_id, item, *, session=requests):
    """Download the item's file and sendDocument. Returns (kind, url, size)."""
    if not ITEM_ID.fullmatch(str(item.get("id", ""))):
        raise ValueError("Invalid MQL5 item id")
    file_info = resolve_file(str(item["id"]), client=session)
    response = session.get(file_info["url"], headers={"User-Agent": USER_AGENT},
                           stream=True, timeout=(10, 90))
    response.raise_for_status()
    chunks = bytearray()
    for chunk in response.iter_content(65536):
        chunks.extend(chunk)
        if len(chunks) > MAX_BYTES:
            raise ValueError("File exceeds 20 MB limit")
    response.close()
    data = bytes(chunks)
    if len(data) < 256:
        raise ValueError("File too small to be a valid MQL5 download")
    if file_info["kind"] == "zip":
        if not data.startswith(b"PK\x03\x04"):
            raise ValueError("Zip signature mismatch")
    elif not (data.startswith(b"//") or b"//+" in data[:2000]):
        raise ValueError("Not an MQL source file")
    from agent import send
    send(session, token, chat_id, file_info["filename"], data,
         "📦 " + str(item.get("title", "MQL5 file"))[:400] + "\n" + item["url"]
         + "\n(MQL5 Code Base — free community source, not a CC book)")
    return file_info["kind"], file_info["url"], len(data)


# --- Telegram pagination for trending listings ------------------------------

def mql5_listing_keyboard(items, page):
    """First `PER_PAGE` titles as buttons + nav; index-based callback data."""
    pages = max(1, (len(items) + PER_PAGE - 1) // PER_PAGE)
    if not isinstance(page, int) or page < 0 or page >= pages:
        raise ValueError("page out of range")
    start = page * PER_PAGE
    keyboard = []
    for i, item in enumerate(items[start:start + PER_PAGE], start):
        keyboard.append([{"text": str(item["title"])[:60], "callback_data": "dlm:" + str(i)}])
    nav = []
    if page > 0:
        nav.append({"text": "⬅️ Prev", "callback_data": "mql5s:" + str(page - 1)})
    if page + 1 < pages:
        nav.append({"text": "Next ➡️", "callback_data": "mql5s:" + str(page + 1)})
    if nav:
        keyboard.append(nav)
    keyboard.append([{"text": "🏠 Home", "callback_data": "ui:home"}])
    return {"inline_keyboard": keyboard}


def mql5_paged_message(items, page):
    start = page * PER_PAGE
    page_count = max(1, (len(items) + PER_PAGE - 1) // PER_PAGE)
    titles = "\n".join(
        str(i + 1) + ". " + str(item["title"])[:70]
        for i, item in enumerate(items[start:start + PER_PAGE], start))
    return {"text": "📈 MQL5 trending (page " + str(page + 1) + "/" + str(page_count)
            + ")\n\n" + titles + "\n\nTap a title to send the file:",
            "reply_markup": mql5_listing_keyboard(items, page)}


def mql5_item_by_index(items, index_str):
    """Validate + fetch one item from the stored listing."""
    if not INDEX_RE.fullmatch(str(index_str)):
        raise ValueError("bad item index")
    index = int(index_str)
    if index < 0 or index >= len(items):
        raise ValueError("item index out of range")
    return items[index]
