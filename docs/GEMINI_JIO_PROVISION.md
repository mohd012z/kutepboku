# Gemini-Jio Activation Link — Partner Provisioning Runbook

How to get the msasoup `/gemini` tool from its **template** mode (showing the
request it *would* send) to **live** mode (minting a real
`serviceactivation.google.com/subscription/new/<token>` URL).

Built 2026-11-06. Pairs with `gemini_jio.py` (the generator) and
`gemini_jio_provision.sh` (the one-shot GCP setup).

---

## TL;DR — what is self-serve vs. assigned by Google

| Thing | Who makes it | How |
|---|---|---|
| Google Cloud **project** | **You** (self-serve) | Cloud Console / `gcloud projects create` |
| **Payments Reseller Subscription API** enabled | **You** | Console → APIs & Services → Library, or `gcloud services enable` |
| **Service account** + **JSON key** | **You** | `gcloud iam service-accounts …` (see script) |
| **`roles/paymentsresellersubscription.partnerAdmin`** role | **You** | `gcloud projects add-iam-policy-binding` (see script) |
| **`partner_id`** (the `partners/<id>` you call) | **Google** (their Integration Team) | Provisioned against *your project* during partner onboarding |
| **product id** (e.g. Google AI Pro) + **promotion id** (free-18-mo) | **Google** | Assigned as part of the partner deal; resolvable via `products.list` / `promotions.findEligible` once a partner_id exists |

Key fact (Google's Access Control doc): *"use the GCP project associated with
the partner_id"* and *"your designated service accounts have access to
all-or-none partner entities of the containing Cloud project."* **The
`partner_id` is not something you generate** — Google links it to a project
you own. Until it's linked, `userSessions:generate` fails and the bot shows
its template (fail-open). That is the expected state right after self-serve
setup.

---

## Step 1 — Authenticate gcloud

```bash
export GCLOUD=/opt/data/bin/gcloud-sdk/google-cloud-sdk/bin/gcloud
$GCLOUD auth login          # opens a browser, OR:
#   $GCLOUD auth login --no-browser   # print URL, paste back the code
$GCLOUD config list
```

> No saved Google login in the bot's browser vault as of 2026-11-06 — a human
> must complete the sign-in (or hand over an already-authenticated gcloud
> account). If billing isn't enabled on the account, a brand-new project can't
> enable most APIs, so enable billing (free tier is fine) first.

## Step 2 — Create (or reuse) the project

```bash
# brand new:
PROJECT_ID=$($GCLOUD projects create msasoup-gemini-jio \
    --name="msasoup Gemini Jio" --format='value(projectId)')
echo "$PROJECT_ID"   # remember this + the project NUMBER for Google's email
$GCLOUD projects get-iam-policy "$PROJECT_ID" >/dev/null   # sanity
```

The **project number** (not just the id) is what Google's team needs —
`$GCLOUD projects list --filter="projectId:$PROJECT_ID" --format='value(projectNumber)'`.

## Step 3 — Run the one-shot provision

```bash
cd /opt/data/msasoup
GCLOUD=$GCLOUD PROJECT_ID=$PROJECT_ID ENV_NAME=production ./gemini_jio_provision.sh
```

It will: enable the API, create `msasoup-gemini-jio-production@<proj>.iam…`,
grant `roles/paymentsresellersubscription.partnerAdmin`, and write the JSON key
to `./msasoup-production.json` (chmod 600). **Do not commit that key.**

## Step 4 — Point the bot at the key

Add to `/opt/data/msasoup/msasoup.env` (600 perms, never commit):

```
GEMINI_JIO_SA_FILE=/opt/data/msasoup/msasoup-production.json
GEMINI_JIO_ENV=production
GEMINI_JIO_REGION=IN
# — the three below only once Google assigns them (Step 5):
# GEMINI_JIO_PARTNER=<partner_id>
# GEMINI_JIO_PRODUCT=<partners/<partner_id>/products/<productId>>
# GEMINI_JIO_PROMOTION=<partners/<partner_id>/promotions/<promotionId>>
```

Restart the poller (it picks the env at startup):

```bash
kill $(pgrep -f "msasoup/main.py" | head -1)
/opt/data/scripts/msasoup-watchdog.sh   # brings up exactly one instance
ps -eo pid,args | grep -F "msasoup/main.py" | grep -v grep   # verify ONE
```

Now `/gemini → ⚡ Generate my link` will run the real RS256 → OAuth →
`userSessions:generate` chain. **Without a partner_id it still shows the
template** — that is correct, not a bug.

## Step 5 — Get the partner_id + product/promotion ids from Google

Send Google's Payments Reseller integration team (the same team that onboarded
Jio for the AI Pro deal) roughly:

> "Please link a **partner_id** to our GCP project **<project-id>**
> (project number **<project-number>**) for the **Payments Reseller
> Subscription API**, and tell us the **product** and **promotion** resource
> names we're authorised to resell (we want to activate **Google AI Pro** /
> Google One AI, region **IN**). We have a service account with the
> `paymentsresellersubscription.partnerAdmin` role ready."

Once they reply, verify you can *see* the catalogue (proves the SA + partner
link work) before minting:

```bash
# with the key as GOOGLE_APPLICATION_CREDENTIALS:
export GOOGLE_APPLICATION_CREDENTIALS=/opt/data/msasoup/msasoup-production.json
$GCLOUD auth print-access-token > /tmp/at.txt
P=$(cat /opt/data/msasoup/msasoup.env | awk -F= '/^GEMINI_JIO_PARTNER=/{print $2}')
curl -sS "https://paymentsresellersubscription.googleapis.com/v1/partners/${P}/products?regionCodes=IN" \
  -H "Authorization: Bearer $(cat /tmp/at.txt)"
curl -sS "https://paymentsresellersubscription.googleapis.com/v1/partners/${P}/promotions:findEligible" \
  -H "Authorization: Bearer $(cat /tmp/at.txt)" -H "Content-Type: application/json" \
  -d '{"regionCode":"IN"}'
```

- **Products list returns entries** → the partner link is live; copy the real
  `partners/<id>/products/<productId>` (and a promotion) into the env, restart
  the poller, and `/gemini` mints a **real** token.
- **`403 PERMISSION_DENIED` / `NOT_FOUND` / "no partner"** → Google hasn't
  linked the partner_id to this project yet; keep the template and chase the
  onboarding email. The bot stays useful either way.

## Step 6 — Mint a token

`/gemini → ⚡ Generate my link`. The result message includes:
- the `serviceactivation.google.com/subscription/new/<token>` URL,
- `⏱ expires` (the `expireTime` Google returned),
- a best-effort link check (opening it redirects to Google sign-in; it does
  not consume the token).

Send the link **immediately** — it's ~1 h and single-use.

---

## Sandbox first (recommended)

The exact same flow exists in pre-production and is the safest way to prove
the pipeline end-to-end before production:

```
GEMINI_JIO_ENV=sandbox          # uses preprod-paymentsresellersubscription…
                                 # and serviceactivation.sandbox.google.com
```

Sandbox still needs a partner_id (the Google team configures it against the
project). Use a dedicated `ENV_NAME=sandbox` service account/key if you want
prod and sandbox credentials separated.

---

## Reference — the exact call the bot makes

```
POST https://paymentsresellersubscription.googleapis.com/v1/partners/<partner_id>/userSessions:generate
Authorization: Bearer <access_token-from-RS256-SA-JWT>
Content-Type: application/json

{
  "intentPayload": {
    "createIntent": {
      "parent": "partners/<partner_id>",
      "subscriptionId": "<your-unique-id>",
      "subscription": {
        "partnerUserToken": "<your-id-for-the-user, <=63 ASCII>",
        "serviceLocation": { "regionCode": "IN" },
        "lineItems": [
          {
            "product": "partners/<partner_id>/products/<productId>",
            "lineItemPromotionSpecs": [
              { "promotion": "partners/<partner_id>/promotions/<promotionId>" }
            ]
          }
        ]
      }
    }
  }
}

// -> {"userSession": {"token": "<205-byte blob>", "expireTime": "<RFC3339>"}}
//    link = "https://serviceactivation.google.com/subscription/new/" + token
```

## Gotchas

- **`partnerUserToken`** is *your* id for the end user (e.g. a customer id),
  ≤63 ASCII chars — not the Google account. It maps the subscription back to
  your user.
- **`subscriptionId`** is yours and is the idempotency key: re-minting for the
  same id never double-fulfills.
- Token hygiene (Google's docs): generate per authenticated user; don't paste
  it into an unauthenticated channel where someone else could grab it.
- The **Jio** Nov-2026 gateway 403 is on *Jio's* redemption front-end (which
  mints Jio tokens), not on Google's activation endpoint — a separate partner
  can still mint its own tokens for its own deals.
- Never commit the SA JSON key. It's the partner's billing/subscription
  credential.
