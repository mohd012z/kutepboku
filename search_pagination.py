"""Session-aware Telegram inline keyboard pagination (framework-neutral)."""
import math
import copy
import re

ITEMS_PER_PAGE = 3
MAX_RESULTS = 100
SEARCH_STATE = "SELECTING_BOOK"
TOKEN = re.compile(r"^[a-f0-9]{12}$")
BOOK_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def build_search_keyboard(results, page_index, session_token):
    """Return Telegram Bot API reply_markup JSON for one result page.

    The caller must verify user ownership, FSM state and token before handling clicks.
    """
    if not TOKEN.fullmatch(session_token):
        raise ValueError("Invalid session token")
    if not isinstance(results, list) or len(results) > MAX_RESULTS:
        raise ValueError("Invalid result list")
    pages = max(1, math.ceil(len(results) / ITEMS_PER_PAGE))
    if type(page_index) is not int or not 0 <= page_index < pages:
        raise ValueError("Page out of range")
    start = page_index * ITEMS_PER_PAGE
    keyboard = []
    for book in results[start:start + ITEMS_PER_PAGE]:
        book_id = str(book["id"])
        if not BOOK_ID.fullmatch(book_id):
            raise ValueError("Invalid book ID")
        keyboard.append([{"text": str(book["title"])[:60],
                          "callback_data": f"sr:b:{session_token}:{book_id}"}])
    nav = []
    if page_index:
        nav.append({"text": "⬅️ Previous",
                    "callback_data": f"sr:p:{session_token}:{page_index - 1}"})
    if page_index + 1 < pages:
        nav.append({"text": "Next ➡️",
                    "callback_data": f"sr:p:{session_token}:{page_index + 1}"})
    if nav:
        keyboard.append(nav)
    keyboard.append([{"text": "❌ Cancel", "callback_data": f"sr:c:{session_token}"}])
    return {"inline_keyboard": keyboard}


def process_search_callback(user_id, callback_data, *, load_session, save_session, clear_session, compare_and_set=None):
    """Validate a callback against a persisted session, then return a UI action.

    load_session(user_id) -> (state, data), save_session(user_id, state, data).
    A deployment must serialize concurrent updates per user or use compare-and-swap
    state versions to prevent lost updates.
    """
    if not isinstance(callback_data, str) or len(callback_data.encode("utf-8")) > 64:
        return {"ok": False, "error": "Invalid callback"}
    parts = callback_data.split(":")
    if len(parts) not in (3, 4) or parts[:1] != ["sr"] or parts[1] not in ("p", "b", "c"):
        return {"ok": False, "error": "Invalid callback"}
    action, token = parts[1:3]
    if not TOKEN.fullmatch(token) or (action == "c") != (len(parts) == 3):
        return {"ok": False, "error": "Invalid callback"}
    state, data = load_session(user_id)
    if state != SEARCH_STATE or data.get("search_token") != token:
        return {"ok": False, "error": "This search has expired. Start a new search."}
    original_data = copy.deepcopy(data)
    results = data.get("results", [])
    if not isinstance(results, list) or len(results) > MAX_RESULTS:
        return {"ok": False, "error": "Invalid search results"}
    if action == "c":
        if compare_and_set is not None:
            if not compare_and_set(user_id, SEARCH_STATE, original_data, "IDLE", {}):
                return {"ok": False, "error": "Search changed. Please retry."}
        else:
            clear_session(user_id)
        return {"ok": True, "action": "cancel"}
    if len(parts) != 4:
        return {"ok": False, "error": "Invalid callback"}
    if action == "p":
        if not re.fullmatch(r"0|[1-9][0-9]{0,2}", parts[3]):
            return {"ok": False, "error": "Invalid page"}
        page = int(parts[3])
        total = max(1, math.ceil(len(results) / ITEMS_PER_PAGE))
        if page >= total:
            return {"ok": False, "error": "Page out of range"}
        data["current_page"] = page
        if compare_and_set is not None:
            if not compare_and_set(user_id, SEARCH_STATE, original_data, SEARCH_STATE, data):
                return {"ok": False, "error": "Search changed. Please retry."}
        else:
            save_session(user_id, SEARCH_STATE, data)
        return {"ok": True, "action": "page", "page": page,
                "pages": total, "keyboard": build_search_keyboard(results, page, token)}
    if not BOOK_ID.fullmatch(parts[3]):
        return {"ok": False, "error": "Invalid book"}
    current_page = data.get("current_page", 0)
    if type(current_page) is not int or current_page < 0:
        return {"ok": False, "error": "Invalid session page"}
    visible = results[current_page * ITEMS_PER_PAGE:(current_page + 1) * ITEMS_PER_PAGE]
    book = next((b for b in visible if b.get("id") == parts[3]), None)
    if not book:
        return {"ok": False, "error": "Book not on current page"}
    data["selected_book"] = book
    if compare_and_set is not None:
        if not compare_and_set(user_id, SEARCH_STATE, original_data, "CHOOSE_DELIVERY", data):
            return {"ok": False, "error": "Search changed. Please retry."}
    else:
        save_session(user_id, "CHOOSE_DELIVERY", data)
    return {"ok": True, "action": "selected", "book": book}


def new_search_session(query, results, token):
    """Prepare session data; token should be secrets.token_hex(6)."""
    if not TOKEN.fullmatch(token) or not isinstance(results, list) or len(results) > MAX_RESULTS:
        raise ValueError("Invalid search session")
    return {"search_query": query[:200], "results": results,
            "current_page": 0, "search_token": token}
