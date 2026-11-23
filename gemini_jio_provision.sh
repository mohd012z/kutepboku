#!/usr/bin/env bash
#
# gemini_jio_provision.sh — one-shot provisioning for the Jio "AI Gemini Pro"
# activation-link generator (see gemini_jio.py + /gemini in the msasoup bot).
#
# WHAT THIS CREATES (all SELF-SERVE, you own it):
#   1. A Google Cloud project (or reuse an existing one via $PROJECT_ID).
#   2. Enables the Payments Reseller Subscription API in it.
#   3. A service account  ->  roles/paymentsresellersubscription.partnerAdmin.
#   4. A JSON key for that service account (THE credential the bot signs JWTs
#      with — store it as GEMINI_JIO_SA_FILE in msasoup.env).
#
# WHAT THIS CANNOT DO (Google's team assigns it):
#   * partner_id   — the reseller id that must prefix every call. Google links
#                    it to THIS project during partner onboarding. Until it is,
#                    userSessions:generate returns a "no partner" error and the
#                    bot falls back to its template (fail-open). The runbook
#                    (GEMINI_JIO_PROVISION.md) has the exact email to send.
#   * product / promotion ids you're allowed to resell (e.g. Google AI Pro +
#                    the free-18-month deal).
#
# REQUIRES: gcloud CLI authenticated (gcloud auth login), plus billing enabled
#           on the project (needed to enable most APIs on a brand-new project).
#
# USAGE:
#   export GCLOUD=/opt/data/bin/gcloud-sdk/google-cloud-sdk/bin/gcloud
#   # brand-new project:
#   $GCLOUD config set project "" 2>/dev/null
#   PROJECT_ID=$(gcloud projects create my-gemini-partner --name="msasoup Gemini Jio" --format='value(projectId)')
#   PROJECT_ID=$PROJECT_ID ./gemini_jio_provision.sh
#   # ...or reuse an existing project:
#   PROJECT_ID=existing-project ./gemini_jio_provision.sh
#
set -euo pipefail

GCLOUD="${GCLOUD:-gcloud}"
PROJECT_ID="${PROJECT_ID:?Set PROJECT_ID (the GCP project to provision)}"
ENV_NAME="${ENV_NAME:-production}"                 # production | sandbox
SA_NAME="${SA_NAME:-msasoup-gemini-jio-${ENV_NAME}}"
KEY_FILE="${KEY_FILE:-./msasoup-${ENV_NAME}.json}"   # the SA JSON key to write
ROLE="roles/paymentsresellersubscription.partnerAdmin"

echo "==> Using gcloud: $($GCLOUD --version 2>&1 | head -1)"
echo "==> Project: $PROJECT_ID   env: $ENV_NAME   sa: $SA_NAME"

# 1) make sure we're pointed at the project
$GCLOUD config set project "$PROJECT_ID"

# 2) enable the Payments Reseller Subscription API
echo "==> Enabling paymentsresellersubscription.googleapis.com ..."
$GCLOUD services enable paymentsresellersubscription.googleapis.com --project "$PROJECT_ID"

# 3) create the service account (idempotent)
echo "==> Ensuring service account '$SA_NAME' exists ..."
if ! $GCLOUD iam service-accounts describe "$SA_NAME@$PROJECT_ID.iam.gserviceaccount.com" >/dev/null 2>&1; then
  $GCLOUD iam service-accounts create "$SA_NAME" \
      --display-name="msasoup Gemini Jio ($ENV_NAME)" --project "$PROJECT_ID"
fi
SA_EMAIL="$SA_NAME@$PROJECT_ID.iam.gserviceaccount.com"

# 4) grant the Payments Reseller Admin role (idempotent)
echo "==> Granting $ROLE to $SA_EMAIL ..."
$GCLOUD projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:$SA_EMAIL" --role="$ROLE" \
    --condition=None || echo "    (role already granted — ok)"

# 5) create a JSON key (idempotent: only if the file isn't present)
if [[ -f "$KEY_FILE" ]]; then
  echo "==> Key file already present: $KEY_FILE (skipping creation)"
else
  echo "==> Creating service-account key -> $KEY_FILE"
  $GCLOUD iam service-accounts keys create "$KEY_FILE" \
      --iam-account="$SA_EMAIL" --key-format=JSON
fi
chmod 600 "$KEY_FILE"

# 6) the env block to drop into msasoup.env
cat <<EOF

====================================================================
Provisioning done. Add these to /opt/data/msasoup/msasoup.env:

  GEMINI_JIO_SA_FILE=/opt/data/msasoup/$(basename "$KEY_FILE")
  GEMINI_JIO_ENV=${ENV_NAME}
  GEMINI_JIO_REGION=IN
  # FILL THESE from Google's onboarding (see GEMINI_JIO_PROVISION.md):
  GEMINI_JIO_PARTNER=<partner_id-assigned-by-google>
  GEMINI_JIO_PRODUCT=<partners/<partner_id>/products/<productId>>
  GEMINI_JIO_PROMOTION=<partners/<partner_id>/promotions/<promotionId>>
  GEMINI_JIO_PARTNER_USER_TOKEN=<your-id-for-the-end-user>
====================================================================
EOF
echo
echo "Verify the key works (list the products this partner may resell — will be"
echo "empty until Google assigns a partner_id to this project):"
echo "  $GCLOUD auth print-access-token > /dev/null 2>&1"
echo "  # quick probe (needs the key): see GEMINI_JIO_PROVISION.md § verify"
