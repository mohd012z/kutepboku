"""Async Telegram update router: msasoup conversational eBook assistant.

Flow:
  /start or Home button -> category menu (buttons)
  category / typed request -> search (Minda intent + IA discovery + CC gate
    + Minda relevance) -> paginated book list
  book tapped -> "Send file here" / "Link only"
  Send file -> download + sendDocument; Link -> archive.org URL
  LLM unavailable -> raw-topic search fallback (never blocks)
"""
import asyncio
import os
import secrets

import requests

from session_manager import SessionManager
from search_pagination import (build_search_keyboard, new_search_session,
                               process_search_callback)
from ai_assistant import (BOT_COMMANDS, HELP_TEXT, _chat_reply, ask_intent,
                          auto_menu, category_topic, command_action,
                          deliver_file, delivery_keyboard,
                          delivery_nav_keyboard, find_menu, home_menu,
                          mql5_menu, termux_menu)
from mql5_scout import (MQL5_LISTINGS, mql5_item_by_index, mql5_paged_message,
                        scrape_trending)
from mql5_scout import deliver_file as mql5_deliver_file
from auto_scout import (_TOOL_LOOKUP, _default_branch, deliver_zip,
                        trending_repos)
from find_all import (_TOPIC_LOOKUP, find_all, find_all_keyboard,
                      find_all_message)
from agent_skills import agent_skills
from prompt_forge import forge_menu, forge_prompt, prompt_text

# callback key ("mt5:ea") -> (market, kind)
_MQL5_LOOKUP = {key: (market, kind) for key, _label, market, kind in MQL5_LISTINGS}

# termux:ghidra / termux:radare2 / termux:frida -> verified Termux how-to
_TERMUX_RE_INFO = {
    "ghidra": (
        "🧩 Ghidra in Termux (Java app — runs on openjdk-21; GUI needs X11)\n\n"
        "pkg install openjdk-21 unzip\n"
        "wget -O ghidra.zip https://github.com/NationalSecurityAgency/"
        "ghidra/releases/download/Ghidra_12.1.4_build/"
        "ghidra_12.1.4_PUBLIC_20260921.zip\n"
        "unzip ghidra.zip && cd Ghidra_12.1.4_PUBLIC_20260921\n"
        "# GUI (official x11 repo, per termux/termux-x11 README):\n"
        "pkg install x11-repo\n"
        "pkg install termux-x11\n"
        "termux-x11 :0 & ./ghidraRun\n"
        "# headless (no GUI needed):\n"
        "support/analyzeHeadless.sh proj 1 -import app.apk\n\n"
        "Tip: raise the heap in ghidraRun (JAVA_OPTS) — phones have ~2-4 GB."),
    "radare2": (
        "🐚 radare2 in Termux (native package, fully headless)\n\n"
        "pkg install radare2\n"
        "r2 -q app.apk\n"
        "[0:]> i      # classes / methods / libraries\n"
        "[0:]> afl    # list functions\n"
        "[0:]> pdf @ sym.method   # disassemble one function\n"
        "[0:]> iz     # interesting strings\n"
        "[0:]> s main; pd 30\n"
        "r2 -q -d /system/bin/mediaserver   # debug a live process\n\n"
        "PATCH (write opcodes/bytes, in place):\n"
        "[0:]> wa add x0, x22, 0x20   # write/replace instruction at cursor\n"
        "[0:]> wx 17 @ 0x4010   # write raw hexpair bytes at addr\n"
        "[0:]> wao 'je' 'jne'   # modify a jump's condition in place\n"
        "[0:]> /a add x0, x22   # search bytes BY assembly (find the insn)\n"
        "[0:]> wc   # list write-changes (undo before saving)\n\n"
        "ESIL (reason about what a patch does, no device):\n"
        "[0:]> e emu.str=true; pd 20 @ fcn   # show reg/mem effect per insn\n\n"
        "Memory maps (debugger mode, like MemTool):\n"
        "[0:]> dm   # list maps; dm= bars; dmd dump region; dmh heap\n\n"
        "Also bundled: rabin2, radiff2 (diff two apks), rasm2, rz find.\n"
        "Full reference: book.rada.re (the radare2 book)."),
    "frida": (
        "🪝 Frida in Termux (instrument + hook a running app)\n\n"
        "pkg install python curl unzip\n"
        "pip install frida-tools\n"
        "# frida-server (matches frida version, arm64):\n"
        "curl -O https://github.com/frida/frida/releases/download/"
        "16.7.10/frida-server-16.7.10-android-arm64.xz\n"
        "unxz frida-server-*.xz && chmod 755 frida-server-16.7.10-android-arm64\n"
        "adb push frida-server-16.7.10-android-arm64 /data/local/tmp/frida-server\n"
        "adb shell \"su -c '/data/local/tmp/frida-server -D &'\"\n"
        "frida -U -f com.example.app -l script.js   # spawn + hook\n"
        "frida-ps -U    # list running apps\n\n"
        "On the same phone: skip adb, run frida-server in one Termux tab, "
        "frida tools in another. Root (magisk) or an app you own for "
        "spawning; non-root can attach to unhardened apps."),
    "hbctool": (
        "📦 hbctool in Termux — assemble/disassemble Hermes bytecode "
        "(React Native)\n\n"
        "pip install hbctool   (or: pip install <the>.whl)\n"
        "# 1) pull the RN bundle out of the APK:\n"
        "apktool d app.apk\n"
        "cp app.apk/assets/index.android.bundle .\n"
        "# 2) disassemble -> metadata.json + string.json + instruction.hasm\n"
        "hbctool disasm index.android.bundle hasm_dir\n"
        "# 3) patch strings / register operands in the .hasm, then reassemble\n"
        "hbctool asm hasm_dir index.android.bundle\n\n"
        "Supports HBC versions 59-96 (this build), magic "
        "0x1F1903C103BC1FC6. Verified: disasm->patch->asm->reload OK.\n"
        "Limits: patched strings/instructions may not grow past the "
        "original length (overflow patching not supported yet).\n"
        "Caveat: .hasm text drops the decorative string-lookup comments "
        "(; Oper[i]: String(id) '...') — operand VALUES round-trip fine "
        "(verified); edit by number, check string.json for the text."),
    "flutter": (
        "🐦 Flutter (Dart AOT) RE in Termux — blutter + PPTool\n\n"
        "# VIP logic in Flutter apps lives in libapp.so (Dart AOT), not\n"
        "# smali. Workflow (grounded in Lazy_Flutter_patcher.py study):\n"
        "pkg install python cmake ninja git unzip\n"
        "git clone https://github.com/worawit/blutter && cd blutter\n"
        "python3 blutter.py arm64-v8a out_dir   # first run builds C++\n"
        "# -> out_dir/pp.txt = Object Pool map, Dart decompiled per class\n"
        "# resolve the target object's pool offset from pp.txt, then:\n"
        "pip install <pptool release wheel>   # Kirlif/PPTool (not on PyPI)\n"
        "pptool libapp.so 0x<pp_off>   # -> function addresses that load it\n"
        "# patch in r2 (pkg install radare2):\n"
        "r2 -w libapp.so -c 's 0x<addr>; wa <insn>'\n\n"
        "Pattern: swap a struct-field immediate (e.g. add x0,x22,0x30 -> "
        "0x20) to read the sibling 'unlocked' member. Re-sign after patching "
        "if you install normally (apksigner)."),
    "ytdlp": (
        "🎬 yt-dlp in Termux (YTDLnis GUI's engine — native pkg)\n\n"
        "pkg install python-yt-dlp ffmpeg\n"
        "yt-dlp --version\n\n"
        "Video (best 1080p, merged mp4):\n"
        "yt-dlp -f 'bestvideo[height<=1080]+bestaudio/best[height<=1080]' "
        "--merge-output-format mp4 <url>\n"
        "Audio (best flac / 320k mp3):\n"
        "yt-dlp -x --audio-format flac <url>\n"
        "yt-dlp -x --audio-format mp3 --audio-quality 320K <url>\n\n"
        "Options the YTDLnis GUI wraps:\n"
        "--embed-metadata --embed-thumbnail   # tags + cover\n"
        "--write-subs --sub-langs 'en.*,original' --embed-subs\n"
        "--sponsorblock-remove sponsor,intro,outro\n"
        "--split-chapters --embed-chapters\n"
        "yt-dlp -a urls.txt   # batch: one URL per line\n\n"
        "More (verified against yt-dlp upstream options.py):\n"
        "yt-dlp -s --write-thumbnail --convert-thumbnails jpg <url>\n"
        "   # thumbnail only (-s = --skip-download)\n"
        "yt-dlp --download-sections '*00:01:30-00:02:45' <url>\n"
        "   # clip a time range (MM:SS or HH:MM:SS)\n"
        "yt-dlp --format-sort vcodec:vp9 <url>   # prefer vp9/av1\n"
        "yt-dlp --get-id --flat-playlist <playlist_url>\n"
        "   # cheap playlist expansion (ids only, no per-video meta)\n\n"
        "This file (ytdlnis.py v2.2 / ytdlnis_gui.py, by @bang_albin) = "
        "CLI + tkinter front-ends over yt-dlp. The headless CLI does "
        "everything without a GUI; for the GUI on Termux: pkg install "
        "python-tkinter x11-repo termux-x11, then termux-x11 :0 & "
        "python ytdlnis_gui.py (needs a display).\n"
        "YTDLnis (deniscerri) = the Android app this is ported from.\n\n"
        "📸 Instagram (InstaDownload.py = rich-TUI wrapper over instaloader):\n"
        "pip install instaloader   # pure Python; also works in Termux\n"
        "python -m instaloader <username>   # whole profile\n"
        "python -m instaloader --post <shortcode>   # one post/reel\n"
        "python -m instaloader <hashtag>   # by tag\n"
        "Stories/highlights need a logged-in session: instaloader --login. "
        "The script's extras (rate-limit, dedupe-by-hash, ffmpeg audio "
        "extract, smart folder org) are a thin layer over these."),
    "datainject": (
        "💉 LSPosed Data-Inject Hook (login-state persistence)\n\n"
        "Pattern (MemTool/Jiagu sibling — the 'data' way, no code patching):\n"
        "an Xposed/LSPatch module injects a captured shared_prefs XML into "
        "the target app's /data/data/ at launch, so the app re-reads a "
        "logged-in session (subscriber id, login time, tokens) after "
        "updates/clears.\n\n"
        "Anatomy (studied: Antik Mods 'login Data Injection Hook 💉'):\n"
        "• UserBook.txt = the smali line LSPatch inserts at the app's "
        "launch point: invoke-static -> entry class (Object)V\n"
        "• assets/Antik.json = {targetPackageName, folderName, fileName}\n"
        "• assets/exampleYour.xml = the captured XML to inject "
        "(template: a T-Sports shared_prefs dump)\n"
        "• classes99.dex: entry class -> Hook.DataInjection(context): "
        "read Antik.json -> PackageManager check target installed -> "
        "copy asset to /data/data/<folderName>/<fileName>\n\n"
        "Use (rooted, or LSPatch with WRITE access):\n"
        "1) capture the real prefs: adb pull /data/data/<pkg>/shared_prefs/\n"
        "2) rename to your fileName, edit values, put in module assets\n"
        "3) set Antik.json (folderName = shared_prefs for that XML)\n"
        "4) LSPatch the target app with the module / insert UserBook.txt "
        "line at the app's first-activity onCreate\n\n"
        "Quick no-module test (root + adb):\n"
        "adb root; adb push exampleYour.xml "
        "/data/data/<pkg>/shared_prefs/prefs.xml\n"
        "adb shell am force-stop <pkg>   # then relaunch -> logged in\n\n"
        "Differs from the VIP code patches (add x0,x22,...): this swaps "
        "DATA, not bytecode. Caveat: shipped example contains real "
        "subscriber data (T-Sports BD) — treat as template; capture your "
        "own XML from your own account."),
}

db = None

# Leading words users often prepend to a book topic; stripped before the
# search so "Search ebook bbma" is treated as the topic "bbma".
_QUERY_FILLER = (
    "search for", "search ebook", "search e-books", "search books", "search book",
    "search about", "search", "find for", "find me a", "find me", "find an",
    "find the", "find a", "find", "look for", "look up", "lookup", "look up",
    "ebooks about", "ebook about", "ebooks of", "ebook of", "books about",
    "book about", "books on", "book on", "about",
)


def _clean_query(text):
    """Strip leading filler words, keeping only the actual topic."""
    t = (text or "").strip()
    prev = None
    while prev != t and t:
        prev = t
        for filler in _QUERY_FILLER:
            if t.lower().startswith(filler):
                t = t[len(filler):].strip(" ,:;-")
                break
    return t or (text or "").strip()


def session_store():
    global db
    if db is None:
        db = SessionManager(os.getenv("BOT_DB_PATH", "bot_sessions.db"))
    return db


def _is_allowed(user_id):
    allowed = {int(value.strip()) for value in
               os.getenv("TELEGRAM_ALLOWED_USER_IDS", "").split(",")
               if value.strip().isdigit()}
    return user_id in allowed


async def _reply_long(message, text, **kwargs):
    """Send text that may exceed Telegram's 4096-char limit by splitting on
    newlines; only the final chunk carries reply_markup. Without this a long
    reply raises BadRequest and kills the whole update (the prompt/clone
    'nothing happens' bug)."""
    limit = 4000  # stay safely under Telegram's 4096
    if len(text) <= limit:
        await message.reply_text(text, **kwargs)
        return
    chunks, cur = [], ""
    for line in text.split("\n"):
        piece = (cur + "\n" + line) if cur else line
        if len(piece) > limit and cur:
            chunks.append(cur)
            cur = line
        else:
            cur = piece
    if cur:
        chunks.append(cur)
    for chunk in chunks[:-1]:
        await message.reply_text(chunk)
    await message.reply_text(chunks[-1], **kwargs)


async def _search_and_present(message, user_id, topic, store, search_provider):
    """Run the provider and show the paginated book list (or an explanation)."""
    if search_provider is None:
        await message.reply_text("Search is not configured yet.")
        return
    results = await search_provider(topic)
    # Built-in agent: study this search (levels up, learns the domain).
    n = len(results) if isinstance(results, list) else 0
    try:
        gained, level = agent_skills().record_search(topic, n, source="ebook")
    except Exception:
        gained, level = 0, 1
    if not isinstance(results, list) or not results:
        await message.reply_text(
            "No open-licensed books found for “" + topic[:60] + "”.\n"
            "Only explicitly CC-licensed (open) documents are offered, so "
            "results are sparse — try a broader topic (e.g. machine learning, "
            "chemistry, philosophy).\n\n🧠 +{g} XP → L{lv}".format(g=gained, lv=level))
        store.set_session(user_id, "MENU", {})
        return
    token = secrets.token_hex(6)
    data = new_search_session(topic, results, token)
    store.set_session(user_id, "SELECTING_BOOK", data)
    await message.reply_text(
        "📚 Found " + str(len(results)) + " open-licensed book(s) for “"
        + topic[:60] + "” — pick one:\n\n🧠 +{g} XP → L{lv}".format(g=gained, lv=level),
        reply_markup=build_search_keyboard(results, 0, token))


async def _deliver(callback, user_id, store, book, mode, sdata=None):
    """mode 'file' -> download + sendDocument; 'link' -> send the URL.
    Restores the results list (CHOOSE_DELIVERY) after delivery and shows
    nav buttons so the user can go back to results or search more."""
    message = callback.message
    restored = False
    if isinstance(sdata, dict):
        results = sdata.get("results")
        token = sdata.get("search_token")
        if isinstance(results, list) and results and token:
            store.set_session(user_id, "CHOOSE_DELIVERY", dict(sdata))
            restored = True
    nav = delivery_nav_keyboard() if restored else None
    if mode == "link":
        url = str(book.get("source_url", ""))
        if not url:
            await message.reply_text("Link unavailable for this book.")
            return
        await message.reply_text(
            "🔗 " + str(book.get("title", "Open eBook"))[:120] + "\n" + url,
            reply_markup=nav)
        return
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = str(os.getenv("TELEGRAM_DELIVERY_CHAT_ID") or user_id)
    await message.reply_text("⏳ Downloading — files up to 20 MB take a moment…")
    url = str(book.get("source_url", ""))
    try:
        ext, _ = await asyncio.to_thread(deliver_file, token, chat_id, book)
    except Exception:
        await message.reply_text(
            "File delivery failed — direct link instead:\n" + url,
            reply_markup=nav)
        return
    await message.reply_text(
        "✅ Sent (." + ext + "). Direct link:\n" + url, reply_markup=nav)


async def _run_action(action, user_id, store, message, intent_result, raw_text):
    """Dispatch a non-search intent. Returns True when handled."""
    if action == "home":
        store.set_session(user_id, "MENU", {})
        menu = home_menu()
        await message.reply_text(menu["text"], reply_markup=menu["reply_markup"])
        return True
    if action == "help":
        await message.reply_text(HELP_TEXT)
        return True
    if action == "cancel":
        store.clear_session(user_id)
        await message.reply_text("Cancelled.")
        return True
    if action == "chat":
        reply = _chat_reply(intent_result, raw_text)
        if reply:
            await message.reply_text(reply)
        return True
    return False


async def _run_command(action, user_id, store, message, search_provider):
    """Dispatch a BOT_COMMANDS action string (see ai_assistant.BOT_COMMANDS)."""
    if action == "home":
        store.set_session(user_id, "MENU", {})
        menu = home_menu()
        await message.reply_text(menu["text"], reply_markup=menu["reply_markup"])
        return
    if action == "help":
        await message.reply_text(HELP_TEXT)
        return
    if action == "cancel":
        store.clear_session(user_id)
        await message.reply_text("Cancelled.")
        return
    if action == "admin":
        # /status + /backup are handled by main.py's CommandHandlers; if this
        # is reached the user is not the configured admin.
        await message.reply_text("Admin-only command (status/backup).")
        return
    if action.startswith("search:"):
        topic = action.split(":", 1)[1]
        await _search_and_present(message, user_id, topic, store,
                                  search_provider)
        return
    if action == "mql5_menu":
        menu = mql5_menu()
        await message.reply_text(menu["text"], reply_markup=menu["reply_markup"])
        return
    if action == "auto_menu":
        menu = auto_menu()
        await message.reply_text(menu["text"], reply_markup=menu["reply_markup"])
        return
    if action == "termux_menu":
        menu = termux_menu()
        await message.reply_text(menu["text"], reply_markup=menu["reply_markup"])
        return
    if action == "find_menu":
        menu = find_menu()
        await message.reply_text(menu["text"], reply_markup=menu["reply_markup"])
        return
    if action == "agent":
        try:
            await message.reply_text(agent_skills().summary_text())
        except Exception:
            await message.reply_text("🧠 Agent view unavailable right now.")
        return
    if action == "prompt_menu":
        menu = forge_menu()
        await message.reply_text(menu["text"], reply_markup=menu["reply_markup"])
        return
    if action.startswith("find:"):
        key = action.split(":", 1)[1]
        if key not in _TOPIC_LOOKUP:
            await message.reply_text("Unknown area.")
            return
        await _run_find_all(message, user_id, store, search_provider, key=key)
        return


async def _run_find_all(message, user_id, store, search_provider,
                        topic=None, key=None):
    """Combined Find ALL: open ebooks + apps/repos for one topic.

    A curated AI sub-topic (key) runs immediately on its known phrasing; a
    bare call (topic=None, key=None) enters FIND_TOPIC and waits for the
    user to type a topic (free-form path)."""
    if topic is None and key in _TOPIC_LOOKUP:
        topic = _TOPIC_LOOKUP[key][2]  # the ebook-side phrasing
    if topic is None:
        store.set_session(user_id, "FIND_TOPIC", {})
        await message.reply_text(
            "✍️ What topic? Reply with it — e.g. \"ai agent\", "
            "\"web automation\", \"forex trading\". "
            "I'll gather open ebooks AND the best apps together. "
            "(❌ Cancel to stop.)")
        return
    topic = str(topic)[:200]
    await message.reply_text("⏳ Finding ALL for “" + topic + "” — ebooks + apps…")
    try:
        ebooks = (await search_provider(topic)) if search_provider is not None else []
        if not isinstance(ebooks, list):
            ebooks = []
    except Exception:
        ebooks = []
    result = await asyncio.to_thread(find_all, topic, key=key, ebooks=ebooks)
    # Built-in agent: study this search too.
    try:
        gained, level = agent_skills().record_search(topic, len(result["ebooks"]),
                                                     source="find_all")
    except Exception:
        gained, level = 0, 1
    token = secrets.token_hex(6)
    store.set_session(user_id, "FIND_RESULT",
                      {"result": result, "fa_token": token})
    await _reply_long(message, find_all_message(result)
                      + "\n\n🧠 +" + str(gained) + " XP → L" + str(level),
                      reply_markup=find_all_keyboard(result, token))


async def _send_repo_zip(update, user_id, store, item):
    """Resolve branch, download the repo zip, sendDocument; >20 MB or any
    failure falls back to the repo link. `item` needs id/title/url."""
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = str(os.getenv("TELEGRAM_DELIVERY_CHAT_ID") or user_id)
    message = update.callback_query.message
    await update.callback_query.answer("⏳ Resolving + downloading…")
    repo = {**item}
    try:
        repo["branch"] = await asyncio.to_thread(_default_branch, item["id"])
        size, _ = await asyncio.to_thread(
            deliver_zip, token, chat_id, repo, session=requests)
    except ValueError as err:
        if message is not None:
            await message.reply_text("🔗 " + item["id"] + " — " + str(err)
                                     + ":\n" + item["url"])
        return
    except Exception:
        if message is not None:
            await message.reply_text("⚠️ Download failed — repo link instead:\n"
                                     + item["url"])
        return
    if message is not None:
        await message.reply_text("✅ Sent " + item["id"] + " ("
                                 + str(round(size / 1024)) + " KB)\n" + item["url"])


async def handle_update(update, context, *, search_provider=None, store=None):
    store = store or session_store()
    user = getattr(update, "effective_user", None)
    if user is None:
        return
    user_id = user.id
    if not _is_allowed(user_id):
        callback = getattr(update, "callback_query", None)
        if callback is not None:
            await callback.answer("Not authorized", show_alert=True)
        return

    # ---- callbacks ------------------------------------------------------
    callback = getattr(update, "callback_query", None)
    if callback is not None:
        data = callback.data or ""
        if data.startswith("sr:"):
            result = process_search_callback(
                user_id, data, load_session=store.get_session,
                save_session=store.set_session, clear_session=store.clear_session)
            await callback.answer("" if result["ok"] else result["error"],
                                   show_alert=not result["ok"])
            if not result["ok"]:
                return
            if result["action"] == "page":
                await callback.edit_message_text(
                    "Choose an eBook", reply_markup=result["keyboard"])
            elif result["action"] == "selected":
                store.set_session(user_id, "CHOOSE_DELIVERY", {"book": result["book"]})
                await callback.edit_message_text(
                    "📖 " + str(result["book"]["title"])[:120] + "\n\n"
                    "How should I deliver it?",
                    reply_markup=delivery_keyboard())
            elif result["action"] == "cancel":
                store.clear_session(user_id)
                await callback.edit_message_text("Search cancelled.")
            return
        if data.startswith("dl:"):
            mode = data[3:]
            state, sdata = store.get_session(user_id)
            book = sdata.get("book") if isinstance(sdata, dict) else None
            if state != "CHOOSE_DELIVERY" or not isinstance(book, dict) \
                    or not book.get("source_url"):
                await callback.answer("This selection has expired.", show_alert=True)
                await callback.edit_message_text(
                    "Expired — tap /start and pick again.")
                return
            await callback.answer("Sending link…" if mode == "l" else "Downloading…")
            await _deliver(callback, user_id, store, book, mode, sdata)
            return
        if data.startswith("dlb:"):
            # post-delivery navigation: back to the same results, or search more
            state, sdata = store.get_session(user_id)
            results = sdata.get("results") if isinstance(sdata, dict) else None
            token = sdata.get("search_token") if isinstance(sdata, dict) else None
            action = data[4:]
            if action == "more":
                store.clear_session(user_id)
                store.set_session(user_id, "MENU", {})
                menu = home_menu()
                await callback.answer("")
                await callback.edit_message_text(menu["text"],
                                                 reply_markup=menu["reply_markup"])
                return
            # back to results
            if state != "CHOOSE_DELIVERY" or not (isinstance(results, list)
                                                  and results and token):
                await callback.answer("No results to go back to.", show_alert=True)
                return
            store.set_session(user_id, "SELECTING_BOOK",
                              {"results": results, "search_token": token,
                               "current_page": 0,
                               "search_query": sdata.get("search_query", "")})
            await callback.answer("")
            await callback.edit_message_text(
                "📚 Pick another from the same results, or use the buttons "
                "below:",
                reply_markup=build_search_keyboard(results, 0, token))
            return
        if data.startswith("mql5:"):
            # trending listing request: "mql5:mt5:ea" | "mql5:mt5:ind" | ...
            if data == "mql5:menu":
                menu = mql5_menu()
                await callback.edit_message_text(menu["text"],
                                                 reply_markup=menu["reply_markup"])
                return
            parts = data.split(":")
            key = ":".join(parts[1:])
            if key not in _MQL5_LOOKUP:
                await callback.answer("Unknown MQL5 listing.", show_alert=True)
                return
            market, kind = _MQL5_LOOKUP[key]
            await callback.answer("📡 Loading MQL5 trending…")
            try:
                items = await asyncio.to_thread(scrape_trending, market, kind)
            except Exception:
                await callback.edit_message_text(
                    "⚠️ Couldn't load the MQL5 Code Base right now "
                    "(site busy or layout changed). Try again in a minute.")
                return
            store.set_session(user_id, "MQL5_LISTING",
                              {"market": market, "kind": kind,
                               "items": items, "page": 0})
            page_msg = mql5_paged_message(items, 0)
            await callback.edit_message_text(page_msg["text"],
                                             reply_markup=page_msg["reply_markup"])
            return
        if data.startswith("mql5s:"):
            # page navigation within a stored MQL5 listing
            state, sdata = store.get_session(user_id)
            if state != "MQL5_LISTING" or not isinstance(sdata.get("items"), list):
                await callback.answer("This listing has expired.", show_alert=True)
                return
            try:
                page = int(data[6:])
                msg = mql5_paged_message(sdata["items"], page)
            except ValueError:
                await callback.answer("Bad page.", show_alert=True)
                return
            sdata["page"] = page
            store.set_session(user_id, state, sdata)
            await callback.answer("")
            await callback.edit_message_text(msg["text"], reply_markup=msg["reply_markup"])
            return
        if data.startswith("dlm:"):
            # send one item's file from the stored listing
            state, sdata = store.get_session(user_id)
            items = sdata.get("items") if isinstance(sdata, dict) else None
            if state != "MQL5_LISTING" or not isinstance(items, list):
                await callback.answer("This listing has expired.", show_alert=True)
                return
            try:
                item = mql5_item_by_index(items, data[4:])
            except ValueError as err:
                await callback.answer(str(err), show_alert=True)
                return
            message = callback.message
            token = os.getenv("TELEGRAM_BOT_TOKEN", "")
            chat_id = str(os.getenv("TELEGRAM_DELIVERY_CHAT_ID") or user_id)
            await callback.answer("⏳ Downloading…")
            try:
                kind, url, size = await asyncio.to_thread(
                    mql5_deliver_file, token, chat_id, item,
                    session=requests)
            except Exception:
                if message is not None:
                    await message.reply_text(
                        "⚠️ Download failed — item page link instead:\n" + item["url"])
                return
            if message is not None:
                await message.reply_text(
                    "✅ Sent " + item["title"][:80] + " (" + kind + ", "
                    + str(round(size / 1024)) + " KB)\n" + item["url"])
            return
        if data.startswith("auto:"):
            action = data[5:]
            if action == "menu":
                menu = auto_menu()
                await callback.edit_message_text(menu["text"],
                                                 reply_markup=menu["reply_markup"])
                return
            if action == "trend":
                await callback.answer("🔥 Loading GitHub trending…")
                try:
                    items = await asyncio.to_thread(trending_repos)
                except Exception:
                    await callback.edit_message_text(
                        "⚠️ Couldn't load GitHub trending right now "
                        "(site busy or layout changed). Try again in a minute.")
                    return
                store.set_session(user_id, "AUTO_LISTING", {"items": items})
                rows = [[{"text": it["title"][:60],
                          "callback_data": "autl:" + str(i)}]
                        for i, it in enumerate(items[:5])]
                rows.append([{"text": "🏠 Home", "callback_data": "ui:home"}])
                await callback.edit_message_text(
                    "🔥 Trending on GitHub right now — tap a repo to get "
                    "the source zip (link-only if >20 MB):",
                    reply_markup={"inline_keyboard": rows})
                return
            if action.startswith("tool:"):
                key = action[5:]
                label, full = _TOOL_LOOKUP.get(key, (None, None))
                if full is None:
                    await callback.answer("Unknown tool.", show_alert=True)
                    return
                await _send_repo_zip(update, user_id, store, {
                    "id": full, "title": label,
                    "url": "https://github.com/" + full})
                return
        if data.startswith("autl:"):
            state, sdata = store.get_session(user_id)
            items = sdata.get("items") if isinstance(sdata, dict) else None
            if state != "AUTO_LISTING" or not isinstance(items, list):
                await callback.answer("This listing has expired.", show_alert=True)
                return
            try:
                index = int(data[5:])
                if index < 0 or index >= len(items):
                    raise ValueError("bad index")
            except ValueError:
                await callback.answer("Bad item.", show_alert=True)
                return
            await _send_repo_zip(update, user_id, store, items[index])
            return
        if data.startswith("pf:"):
            action = data[3:]
            if action == "menu":
                menu = forge_menu()
                await callback.edit_message_text(menu["text"],
                                                 reply_markup=menu["reply_markup"])
                return
            if action.startswith("cap:"):
                key = action.split(":", 1)[1]
                store.set_session(user_id, "FORGE_TOPIC", {"cap": key})
                await callback.answer("")
                await callback.edit_message_text(
                    "🪄 Now describe the task you want this prompt to do "
                    "(optionally add context on a 2nd line after a blank "
                    "line). I'll forge a strong, evidence-first prompt.\n\n"
                    "❌ Cancel to back out.")
                return
        if data.startswith("fae:"):
            # "Show all ebooks" from a Find ALL result -> standard book list
            state, sdata = store.get_session(user_id)
            if state != "FIND_RESULT":
                await callback.answer("This selection has expired.", show_alert=True)
                return
            token = data[4:]
            if sdata.get("fa_token") != token:
                await callback.answer("This selection has expired.", show_alert=True)
                return
            result = sdata.get("result") or {}
            books = result.get("ebooks") or []
            if not books:
                await callback.answer("No ebooks in this result.", show_alert=True)
                return
            btoken = secrets.token_hex(6)
            store.set_session(user_id, "SELECTING_BOOK",
                              new_search_session(result.get("topic", ""), books,
                                                 btoken))
            await callback.answer("")
            await callback.edit_message_text(
                "📚 " + str(len(books)) + " open-licensed ebook(s) for “"
                + str(result.get("topic", ""))[:60] + "” — pick one:",
                reply_markup=build_search_keyboard(books, 0, btoken))
            return
        if data.startswith("fap:"):
            # send one app's repo zip from a Find ALL result
            state, sdata = store.get_session(user_id)
            if state != "FIND_RESULT":
                await callback.answer("This selection has expired.", show_alert=True)
                return
            parts = data.split(":")
            if len(parts) != 3 or sdata.get("fa_token") != parts[1]:
                await callback.answer("Bad item.", show_alert=True)
                return
            try:
                index = int(parts[2])
            except ValueError:
                await callback.answer("Bad item.", show_alert=True)
                return
            apps = (sdata.get("result") or {}).get("apps") or []
            if index < 0 or index >= len(apps):
                await callback.answer("Bad item.", show_alert=True)
                return
            await _send_repo_zip(update, user_id, store, apps[index])
            return
        if data.startswith("fa:"):
            action = data[3:]
            if action == "menu":
                menu = find_menu()
                await callback.edit_message_text(menu["text"],
                                                 reply_markup=menu["reply_markup"])
                return
            if action.startswith("run"):
                key = None
                if ":" in action:
                    key = action.split(":", 1)[1]
                    if key not in _TOPIC_LOOKUP:
                        await callback.answer("Unknown topic.", show_alert=True)
                        return
                await callback.answer("⏳ Finding ALL…")
                await _run_find_all(callback.message, user_id, store,
                                    search_provider, key=key)
                return
        if data.startswith("ui:"):
            action = data[3:]
            if action in ("home", "menu"):
                store.set_session(user_id, "MENU", {})
                menu = home_menu()
                await callback.edit_message_text(menu["text"],
                                                 reply_markup=menu["reply_markup"])
                return
            if action == "help":
                await callback.edit_message_text(HELP_TEXT)
                return
            if action == "agent":
                try:
                    await callback.edit_message_text(agent_skills().summary_text())
                except Exception:
                    await callback.edit_message_text("🧠 Agent view unavailable.")
                return
            if action == "cancel":
                store.clear_session(user_id)
                await callback.edit_message_text("Cancelled.")
                return
            if action.startswith("cat:"):
                topic = category_topic(action[4:])
                if topic is None:
                    await callback.answer("Unknown category.", show_alert=True)
                    return
                await callback.answer("🔎 Searching " + topic + "…")
                await _search_and_present(callback.message, user_id, topic,
                                          store, search_provider)
                return
        if data.startswith("termux:"):
            action = data[7:]
            if action == "menu":
                menu = termux_menu()
                await callback.edit_message_text(menu["text"],
                                                 reply_markup=menu["reply_markup"])
                return
            if action == "pkg":
                await callback.edit_message_text(
                    "⚙️ Termux packages (type these in Termux):\n"
                    "pkg update\n"
                    "pkg install python nodejs git openjdk-17\n"
                    "pkg install uiautomator2 scrcpy adb\n"
                    "pkg install termux-api  (termux-notification, "
                    "termux-tts-speak, termux-battery-status…)\n"
                    "pkg install termux-x11  (GUI apps)\n\n"
                    "Chat-automation starter:\n"
                    "pip install uiautomator2\n"
                    "adb connect <phone-ip>:5555   (over Wi-Fi)\n"
                    "python -m uiautomator2 init   (installs atx agent)\n\n"
                    "Then run your own scripts from here — tap “💬 Chat "
                    "& UI Automation” for the tools to install.",
                    reply_markup={"inline_keyboard": [
                        [{"text": "💬 Chat & UI Automation (tools)",
                          "callback_data": "fa:run:termux"}],
                        [{"text": "📱 Termux menu",
                          "callback_data": "termux:menu"}],
                        [{"text": "🏠 Home", "callback_data": "ui:home"}]]})
                return
            if action == "books":
                await callback.answer("🔎 Searching termux / chat-automation "
                                      "books…")
                await _search_and_present(callback.message, user_id,
                                          "termux android automation",
                                          store, search_provider)
                return
            if action in _TERMUX_RE_INFO:
                info = _TERMUX_RE_INFO[action]
                await callback.edit_message_text(
                    info + "\n\n🔬 Related: tap “Termux RE” for the full "
                    "tool list (Ghidra, jadx, apktool, radare2, Frida).",
                    reply_markup={"inline_keyboard": [
                        [{"text": "🔬 Termux RE (tools)",
                          "callback_data": "fa:run:termuxre"}],
                        [{"text": "📱 Termux menu",
                          "callback_data": "termux:menu"}],
                        [{"text": "🏠 Home", "callback_data": "ui:home"}]]})
                return
            await callback.answer("Unknown termux action.", show_alert=True)
            return

    # ---- messages -------------------------------------------------------
    message = getattr(update, "message", None)
    if message is None or not isinstance(getattr(message, "text", None), str):
        return
    text = message.text.strip()
    if not text:
        return

    state, _sdata = store.get_session(user_id)

    # ---- bot commands (bottom-left ⋮ menu) --------------------------------
    # Anything listed in BOT_COMMANDS is dispatched here; the LLM never sees
    # it. /status and /backup are served by main.py's CommandHandlers
    # (admin-only diagnostics) and don't reach the router.
    if text.startswith("/"):
        first = text.split()[0] if text.split() else ""
        name = first[1:].split("@")[0].lower()  # strip "/" and "@botname"
        action = command_action(name)
        if action is not None:
            if state in ("SELECTING_BOOK", "CHOOSE_DELIVERY",
                         "MQL5_LISTING", "AUTO_LISTING", "FIND_TOPIC",
                         "FIND_RESULT", "FORGE_TOPIC"):
                store.clear_session(user_id)
            await _run_command(action, user_id, store, message,
                               search_provider)
            return

    if text in ("/start", "/menu", "/home"):
        store.set_session(user_id, "MENU", {})
        menu = home_menu()
        await message.reply_text(menu["text"], reply_markup=menu["reply_markup"])
        return
    if text == "/cancel":
        store.clear_session(user_id)
        await message.reply_text("Cancelled.")
        return
    if text == "/help":
        await message.reply_text(HELP_TEXT)
        return

    # Prompt Forge: a typed goal answers the pending "describe the task" prompt
    if state == "FORGE_TOPIC":
        if text in ("/cancel", "cancel", "Cancel"):
            store.clear_session(user_id)
            await message.reply_text("Cancelled.")
            return
        parts = text.split("\n\n", 1)
        goal = parts[0].strip()
        context = parts[1].strip() if len(parts) > 1 else ""
        if not goal:
            await message.reply_text("Describe the task first — e.g. "
                                     "\"build a daily report from my market "
                                     "data\".")
            return
        cap = (_sdata.get("cap") if isinstance(_sdata, dict) else None) or "general"
        await message.reply_text("🪄 Forging a strong prompt… (a moment)")
        result = await asyncio.to_thread(forge_prompt, cap, goal, context)
        if result is None:
            store.clear_session(user_id)
            await message.reply_text("Couldn't forge that — check the task "
                                     "and try again.")
            return
        # Built-in agent: studying the domain of a prompt is study too.
        try:
            gained, level = agent_skills().record_search(
                "prompt:" + result["capability"], 1, source="prompt")
        except Exception:
            gained, level = 0, 1
        store.clear_session(user_id)
        await _reply_long(message, prompt_text(result),
                          disable_web_page_preview=True)
        await message.reply_text("🧠 +" + str(gained) + " XP → L" + str(level))
        return

    # Find ALL: a typed topic answers the pending "What topic?" prompt
    if state == "FIND_TOPIC":
        if text in ("/cancel", "cancel", "Cancel"):
            store.clear_session(user_id)
            await message.reply_text("Cancelled.")
            return
        topic = _clean_query(text)
        if not topic:
            await message.reply_text("What topic should I search for? "
                                     "e.g. \"quantum computing\"")
            return
        await _run_find_all(message, user_id, store, search_provider,
                            topic=topic)
        return

    # mid-flow plain text starts a new action
    if state in ("SELECTING_BOOK", "CHOOSE_DELIVERY"):
        store.clear_session(user_id)

    # classify the message (LLM); fall back to raw-topic search
    intent_result = await asyncio.to_thread(ask_intent, text)
    if intent_result is None:
        intent_result = {"intent": "search", "topic": _clean_query(text)}
    action = intent_result["intent"]
    if action == "search":
        topic = (intent_result.get("topic") or _clean_query(text))
        if not topic:
            await message.reply_text("What topic should I search for? "
                                     "e.g. \"quantum computing\"")
            return
        await _search_and_present(message, user_id, topic, store, search_provider)
        return
    await _run_action(action, user_id, store, message, intent_result, text)
