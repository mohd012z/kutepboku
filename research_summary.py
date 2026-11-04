"""Research digest: one LLM pass over the collected global-source list.

Fail-open by design — any LLM/network failure returns None and the research
view still shows the raw (verified) sources. The model only ever receives
title + description text from public package/repo registries, never user
session data.
"""
import json
import os
import re

import requests

_RESEARCH_PROMPT = (
    "You are a research assistant compiling a field digest for Telegram. "
    "Using ONLY the numbered source list below (real packages/repos/images), "
    "write a concise digest about the topic.\n"
    "Format, plain text (no markdown headings):\n"
    "OVERVIEW: 3-5 short bullets on what the topic is and where the field "
    "is now.\n"
    "KEY RESOURCES: pick at most 5 from the list, each 'name — why it "
    "matters' (one line).\n"
    "NOTES: one line — a caveat, gap, or what is missing from this list.\n"
    "Keep it under 900 characters total. If the list is empty, write "
    "OVERVIEW: No sources were found in the public registries just now.\n\n"
    "TOPIC: "
)

# (label, max items quoted into the prompt)
_QUOTA = 40


def build_source_lines(apps, sources, limit=_QUOTA):
    """Flatten apps (GitHub/curated) + global sources into numbered lines
    'i. [src] name — desc'. apps entries are GitHub; sources entries carry
    their own source key."""
    lines = []
    for a in apps or []:
        src = "GitHub"
        if a.get("source"):
            src = a["source"]
        lines.append("[%s] %s — %s" % (src, a.get("id", ""),
                                       (a.get("desc") or a.get("title") or "")[:90]))
    for key, items in (sources or {}).items():
        for it in items:
            lines.append("[%s] %s — %s" % (key, it.get("id", ""),
                                           (it.get("desc") or "")[:90]))
    return lines[:limit]


def deterministic_digest(topic, apps, sources):
    """Worker-style field summary built ONLY from the verified source list —
    no LLM required (the agent runs without any external AI service)."""
    all_items = []
    for a in apps or []:
        all_items.append(("GitHub" if not a.get("source") else a["source"],
                          a.get("id", ""), a.get("desc") or a.get("title") or "",
                          int(a.get("stars") or a.get("count") or 0)))
    for key, items in (sources or {}).items():
        for it in items:
            all_items.append((key, it.get("id", ""), it.get("desc") or "",
                              int(it.get("count") or 0)))
    n = len(all_items)
    if not n:
        return ("OVERVIEW: No sources were found in the public registries "
                "just now.\nNOTES: The subject may be too narrow, or a "
                "registry was rate-limited.")
    keys = []
    for key, _id, _desc, _c in all_items:
        if key not in keys:
            keys.append(key)
    top = sorted(all_items, key=lambda t: -t[3])[:5]
    lines = ["OVERVIEW:"]
    lines.append("- Verified sources: %d across %d registries (%s)."
                 % (n, len(keys), ", ".join(keys)))
    if top and top[0][3]:
        lines.append("- Most-used in the field: %s (%s, %d popularity)."
                     % (top[0][1], top[0][0], top[0][3]))
    lines.append("- Descriptions below are the registries' own; verify "
                 "before adopting.")
    lines.append("")
    lines.append("KEY RESOURCES:")
    for key, ident, desc, _c in top:
        lines.append("- %s [%s] — %s" % (ident, key, (desc or "no description")[:90]))
    lines.append("")
    lines.append("NOTES: Deterministic agent digest (no external AI service); "
                 "counts are registry popularity, not endorsements.")
    return "\n".join(lines)[:1200]


def research_summary(topic, apps, sources, *, client=requests, base_url=None,
                     api_key=None, model=None, timeout=40):
    """One digest call. Returns a string or None (fail-open)."""
    base_url = base_url if base_url is not None else os.getenv("MINDA_BASE_URL")
    api_key = api_key if api_key is not None else os.getenv("MINDA_API_KEY")
    model = model if model is not None else os.getenv("MINDA_MODEL", "llm_model_fp8")
    if not base_url or not api_key:
        return None
    lines = build_source_lines(apps, sources)
    body = _RESEARCH_PROMPT + str(topic)[:120] + "\nSOURCES:\n"
    body += "\n".join("%d. %s" % (i + 1, ln) for i, ln in enumerate(lines))
    try:
        response = client.post(
            base_url.rstrip("/") + "/chat/completions",
            headers={"Authorization": "Bearer " + api_key,
                     "Content-Type": "application/json"},
            json={"model": model, "temperature": 0.4, "max_tokens": 700,
                  "chat_template_kwargs": {"enable_thinking": False},
                  "messages": [{"role": "user", "content": body}]},
            timeout=timeout)
        response.raise_for_status()
        raw = response.json()["choices"][0]["message"]["content"].strip()
        raw = re.sub(r"^```(?:text|md)?\s*|\s*```$", "", raw, flags=re.S).strip()
        return raw or None
    except Exception:
        return None


if __name__ == "__main__":
    import sys
    print(json.dumps({"topic": sys.argv[1] if len(sys.argv) > 1 else "ml"},
                     indent=2))
