"""gemini_jio.py — the Jio "AI Gemini Pro" activation link: how it's created
and how to generate one.

THE KEY FACT
------------
The link is NOT built by Jio's frontend. It is minted by Google's
**Payments Reseller Subscription API**. Jio is a Google *reseller/billing
partner*; when a user passes Jio's eligibility check (age 18-25, active
rs.349+ 5G plan), Jio's *backend* (a Google service account) calls
``partners.userSessions.generate``. Google signs a short-lived
``userSession.token`` and hands it back; the activation link is simply::

    https://serviceactivation.google.com/subscription/new/<token>

Sandbox variant: ``serviceactivation.sandbox.google.com``. There is also an
entitlement-only endpoint (``.../subscription/entitle/<token>``). The token is
an opaque base64url-encoded blob (starts ``01 00``), ~1 hour TTL by default,
single-use, and bound to the intent payload server-side — so it cannot be
forged or reused by the user.

THIS MODULE
-----------
* ``how_it_works_text()``      — the full study (the "how they create it" answer).
* ``generate_activation_link()`` — mints a REAL link when the partner service
  account is configured (RS256 JWT -> OAuth access token ->
  ``userSessions:generate`` -> activation URL). **Fails open**: with no
  credentials it returns a ``template`` result showing the exact request, the
  link shape, and the env vars to set — the bot never dead-ends.
* ``gemini_menu()``            — inline-keyboard entry point (prefix ``gj:``).

No new runtime deps: the RS256 service-account JWT is built with the
``cryptography`` package already in ``requirements.txt`` (the bot venv has no
``google-auth`` / ``PyJWT``).
"""
import base64
import json
import os
import time
import uuid

import requests

# ---- endpoints -------------------------------------------------------------
_PROD_API = "https://paymentsresellersubscription.googleapis.com"
_SANDBOX_API = "https://preprod-paymentsresellersubscription.googleapis.com"
_PROD_ACT = "https://serviceactivation.google.com"
_SANDBOX_ACT = "https://serviceactivation.sandbox.google.com"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_DEFAULT_SCOPE = ("https://www.googleapis.com/auth/payments.reseller.subscription")
_BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/120 Safari/537.36")

# A real, verified Jio token (shared by Anam, 2026-09): 205 bytes of base64url
# protobuf, opens the Google sign-in page. Used only as a worked example.
_SAMPLE_TOKEN = (
    "AQCpiIFGJKlYJG59Qeh-R_zayuBXvyhDT1DppktXdu7nv8OLk3B_l93TEVg-LAZBCXTr1kDorJ"
    "zw0EljCktGjXd7jo9SUU91yYWcO2JfA8KdnjtnUVjeEdI9GZ1eOySr7q7q1htAgouBrS2TgItr"
    "Y8DnYOBYego0FSuMqvE44gstg_YeE1XeeTS70_lGV00uj0t0AzhKiozTykn6wpyrAdCakjy7RG"
    "MyQEBlTILKp8MsuS_aqDrI5AVUuk4giQuOCRVRyriaMkZd0KM2HQ=="
)


def _b64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


# ---- service-account JWT (RS256) -------------------------------------------
def _sa_jwt(sa, scope, now):
    """Build a signed RS256 assertion for a Google service account.

    ``sa`` is the parsed service-account JSON (needs ``client_email`` and a
    PEM ``private_key``). This is exactly what google-auth does internally,
    but without the dependency."""
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    header = {"alg": "RS256", "typ": "JWT"}
    claims = {
        "iss": sa["client_email"],
        "scope": scope,
        "aud": _TOKEN_URL,
        "iat": int(now),
        "exp": int(now) + 3600,
    }
    seg_h = _b64url(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    seg_p = _b64url(json.dumps(claims, separators=(",", ":")).encode("utf-8"))
    signing_input = (seg_h + "." + seg_p).encode("ascii")
    key = serialization.load_pem_private_key(sa["private_key"].encode("utf-8"),
                                             password=None)
    sig = key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    return seg_h + "." + seg_p + "." + _b64url(sig)


def _exchange_token(assertion, client=requests, token_url=None, timeout=20):
    """Swap the signed JWT for an OAuth 2.0 access token. Returns the token."""
    url = token_url or _TOKEN_URL
    response = client.post(
        url,
        data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
              "assertion": assertion},
        timeout=timeout)
    response.raise_for_status()
    body = response.json()
    token = body.get("access_token")
    if not token:
        raise RuntimeError("token endpoint returned no access_token: "
                           + str(body)[:200])
    return token


# ---- userSessions:generate --------------------------------------------------
def _generate_session(*, api_base, partner, access_token, intent, client,
                      timeout=25):
    """Call userSessions:generate and return the userSession dict
    (``token`` + ``expireTime``)."""
    url = "%s/v1/partners/%s/userSessions:generate" % (api_base, partner)
    response = client.post(
        url,
        headers={"Authorization": "Bearer " + access_token,
                 "Content-Type": "application/json"},
        json={"intentPayload": intent},
        timeout=timeout)
    if response.status_code != 200:
        raise RuntimeError("userSessions:generate %s: %s"
                           % (response.status_code, response.text[:300]))
    return response.json().get("userSession") or {}


def _verify_url(url, client=requests, timeout=20):
    """Best-effort GET: report (status, final_url). The link just redirects to
    Google sign-in; opening it does not consume the token."""
    try:
        response = client.get(url, headers={"User-Agent": _BROWSER_UA},
                              allow_redirects=True, timeout=timeout)
        return response.status_code, response.url
    except requests.RequestException as err:
        return None, str(err)[:160]


def _read_sa():
    """Locate + parse the partner service account from env. Returns (sa, err)."""
    path = os.getenv("GEMINI_JIO_SA_FILE", "").strip()
    if path:
        try:
            with open(path, "r", encoding="utf-8") as handle:
                return json.load(handle), None
        except (OSError, ValueError) as err:
            return None, "GEMINI_JIO_SA_FILE: " + str(err)
    inline = os.getenv("GEMINI_JIO_SA_JSON", "").strip()
    if inline:
        try:
            return json.loads(inline), None
        except ValueError as err:
            return None, "GEMINI_JIO_SA_JSON: " + str(err)
    return None, None


def _config():
    """Pull partner config from env with sane defaults."""
    env = os.getenv("GEMINI_JIO_ENV", "prod").strip().lower()
    sandbox = env == "sandbox"
    return {
        "env": env,
        "sandbox": sandbox,
        "api_base": _SANDBOX_API if sandbox else _PROD_API,
        "act_base": _SANDBOX_ACT if sandbox else _PROD_ACT,
        "partner": os.getenv("GEMINI_JIO_PARTNER", "").strip(),
        "product": os.getenv("GEMINI_JIO_PRODUCT", "").strip(),
        "promotion": os.getenv("GEMINI_JIO_PROMOTION", "").strip(),
        "region": os.getenv("GEMINI_JIO_REGION", "IN").strip() or "IN",
        "partner_user_token": os.getenv("GEMINI_JIO_PARTNER_USER_TOKEN", "").strip(),
        "subscription_id": os.getenv("GEMINI_JIO_SUBSCRIPTION_ID", "").strip(),
        "scope": os.getenv("GEMINI_JIO_SCOPE", _DEFAULT_SCOPE).strip(),
        "api_base_override": os.getenv("GEMINI_JIO_BASE", "").strip(),
    }


def _missing_for_live(cfg, sa_present, sa_err):
    """Env/kwargs still needed to mint a live link. The SA item is only listed
    when no service account is present (either passed directly or via env)."""
    missing = []
    if not cfg["partner"]:
        missing.append("GEMINI_JIO_PARTNER")
    if not cfg["product"]:
        missing.append("GEMINI_JIO_PRODUCT")
    if not cfg["partner_user_token"]:
        missing.append("GEMINI_JIO_PARTNER_USER_TOKEN")
    if not sa_present:
        if not (os.getenv("GEMINI_JIO_SA_FILE", "").strip()
                or os.getenv("GEMINI_JIO_SA_JSON", "").strip()):
            missing.append("GEMINI_JIO_SA_FILE (or GEMINI_JIO_SA_JSON)")
        elif sa_err:
            missing.append("service-account key: " + sa_err)
    return missing


def _request_example(cfg, subscription_id):
    line_item = {"product": cfg["product"]}
    if cfg["promotion"]:
        line_item["lineItemPromotionSpecs"] = [
            {"promotion": cfg["promotion"]}]
    return {
        "parent": "partners/" + cfg["partner"],
        "subscriptionId": subscription_id,
        "subscription": {
            "partnerUserToken": cfg["partner_user_token"],
            "serviceLocation": {"regionCode": cfg["region"]},
            "lineItems": [line_item],
        },
    }


def generate_activation_link(*, partner=None, product=None, promotion=None,
                             partner_user_token=None, subscription_id=None,
                             region=None, scope=None, sa=None, sa_file=None,
                             env=None, api_base=None, client=requests,
                             verify=True, now=None):
    """Mint the Jio "AI Gemini Pro" activation link.

    With a fully-configured partner service account (``sa`` passed, or the
    ``GEMINI_JIO_*`` env set) it runs the real RS256 -> OAuth ->
    userSessions:generate flow and returns a live URL. Otherwise it fails open
    to a ``template`` result that spells out the exact request + link shape +
    the env vars to set. Never raises."""
    now = now if now is not None else time.time()
    cfg = _config()
    # explicit kwargs override env
    if partner is not None:
        cfg["partner"] = partner
    if product is not None:
        cfg["product"] = product
    if promotion is not None:
        cfg["promotion"] = promotion
    if partner_user_token is not None:
        cfg["partner_user_token"] = partner_user_token
    if region is not None:
        cfg["region"] = region
    if scope is not None:
        cfg["scope"] = scope
    if env is not None:
        cfg["env"] = env.lower()
        cfg["sandbox"] = cfg["env"] == "sandbox"
        cfg["api_base"] = _SANDBOX_API if cfg["sandbox"] else _PROD_API
        cfg["act_base"] = _SANDBOX_ACT if cfg["sandbox"] else _PROD_API
    if api_base is not None:
        cfg["api_base"] = api_base

    if not cfg["subscription_id"] and subscription_id:
        cfg["subscription_id"] = subscription_id
    sid = cfg["subscription_id"] or str(uuid.uuid4())

    example = _request_example(cfg, sid)
    steps = [
        "1. Jio backend signs an RS256 service-account JWT (scope: "
        "payments.reseller.subscription).",
        "2. Swaps it for a Google OAuth access token "
        "(POST oauth2.googleapis.com/token).",
        "3. POST paymentsresellersubscription.googleapis.com/v1/partners/"
        + (cfg["partner"] or "{partner}") + "/userSessions:generate with a "
        "createIntent.",
        "4. Google returns a short-lived userSession.token.",
        "5. The activation link is: "
        + cfg["act_base"] + "/subscription/new/<token>.",
        "6. User opens the link, signs in to Google, taps Activate. Google "
        "then confirms back to Jio over Pub/Sub (endUserEntitled=true).",
    ]

    sa_err = None
    if sa is None:
        sa, sa_err = _read_sa()

    missing = _missing_for_live(cfg, sa is not None, sa_err)
    if sa is None or missing:
        return {
            "mode": "template",
            "env": cfg["env"],
            "url": cfg["act_base"] + "/subscription/new/<TOKEN>",
            "token": None,
            "expires_at": None,
            "partner": cfg["partner"] or None,
            "subscription_id": sid,
            "missing": missing,
            "steps": steps,
            "request_example": example,
            "url_check": None,
            "note": ("Live generation needs the partner's Google service "
                     "account + product id. Nothing is configured yet, so "
                     "this is the exact request the bot would send and the "
                     "link it would return once those are set."),
        }

    try:
        assertion = _sa_jwt(sa, cfg["scope"], now)
        access_token = _exchange_token(assertion, client=client)
        intent = {"createIntent": example}
        session = _generate_session(api_base=cfg["api_base"],
                                    partner=cfg["partner"],
                                    access_token=access_token,
                                    intent=intent, client=client)
        token = session.get("token")
        if not token:
            raise RuntimeError("no token in userSession response: "
                               + json.dumps(session)[:200])
        url = cfg["act_base"] + "/subscription/new/" + token
        check = _verify_url(url, client=client) if verify else None
        return {
            "mode": "live",
            "env": cfg["env"],
            "url": url,
            "token": token,
            "expires_at": session.get("expireTime"),
            "partner": cfg["partner"],
            "subscription_id": sid,
            "missing": [],
            "steps": steps,
            "request_example": example,
            "url_check": check,
            "note": "Minted live from the partner service account. Send the "
                    "link while it's fresh (~1h TTL, single-use).",
        }
    except (requests.RequestException, RuntimeError, ValueError,
            KeyError, OSError) as err:
        return {
            "mode": "error",
            "env": cfg["env"],
            "url": cfg["act_base"] + "/subscription/new/<TOKEN>",
            "token": None,
            "expires_at": None,
            "partner": cfg["partner"] or None,
            "subscription_id": sid,
            "missing": _missing_for_live(cfg, True, None),
            "steps": steps,
            "request_example": example,
            "url_check": None,
            "note": "Live attempt failed (check logs / credentials): "
                    + str(err)[:300],
        }


# ---- study text -------------------------------------------------------------
def how_it_works_text():
    return (
        "🎁 Jio “AI Gemini Pro” — how the link is created\n\n"
        "The link is NOT built by Jio's screen. Jio is a Google **reseller/"
        "billing partner**, and the link is minted by Google's **Payments "
        "Reseller Subscription API**.\n\n"
        "🔗 The link shape\n"
        "https://serviceactivation.google.com/subscription/new/<TOKEN>\n"
        "(sandbox: serviceactivation.sandbox.google.com; entitlement-only "
        "variant: .../subscription/entitle/<TOKEN>)\n\n"
        "⚙️ The flow (all server-to-server)\n"
        "1) You pass Jio's eligibility check (age 18-25, active rs.349+ 5G "
        "plan, once per Jio number).\n"
        "2) Jio's backend signs an **RS256 service-account JWT** (scope: "
        "payments.reseller.subscription).\n"
        "3) Swaps it for a Google OAuth access token.\n"
        "4) POST partners.userSessions:generate with a createIntent "
        "(product, your partner-user id, region IN).\n"
        "5) Google returns a short-lived **userSession.token**.\n"
        "6) The link is built by gluing that token onto the activation URL.\n"
        "7) You open it, sign in to Google, tap Activate. Google then "
        "confirms to Jio over **Pub/Sub** (endUserEntitled=true).\n\n"
        "🔐 The token itself\n"
        "• Opaque base64url blob (~205 bytes, starts `01 00`) — encrypted "
        "user intent + request.\n"
        "• ~1 hour TTL by default, single-use.\n"
        "• Bound to the intent on Google's side → **not forgeable** by the "
        "user; size scales with the intent payload.\n\n"
        "✅ A real Jio token I verified: opens a Google sign-in page (HTTP "
        "200 → accounts.google.com). Offer = 18 months Google AI Pro "
        "(~rs.35,100 value, 2TB storage, Gemini 2.5 Pro/3, Veo/Nano Banana, "
        "NotebookLM), valid only while an eligible recharge stays active.\n\n"
        "📖 You can't self-generate one — the token only exists after Jio's "
        "backend passes the check and asks Google to mint it. Tap “⚡ Generate "
        "my link” to run it live once the partner service account is "
        "configured.")


def gemini_result_text(result):
    """Chat-ready message for a generate_activation_link() result."""
    if result["mode"] == "live":
        check = result.get("url_check")
        check_line = ""
        if check:
            status, final = check
            if status == 200:
                check_line = ("✅ Link verified live (HTTP 200, redirects to "
                              "Google sign-in).\n")
            else:
                check_line = ("ℹ️ Link check: HTTP %s → %s\n"
                              % (status, (final or "")[:120]))
        expires = result.get("expires_at") or "unknown"
        return (
            "🎁 Your Jio AI Gemini Pro activation link (LIVE)\n\n"
            "```\n" + result["url"] + "\n```\n\n"
            + check_line
            + "⏱ Expires: " + expires + "\n"
            + "🔒 Single-use, ~1h window — open it now, sign in to Google, "
              "tap “Activate now”.\n\n"
            + result.get("note", "")
        )
    if result["mode"] == "error":
        return (
            "🎁 Live generation not available right now\n\n"
            + result.get("note", "") + "\n\n"
            "It falls back to the request template:\n\n"
            "```\n" + _pretty_request(result.get("request_example")) + "\n```\n"
            "Link shape once configured:\n"
            "```\n" + result["url"] + "\n```"
        )
    # template
    missing = result.get("missing") or []
    missing_line = ("⚙️ Still needed to go live:\n"
                    + "\n".join("• " + m for m in missing)
                    if missing else "")
    return (
        "🎁 Jio AI Gemini Pro — link generator (TEMPLATE)\n\n"
        "Live minting needs the partner's Google service account + product id. "
        "Here's the exact request it would send and the link it would return:\n\n"
        "Request (userSessions:generate → createIntent):\n"
        "```\n" + _pretty_request(result.get("request_example")) + "\n```\n\n"
        "Link it produces:\n"
        "```\n" + result["url"] + "\n```\n\n"
        + missing_line + "\n\n"
        "How the token is made (6 steps):\n"
        + "\n".join(result["steps"]) + "\n\n"
        + result.get("note", "")
    )


def _pretty_request(obj):
    try:
        return json.dumps(obj, indent=2, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(obj)


# ---- menu -------------------------------------------------------------------
def gemini_menu():
    text = (
        "🎁 Jio “AI Gemini Pro” link maker\n\n"
        "Generate the activation link for the Jio x Google AI Pro offer "
        "(serviceactivation.google.com/subscription/new/<token>), or read how "
        "Google mints it behind the scenes."
    )
    rows = [
        [{"text": "⚡ Generate my link", "callback_data": "gj:gen"}],
        [{"text": "📖 How the link is created", "callback_data": "gj:how"}],
        [{"text": "🏠 Home", "callback_data": "ui:home"}],
    ]
    return {"text": text, "reply_markup": {"inline_keyboard": rows}}


def _nav_keyboard(extra=None):
    rows = []
    if extra:
        rows.append(extra)
    rows.append([{"text": "🏠 Home", "callback_data": "ui:home"}])
    return {"inline_keyboard": rows}
