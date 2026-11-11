"""Prompt Forge: build strong, evidence-first prompts for ANY AI assistant.

The user picks a capability domain, describes their goal (and optional
context), and Minda writes a structured, ready-to-paste prompt:
ROLE / TASK / CONTEXT / METHOD / EVIDENCE RULES / OUTPUT FORMAT / QUALITY
GATES. The evidence rules are the core strength: cite sources, mark each
claim FACT / INFERENCE / ASSUMPTION / UNKNOWN, show the work, never fabricate.

Fail-open design: when the LLM is unavailable the bot falls back to a
deterministic template (same section structure, domain evidence rules) and
labels it "template mode" — a forge is a forge either way.
"""
import json
import os
import re

import requests

MAX_GOAL = 800
MAX_CONTEXT = 1200

# (key, label, persona, domain-specific evidence emphasis, default output
# format). Keys are short — callback_data must fit 64 bytes.
CAPABILITIES = [
    ("automation", "⚙️ Automation",
     "a senior automation engineer",
     "every step must be reproducible: exact commands, inputs, expected "
     "outputs, and how to verify each stage ran correctly; fail-closed on "
     "errors (report them, never guess past them).",
     "a numbered runbook of exact steps + verification checks, then the "
     "code/config needed"),
    ("research", "🔬 Research",
     "a rigorous research analyst",
     "separate primary sources from secondary; give a source for every "
     "material claim; note date, author and credibility of each source; "
     "flag conflicting evidence explicitly.",
     "a structured brief: findings with citations, confidence per finding, "
     "open questions"),
    ("creator", "✍️ Content Creator",
     "a professional content strategist and writer",
     "ground claims in facts the user provided or well-known public record; "
     "mark invented examples as EXAMPLES; keep the audience and platform "
     "constraints stated up front.",
     "the finished content, plus 2 alternates that differ in tone"),
    ("developer", "💻 Developer",
     "a principal software engineer",
     "show the actual code, not pseudocode; state assumptions about the "
     "environment (language version, platform, dependencies); include how "
     "to test the change and what a correct output looks like.",
     "a working solution with the code, why it works, edge cases, and a "
     "test plan"),
    ("finding", "🔍 Finding & Search",
     "a specialist information finder",
     "report what you actually found with the source/URL/path for each item; "
     "distinguish found (FACT) from inferred; say plainly when something is "
     "UNAVAILABLE rather than filling the gap.",
     "a results table/list: item, source, confidence, notes"),
    ("analysis", "📊 Analysis",
     "a senior analyst",
     "show every calculation; state the data used and its limitations; "
     "separate observation (what the data shows) from interpretation (what "
     "you think it means); give a confidence level per conclusion.",
     "executive summary first, then the full analysis with the work shown"),
    ("data", "📈 Data Science",
     "a senior data scientist",
     "state the dataset/schema you are assuming; show code or formulas; "
     "report sample size and known biases; label results as measured vs "
     "modeled; no invented numbers — if data is missing, say so.",
     "method, code/formulas, results with uncertainty, caveats, next steps"),
    ("photo", "📷 Photo & Image",
     "a professional photographer and image editor",
     "describe concrete, verifiable attributes (light, lens, color, "
     "composition); when generating, list exact style/subject/scene tokens; "
     "when critiquing, tie each point to a visible part of the image.",
     "the prompt/spec or the critique with numbered, location-specific points"),
    ("video", "🎬 Video",
     "a professional video producer and editor",
     "break the video into scenes with timing; give shot type, camera "
     "movement and audio for each scene; keep total duration consistent "
     "with the sum of scenes.",
     "a shot-by-shot plan (scene, duration, shot, audio, on-screen text) "
     "plus the generation prompts"),
    ("general", "🧩 General / Other",
     "an expert consultant in the user's stated field",
     "cite or show the basis for every material claim; mark FACT vs "
     "INFERENCE vs ASSUMPTION; state what would verify the key answers.",
     "a clear, structured answer with the reasoning visible"),
]

_CAP_LOOKUP = {key: (label, persona, evidence, fmt)
               for key, label, persona, evidence, fmt in CAPABILITIES}

_SECTIONS = ("ROLE", "TASK", "CONTEXT", "METHOD", "EVIDENCE RULES",
             "OUTPUT FORMAT", "QUALITY GATES")

_GEN_PROMPT = (
    "You are an expert prompt engineer. Write ONE powerful, ready-to-paste "
    "prompt that the user will give to ANY AI assistant (ChatGPT, Claude, "
    "Gemini, or a local model).\n"
    "Capability domain: {domain}\n"
    "Assign this expert role in the prompt: {persona}\n"
    "The user's goal: {goal}\n"
    "{context_block}"
    "The prompt MUST contain these section headers, in order: "
    "ROLE, TASK, CONTEXT, METHOD, EVIDENCE RULES, OUTPUT FORMAT, "
    "QUALITY GATES.\n"
    "EVIDENCE RULES must be strong and domain-specific; include: cite the "
    "source for every material claim; mark each key claim as FACT, "
    "INFERENCE, ASSUMPTION or UNKNOWN; show the work (steps, calculations, "
    "commands) before the conclusion; never fabricate numbers, citations, "
    "files or results — say UNAVAILABLE when something is missing; end with "
    "a self-check of the evidence rules before answering.\n"
    "Domain-specific emphasis to weave in: {evidence}\n"
    "OUTPUT FORMAT should be: {fmt}\n"
    "Reply with the prompt text ONLY — no preamble, no commentary, no "
    "code fences. Under 900 words."
)


def _llm_forge(domain, persona, goal, context, evidence, fmt, *,
               client=requests, base_url=None, api_key=None, model=None,
               timeout=90):
    base_url = base_url if base_url is not None else os.getenv("MINDA_BASE_URL")
    api_key = api_key if api_key is not None else os.getenv("MINDA_API_KEY")
    model = model if model is not None else os.getenv("MINDA_MODEL",
                                                      "llm_model_fp8")
    if not base_url or not api_key:
        return None
    context_block = ("Additional context the user gave: " + context + "\n"
                     if context else "")
    prompt = _GEN_PROMPT.format(domain=domain, persona=persona, goal=goal,
                                context_block=context_block,
                                evidence=evidence, fmt=fmt)
    # Qwen3: try WITHOUT reasoning first (fast, clean content for prompt
    # writing), then WITH reasoning as a fallback if that yields nothing
    # usable. First non-empty answer wins; any failure -> template.
    for thinking in (False, True):
        try:
            response = client.post(
                base_url.rstrip("/") + "/chat/completions",
                headers={"Authorization": "Bearer " + api_key,
                         "Content-Type": "application/json"},
                json={"model": model, "max_tokens": 1000,
                      "temperature": 0.4,
                      "chat_template_kwargs": {"enable_thinking": thinking},
                      "messages": [{"role": "user", "content": prompt}]},
                timeout=min(timeout, 45))
            response.raise_for_status()
            message = response.json()["choices"][0]["message"]
            raw = re.sub(r"^```(?:[a-z]+)?\s*|\s*```$",
                         "", (message.get("content") or ""), flags=re.S)
            raw = raw.strip()
            if len(raw) >= 80:
                return raw
        except (requests.RequestException, ValueError, KeyError,
                IndexError, TypeError):
            continue
    return None


def _template_forge(domain, persona, goal, context, evidence, fmt):
    """Deterministic fallback — same strong structure, no LLM needed."""
    lines = [
        "ROLE",
        "You are " + persona + " working on a " + domain.lower() + " task. "
        "Be rigorous and evidence-first: show your work and never "
        "fabricate facts, numbers or sources.",
        "",
        "TASK",
        goal,
        "",
        "CONTEXT",
        context if context else "None provided — ask at most 2 clarifying "
        "questions before starting if the task is ambiguous.",
        "",
        "METHOD",
        "1. Restate the goal in one line to confirm understanding.",
        "2. List what you will do, step by step, and do it.",
        "3. For each major step, show the evidence (source, calculation "
        "or output) before drawing a conclusion.",
        "4. Stop and report if a step cannot be verified.",
        "",
        "EVIDENCE RULES",
        "- Cite the source for every material claim.",
        "- Mark each key claim: FACT, INFERENCE, ASSUMPTION or UNKNOWN.",
        "- Show steps/calculations/commands before conclusions.",
        "- If data is missing, write UNAVAILABLE and say what you need.",
        "- Domain rules: " + evidence,
        "",
        "OUTPUT FORMAT",
        fmt + ".",
        "",
        "QUALITY GATES — before answering, self-check:",
        "1. Every material claim has a source or is labeled an assumption.",
        "2. No numbers, citations or results are invented.",
        "3. The work shown actually supports the conclusion.",
        "4. The output matches the requested format.",
    ]
    return "\n".join(lines)


def forge_prompt(cap_key, goal, context="", *, client=requests,
                 base_url=None, api_key=None, model=None, timeout=90):
    """Forge a strong prompt. Returns
    {capability, label, prompt, mode: 'ai'|'template', sections} or None
    when the capability or goal is invalid."""
    cap = _CAP_LOOKUP.get(cap_key)
    goal = (goal or "").strip()
    if cap is None or not goal:
        return None
    _label, persona, evidence, fmt = cap
    context = (context or "").strip()[:MAX_CONTEXT]
    prompt = _llm_forge(_label, persona, goal[:MAX_GOAL], context, evidence,
                        fmt, client=client, base_url=base_url,
                        api_key=api_key, model=model, timeout=timeout)
    if prompt and len(prompt) >= 80:
        mode = "ai"
    else:
        prompt = _template_forge(_label, persona, goal[:MAX_GOAL], context,
                                 evidence, fmt)
        mode = "template"
    sections = [s for s in _SECTIONS if re.search(
        r"^" + s + r"\b", prompt, re.M)]
    return {"capability": cap_key, "label": _label, "prompt": prompt,
            "mode": mode, "sections": len(sections)}


def prompt_text(result):
    """Chat-ready message for a forged prompt."""
    mode = ("AI-crafted" if result["mode"] == "ai"
            else "template mode — AI was unavailable")
    return ("🪄 Your prompt (" + result["label"] + " — " + mode + ")\n\n"
            "Copy & paste this into any AI (ChatGPT, Claude, Gemini, local):\n\n"
            "```\n" + result["prompt"] + "\n```")


def forge_menu():
    text = (
        "🪄 Prompt Forge — strong, evidence-first prompts for ANY AI\n\n"
        "Pick a capability, then describe your task. I craft a "
        "ready-to-paste prompt: expert role, method, hard evidence rules "
        "(cite, label FACT/INFER/ASSUME, show the work, never fabricate), "
        "output format and quality gates.\n\n"
        "Works with ChatGPT, Claude, Gemini or your local models."
    )
    rows, left, right = [], [], []
    for key, label, _p, _e, _f in CAPABILITIES:
        (left if len(left) <= len(right) else right).append(
            {"text": label[:40], "callback_data": "pf:cap:" + key})
        if len(left) == 2 and len(right) == 2:
            rows.append(left + right)
            left, right = [], []
    if left:
        rows.append(left + right)
    rows.append([{"text": "🏠 Home", "callback_data": "ui:home"}])
    return {"text": text, "reply_markup": {"inline_keyboard": rows}}
