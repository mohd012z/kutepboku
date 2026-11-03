"""Read-only Telegram webhook ownership diagnosis. Never prints bot tokens."""
import json
import os
import sys
import urllib.request
import urllib.error

EXPECTED_USERNAME = "mysoupsearchbot"
EXPECTED_WEBHOOK = "https://msasoup-telegram.ifxhelper.workers.dev/telegram"

def call(method, token):
    req = urllib.request.Request(
        "https://api.telegram.org/bot" + token + "/" + method,
        headers={"User-Agent": "msasoup-diagnostics/1"},
    )
    try:
        with urllib.request.urlopen(req, timeout=12) as response:
            payload = json.loads(response.read(32768))
    except (urllib.error.URLError, TimeoutError, ValueError):
        return None
    return payload.get("result") if payload.get("ok") is True else None

def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        print("UNVERIFIED: TELEGRAM_BOT_TOKEN secret is absent")
        return 2
    me = call("getMe", token)
    if not isinstance(me, dict):
        print("UNVERIFIED: getMe request failed or Telegram rejected the credential")
        return 2
    identity_matches = me.get("username", "").casefold() == EXPECTED_USERNAME
    print("Identity:", "PASS" if identity_matches else "FAIL")
    print("Bot username:", me.get("username", "<missing>"))
    if not identity_matches:
        print("STOP: bot identity does not match the intended MSASoup bot")
        return 1
    webhook = call("getWebhookInfo", token)
    if not isinstance(webhook, dict):
        print("UNVERIFIED: getWebhookInfo request failed")
        return 2
    url = webhook.get("url", "")
    print("Webhook ownership:", "PASS" if url == EXPECTED_WEBHOOK else "FAIL")
    print("Webhook destination:", url or "<not set>")
    print("Pending update count:", webhook.get("pending_update_count", "<unknown>"))
    print("Last delivery error date:", webhook.get("last_error_date", "<none>"))
    print("Last delivery error message:", str(webhook.get("last_error_message", "<none>"))[:500])
    print("Allowed update types:", webhook.get("allowed_updates", "<default>"))
    if url != EXPECTED_WEBHOOK:
        print("STOP: inspect existing polling/webhook owner before changing any registration")
        return 1
    print("Routing metadata PASS; a real /menu reply is still required to prove delivery.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
