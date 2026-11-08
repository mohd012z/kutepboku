"""Staging-only APK research menu: synthetic, no Telegram network or APK access."""
import hashlib
import json
import re

TOPICS = {
    "tools": ("APK Tools Library", "Read-only APK/DEX and archive inspection research"),
    "ads": ("Ad SDK Research", "Advertising SDK evidence and false-positive classification"),
    "security": ("Security Doctor", "Manifest, component and privacy indicators"),
    "sources": ("Repository Inspector", "Source provenance, licenses and release evidence"),
    "reports": ("Research Reports", "SHA-256 evidence and unverified gates"),
    "status": ("Research Status", "Staging-only; no live Telegram delivery"),
}
CALLBACK = re.compile(r"^apk:v1:([a-z]{3,8})$")
MAX_CALLBACK_BYTES = 64

def keyboard():
    return {"inline_keyboard": [
        [{"text": title, "callback_data": "apk:v1:" + key}]
        for key, (title, _) in TOPICS.items()
    ]}

def handle_callback(data, *, user_id, allowed_user_ids):
    if type(user_id) is not int or user_id not in allowed_user_ids:
        return {"ok": False, "error": "Not authorized"}
    if type(data) is not str or len(data.encode("utf-8")) > MAX_CALLBACK_BYTES:
        return {"ok": False, "error": "Invalid callback"}
    match = CALLBACK.fullmatch(data)
    if not match or match.group(1) not in TOPICS:
        return {"ok": False, "error": "Invalid callback"}
    key = match.group(1)
    title, description = TOPICS[key]
    evidence = {"schema": "msa.soup.apk-research.v1", "topic": key,
                "title": title, "description": description,
                "mode": "synthetic_offline", "delivery": "disabled",
                "verification": "research_only"}
    evidence["sha256"] = hashlib.sha256(json.dumps(
        evidence, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return {"ok": True, "text": title + "\n" + description +
            "\nResearch preview only. No APK processing or live delivery.",
            "evidence": evidence}
