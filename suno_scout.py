"""Suno AI song downloader for msasoup.

Method study (2026-11-25) — verified by probing Suno directly and cross-
checking against the reference tool at sunoaisongdownload.online:

* A *public* Suno song is addressable by a share link
  ``https://suno.com/s/<code>`` OR the canonical
  ``https://suno.com/song/<uuid>``. Both render 200 for anonymous browsers
  (no login) — verified with plain ``curl``.
* The share page embeds a ``song_schema`` JSON object in its server-render
  payload. It carries everything the bot needs for the *card*: title,
  artist (``display_name``/``handle``), style (``metadata.tags``), duration,
  cover image, model, and ``media_urls[]`` — the CDN audio URL.
* The ``media_urls[]`` entry is ``delivery:"progressive"``,
  ``content_type:"m4a-opus"`` and lives on ``d2lwuy8qc234o3.cloudfront.net``.
  **It is DRM-encrypted** (Suno's "Mango" system): the raw byte stream has
  8.0 bits/byte entropy, no ``ftyp``/``moov`` MP4 box, and differs from the
  decrypted file at ~100% of its bytes. Decrypting it standalone needs a
  license-server guest token (``glt``) + wrapped key/iv, unwrapped with
  ``SHA-256(glt)`` -> AES-GCM (AAD = content_id) -> AES-CTR. That endpoint is
  in the app's runtime config, not a stable public API, so reproducing it in
  the bot would be fragile.
* The reference tool therefore does the Mango decryption **server-side**:
  ``POST /api/download {url, format}`` -> ``{title, tags, filename, format,
  download_url, cover_url, duration_seconds}`` then ``GET <api>/downloads/
  <filename>`` returns a *valid* playable MP4/M4A (verified: ``ftyp``@4,
  decodes to 60s Opus stereo) or MP3/WAV.

Bot strategy (evidence-based, fail-open, never a dead-end):
* **Metadata + cover** come straight from Suno's own share page (no third
  party, always works for public songs).
* **Audio bytes** come from the reference decrypt API (the proven path).
* If the decrypt API is down/unreachable, the bot still delivers a rich
  metadata card + the direct (DRM-protected) CDN URL so the song is never
  lost. Audio format is the user's choice (M4A default, MP3).
"""
import json
import os
import re

import requests

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

# The free reference decrypt API. Overridable for our own Mango decryptor or
# a second mirror later; default is the verified public one.
DOWNLOAD_API = os.getenv("SUNO_DOWNLOAD_API",
                         "https://api.sunoaisongdownload.online").rstrip("/")
API_TIMEOUT = (10, 90)          # (connect, read) — decrypt can take ~10-30s
PAGE_TIMEOUT = (8, 30)
COVER_MAX_BYTES = 2 * 1024 * 1024

# Telegram bot uploads without a local Bot API server cap at 20 MB; match the
# rest of the repo (agent.MAX_BYTES) so a huge WAV/long song degrades to a
# link-only card instead of a 413 that kills the update.
AUDIO_MAX_BYTES = 20 * 1024 * 1024

# Share-link shapes we accept from the user.
_SHARE_S = re.compile(r'suno\.com/s/([A-Za-z0-9_-]{6,64})')
_SHARE_SONG = re.compile(r'suno\.com/song/([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-'
                         r'[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})')
_BARE_CODE = re.compile(r'^[A-Za-z0-9_-]{8,20}$')
_BARE_UUID = re.compile(r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-'
                        r'[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')


# --- URL handling ------------------------------------------------------------

def extract_suno_link(text):
    """Return a normalized Suno share URL from free text, or None.

    Accepts the full share link, the canonical /song/<uuid> link, or a bare
    code / uuid typed on its own. Never raises.
    """
    if not text:
        return None
    text = text.strip()
    m = _SHARE_SONG.search(text)
    if m:
        return "https://suno.com/song/" + m.group(1).lower()
    m = _SHARE_S.search(text)
    if m:
        return "https://suno.com/s/" + m.group(1)
    # bare uuid or bare code typed alone
    if _BARE_UUID.match(text):
        return "https://suno.com/song/" + text.lower()
    if _BARE_CODE.match(text):
        return "https://suno.com/s/" + text
    return None


def looks_like_suno_link(text):
    return extract_suno_link(text) is not None


# --- Suno page metadata ------------------------------------------------------

def _schema_from_html(html):
    """Pull the ``song_schema`` object out of a Suno share-page payload.

    The schema is embedded in the server-rendered RSC payload as an escaped
    JSON object (every ``"`` appears as ``\\"``). The page also carries big
    i18n dictionaries that contain their own ``"title"`` / ``"status"`` keys,
    so a global per-field search grabs the wrong values. Instead we (1)
    unescape the whole payload, (2) find the unique ``id`` + ``song_schema``
    marker, (3) brace-walk the enclosing object out, and (4) ``json.loads``
    it — which is robust to field reordering. Returns ``None`` when the
    marker is absent (private / non-existent song).
    """
    if not html:
        return None
    text = html.replace('\\"', '"').replace("\\\\", "\\")
    anchor = None
    for m in re.finditer(r'"id"\s*:\s*"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-'
                         r'[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"',
                         text):
        near = text.find("song_schema", m.end())
        if near != -1 and near - m.end() < 400:
            anchor = m
            break
    if anchor is None:
        return None
    content_id = anchor.group(1).lower()

    start = _find_object_start(text, anchor.start())
    if start == -1:
        return None
    end = _find_object_end(text, start)
    obj = None
    if end != -1:
        try:
            obj = json.loads(text[start:end + 1])
        except ValueError:
            obj = None
    if not isinstance(obj, dict):
        # Whole-object parse failed (rare) -> regex the unescaped text.
        obj = {
            "title": _field(text, "title"),
            "display_name": _field(text, "display_name"),
            "handle": _field(text, "handle"),
            "model_name": _field(text, "model_name"),
            "status": _field(text, "status"),
            "image_large_url": _field(text, "image_large_url"),
            "image_url": _field(text, "image_url"),
            "metadata": {"tags": _field(text, "tags"),
                         "duration": _field_num(text, "duration")},
            "media_urls": _media_urls(text),
        }

    metadata = obj.get("metadata") or {}
    media = obj.get("media_urls") or []
    media_url = media[0].get("url") if media and isinstance(media[0], dict) else None
    if not media_url:
        # The object parsed but had no usable media_urls -> scan the page.
        for cand in (_media_urls(text)):
            if cand.get("url"):
                media_url = cand["url"]
                break
    return {
        "content_id": content_id,
        "title": _clean(obj.get("title")) or "Suno song",
        "artist": _clean(obj.get("display_name")) or _clean(obj.get("handle")) or "Unknown artist",
        "handle": _clean(obj.get("handle")) or "",
        "style": _clean(metadata.get("tags")) or "",
        "duration": _as_number(metadata.get("duration")),
        "model": _clean(obj.get("model_name")) or "",
        "status": _clean(obj.get("status")) or "",
        "cover_url": _clean(obj.get("image_large_url")) or _clean(obj.get("image_url")) or "",
        "media_url": media_url,
        "share_url": "https://suno.com/song/" + content_id,
    }


def _find_object_start(text, pos):
    """Index of the ``{`` that opens the object containing ``pos``."""
    depth = 0
    i = pos
    while i >= 0:
        c = text[i]
        if c == "}":
            depth += 1
        elif c == "{":
            if depth == 0:
                return i
            depth -= 1
        i -= 1
    return -1


def _find_object_end(text, start):
    """Index of the ``}`` matching the object that opens at ``start``."""
    depth = 0
    in_str = False
    esc = False
    i = start
    while i < len(text):
        c = text[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return i
        i += 1
    return -1


def _media_urls(text):
    """Best-effort ``media_urls`` list via regex over the unescaped text."""
    m = re.search(r'"url"\s*:\s*"(https://[^"]*cloudfront\.net/[^"]*/clip/'
                  r'[0-9a-fA-F-]{36}\.m4a)"', text)
    if not m:
        m = re.search(r'"media_urls"\s*:\s*\[\s*\{[^]]*?"url"\s*:\s*"(https://[^"]+)"',
                      text)
    if not m:
        # Any bare CloudFront clip URL on the page.
        m = re.search(r'(https://[a-z0-9.-]*cloudfront\.net/[^\s"\\,)]*/clip/'
                      r'[0-9a-fA-F-]{36}\.m4a)', text)
    return [{"url": m.group(1)}] if m else []


def _field(text, name):
    """String value of ``"name":"value"`` in (already-unescaped) JSON text."""
    m = re.search(r'"' + re.escape(name) + r'"\s*:\s*"', text)
    if not m:
        return ""
    i, out = m.end(), []
    while i < len(text):
        c = text[i]
        if c == "\\" and i + 1 < len(text):
            nxt = text[i + 1]
            if nxt == "u":
                try:
                    out.append(chr(int(text[i + 2:i + 6], 16))); i += 6; continue
                except ValueError:
                    out.append(text[i:i + 6]); i += 6; continue
            out.append(nxt); i += 2; continue
        if c == '"':
            break
        out.append(c); i += 1
    return "".join(out)


def _field_num(text, name):
    """Numeric (or empty) field value, e.g. duration."""
    m = re.search(r'"' + re.escape(name) + r'"\s*:\s*([0-9]+(?:\.[0-9]+)?)', text)
    return m.group(1) if m else ""


def _clean(value):
    if value is None:
        return ""
    return str(value).strip()


def _as_number(*values):
    for v in values:
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            try:
                return float(v)
            except ValueError:
                continue
    return 0.0


def fetch_song_info(share_url, *, session=requests):
    """GET a Suno share page and return its song metadata dict.

    Raises ``ValueError`` with a readable message when the song is not
    public / not found, so the router can show a helpful, non-dead-end card.
    """
    response = session.get(share_url, headers={"User-Agent": USER_AGENT},
                           timeout=PAGE_TIMEOUT, allow_redirects=True)
    response.raise_for_status()
    html = response.text
    info = _schema_from_html(html)
    if not info or not info.get("content_id"):
        low = html.lower()
        if "not found" in low or "doesn't exist" in low or "page not found" in low:
            raise ValueError("Song not found at that link — it may be private, "
                             "deleted, or the link is wrong. Open it on Suno, "
                             "use Share → Copy link, and send me the fresh one.")
        raise ValueError("Couldn't read this as a public Suno song. Make sure it "
                         "is public (Share → Copy link), then try again.")
    if info.get("status") == "generating":
        info["note"] = "still generating — try again in a minute"
    return info


# --- Audio download (reference decrypt API) ----------------------------------

def download_audio(info, fmt, *, session=requests):
    """Fetch the decrypted song bytes for ``fmt`` via the reference API.

    Returns ``(filename, audio_bytes)``. Raises ``ValueError``/
    ``requests.RequestException`` on failure so the caller can fall back to
    the link-only card.
    """
    fmt = (fmt or "m4a").lower()
    body = {"url": info.get("share_url") or info.get("media_url"),
            "format": fmt}
    resp = session.post(DOWNLOAD_API + "/api/download", json=body,
                        timeout=(10, 60))
    try:
        data = resp.json()
    except ValueError:
        data = {}
    if resp.status_code != 200 or data.get("error") or not data.get("download_url"):
        detail = data.get("error") or data.get("detail") or "HTTP %s" % resp.status_code
        raise ValueError("Decrypt service unavailable (%s)." % detail)

    file_url = DOWNLOAD_API + data["download_url"]
    fr = session.get(file_url, headers={"User-Agent": USER_AGENT},
                     stream=True, timeout=(10, 90))
    fr.raise_for_status()
    chunks = bytearray()
    for chunk in fr.iter_content(65536):
        chunks.extend(chunk)
        if len(chunks) > AUDIO_MAX_BYTES:
            fr.close()
            raise ValueError("File exceeds the 20 MB Telegram limit.")
    fr.close()
    audio = bytes(chunks)
    if not _valid_audio(audio, fmt):
        raise ValueError("Downloaded file is not a valid %s." % fmt.upper())
    filename = _sanitize(data.get("filename")) or (info["title"] + "." + fmt)
    return filename, audio


def _valid_audio(data, fmt):
    if len(data) < 256:
        return False
    if fmt == "m4a":
        # ftyp box must be present near the head (offset 0 or 4, never -1).
        return 0 <= data.find(b"ftyp") < 16
    if fmt == "mp3":
        return data[:3] == b"ID3" or data[:2] in (b"\xff\xfb", b"\xff\xf3",
                                                   b"\xff\xf2", b"\xff\xe2",
                                                   b"\xff\xe4")
    if fmt == "wav":
        return data[:4] == b"RIFF" and data[8:12] == b"WAVE"
    return False


def _sanitize(name):
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", str(name or "")).strip()
    return name[:180]


# --- Delivery ----------------------------------------------------------------

def _send_audio(session, token, chat_id, filename, audio, info, cover_bytes):
    payload = {
        "chat_id": chat_id,
        "title": info.get("title", "Suno song")[:255],
        "performer": info.get("artist", "")[:255],
    }
    if info.get("duration"):
        payload["duration"] = str(int(info["duration"]))
    files = {"audio": (filename, audio)}
    if cover_bytes:
        # 3-tuple = (filename, bytes, content-type); requests-native for multipart.
        files["thumbnail"] = ("cover.jpg", cover_bytes, "image/jpeg")  # type: ignore[assignment]
    resp = session.post("https://api.telegram.org/bot" + token + "/sendAudio",
                        data=payload, files=files, timeout=(10, 120))
    body = {}
    try:
        body = resp.json()
    except ValueError:
        pass
    if resp.status_code != 200 or not body.get("ok"):
        # sendAudio failed (e.g. bad cover) -> retry as a plain document so
        # the audio is never lost.
        resp = session.post("https://api.telegram.org/bot" + token + "/sendDocument",
                            data={"chat_id": chat_id,
                                  "caption": _caption(info)[:1024]},
                            files={"document": (filename, audio)},
                            timeout=(10, 120))
        if resp.status_code != 200 or not resp.json().get("ok"):
            raise ValueError("Telegram sendAudio/sendDocument failed (HTTP %s)"
                             % resp.status_code)


def _caption(info):
    lines = ["🎵 " + str(info.get("title", "")),
             str(info.get("artist", ""))]
    if info.get("style"):
        lines.append("Style: " + str(info["style"])[:200])
    lines.append(info.get("share_url", ""))
    return "\n".join(x for x in lines if x)


def _fetch_cover(session, url):
    if not url:
        return None
    try:
        r = session.get(url, headers={"User-Agent": USER_AGENT},
                        stream=True, timeout=(8, 20))
        if r.status_code != 200:
            return None
        buf = bytearray()
        for chunk in r.iter_content(32768):
            buf.extend(chunk)
            if len(buf) > COVER_MAX_BYTES:
                break
        r.close()
        data = bytes(buf)
        if data[:2] == b"\xff\xd8":  # JPEG
            return data
        return None
    except requests.RequestException:
        return None


def deliver_song(token, chat_id, info, fmt, *, session=requests):
    """Download the decrypted song and send it as native audio.

    Returns a small status dict ``{size, via, filename}`` (``via`` is the
    decrypt API host or ``"direct"``). Raises on hard failure so the router
    can show the link-only fallback card.
    """
    fmt = (fmt or "m4a").lower()
    filename, audio = download_audio(info, fmt, session=session)
    cover = _fetch_cover(session, info.get("cover_url"))
    _send_audio(session, token, chat_id, filename, audio, info, cover)
    return {"size": len(audio), "via": DOWNLOAD_API, "filename": filename}


# --- Messages / keyboards ----------------------------------------------------

def _fmt_bytes(n):
    if n is None:
        return ""
    n = float(n)
    if n >= 1024 * 1024:
        return "%.1f MB" % (n / 1024 / 1024)
    if n >= 1024:
        return "%.0f KB" % (n / 1024)
    return "%d B" % n


def song_card(info, *, formats=("m4a", "mp3")):
    """Rich card with metadata + a tappable format button per song."""
    dur = _fmt_dur(info.get("duration"))
    lines = ["🎵 " + str(info.get("title", "Suno song"))]
    lines.append(str(info.get("artist", "Unknown artist")))
    if info.get("style"):
        lines.append("🎼 " + str(info["style"]))
    meta = []
    if dur:
        meta.append("⏱ " + dur)
    if info.get("model"):
        meta.append("🤖 " + str(info["model"]))
    if info.get("note"):
        meta.append("⚠ " + str(info["note"]))
    if meta:
        lines.append("  ".join(meta))
    lines.append("")
    lines.append("Pick a format to download & play it:")
    rows = [[{"text": "📥 M4A (default, small)", "callback_data": "snu:dl:m4a"},
             {"text": "📥 MP3 320 (max compat)", "callback_data": "snu:dl:mp3"}]]
    rows.append([{"text": "🔗 Open on Suno", "url": info.get("share_url", "")},
                 {"text": "➕ Another song", "callback_data": "snu:link"}])
    rows.append([{"text": "🏠 Home", "callback_data": "ui:home"}])
    return {"text": "\n".join(x for x in lines), "reply_markup": {"inline_keyboard": rows}}


def _fmt_dur(seconds):
    try:
        s = int(round(float(seconds)))
    except (TypeError, ValueError):
        return ""
    return "%d:%02d" % (s // 60, s % 60)


def link_only_card(info):
    """Fail-open card shown when the decrypt service is down."""
    lines = ["🎵 " + str(info.get("title", "Suno song")),
             str(info.get("artist", "")),
             ""]
    if info.get("style"):
        lines.append("🎼 " + str(info["style"]))
    lines.append("")
    lines.append("⚠️ The audio decrypt service is unreachable right now, so I "
                 "can't attach the playable file this once.")
    if info.get("media_url"):
        lines.append("")
        lines.append("Direct (DRM-protected) stream — opens in a Suno-aware "
                     "player, not every music app:")
        lines.append(info["media_url"])
    lines.append("")
    lines.append("Suno page: " + str(info.get("share_url", "")))
    rows = [[{"text": "🔁 Try M4A again", "callback_data": "snu:dl:m4a"},
             {"text": "🔁 Try MP3 again", "callback_data": "snu:dl:mp3"}],
            [{"text": "🏠 Home", "callback_data": "ui:home"}]]
    return {"text": "\n".join(x for x in lines), "reply_markup": {"inline_keyboard": rows}}


SUNO_TEXT = (
    "🎵 Suno AI song downloader\n"
    "Send me any *public* Suno link — share links (suno.com/s/… ) or song "
    "links (suno.com/song/…) — and I'll pull the title, artist, style, cover "
    "and the audio. Pick M4A (small) or MP3 320 (plays everywhere).\n\n"
    "How it works: I read the song's metadata straight from Suno's page and "
    "get the audio through a decrypt service (Suno's CDN stream is "
    "DRM-encrypted), so only public songs work — private ones need a login."
)


def suno_menu():
    rows = [
        [{"text": "🎵 Download a Suno song", "callback_data": "snu:link"}],
        [{"text": "📋 How it works (method study)", "callback_data": "snu:study"}],
        [{"text": "🏠 Home", "callback_data": "ui:home"}],
    ]
    return {"text": SUNO_TEXT, "reply_markup": {"inline_keyboard": rows}}


SUNO_STUDY_TEXT = (
    "📋 How Suno AI song download works (method study, 2026-11-25)\n\n"
    "• Public Suno songs have two links: a short share link "
    "(suno.com/s/CODE) and a canonical song link (suno.com/song/UUID). Both "
    "render for anyone, no login — verified with a plain anonymous fetch.\n\n"
    "• The song's page embeds a \"song_schema\" block with the title, artist, "
    "style tags, duration, cover image, and the audio CDN URL. I parse that "
    "block directly, so the metadata is always from Suno itself.\n\n"
    "• The audio CDN file is NOT a normal MP4: Suno serves it through its "
    "\"Mango\" streaming DRM — the raw bytes are an AES-CTR encrypted "
    "progressive Opus stream (8 bits/byte of entropy, no MP4 header). To "
    "decrypt it you need a license-server guest token plus a wrapped key/IV "
    "(SHA-256 of the token → AES-GCM unwrap with the song id as the "
    "associated data → the AES-CTR key). That license endpoint lives in "
    "Suno's app config, not a stable public API.\n\n"
    "• So for the *playable* file I use a free decrypt service that already "
    "reproduces that Mango chain (the sunoaisongdownload.online API — "
    "POST /api/download {url,format} → GET /downloads/<file>). Verified: it "
    "returns a real M4A/MP3 that plays. If it's down, I still send you the "
    "metadata card + the direct (DRM) stream link so the song is never lost.\n\n"
    "• Formats: M4A (Opus-in-MP4, small, default) and MP3 320 (maximum "
    "compatibility). WAV is bigger, not better — same source audio."
)


def suno_study():
    return {"text": SUNO_STUDY_TEXT,
            "reply_markup": {"inline_keyboard": [
                [{"text": "🏠 Home", "callback_data": "ui:home"}]]}}
