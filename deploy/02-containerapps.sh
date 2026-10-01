#!/usr/bin/env bash
# Create or update the two Container Apps (api, dashboard) and the one
# scheduled Container Apps Job (etl).
#
# Required env vars (from 01-provision.sh output + your secrets):
#   RG, ACA_ENV, ACR_LOGIN, ACR_NAME, DATABASE_URL, SEC_USER_AGENT,
#   OPENFIGI_API_KEY, ANTHROPIC_API_KEY, API_KEY, ACA_DOMAIN
# Optional:
#   ANTHROPIC_MODEL  (defaults to claude-sonnet-4-6)
#   ETL_CRON         (defaults to "0 6 * * *" — daily 06:00 UTC)
#
# Run from the repo root: `bash deploy/02-containerapps.sh`.
# Must run AFTER 03-deploy.sh has pushed at least one image.

set -euo pipefail

: "${RG:?}"
: "${ACA_ENV:?}"
: "${ACR_LOGIN:?}"
: "${ACR_NAME:?}"
: "${DATABASE_URL:?}"
: "${SEC_USER_AGENT:?}"
: "${OPENFIGI_API_KEY:=}"
: "${ANTHROPIC_API_KEY:=}"
: "${ANTHROPIC_MODEL:=claude-sonnet-4-6}"
: "${API_KEY:?set API_KEY to a random strong secret (used as X-API-Key)}"
: "${ACA_DOMAIN:?}"
: "${ETL_CRON:=0 6 * * *}"

IMAGE="$ACR_LOGIN/concrisk:latest"
API_URL="https://concrisk-api.$ACA_DOMAIN"

ACR_USER=$(az acr credential show -n "$ACR_NAME" --query username -o tsv)
ACR_PASS=$(az acr credential show -n "$ACR_NAME" --query "passwords[0].value" -o tsv)

# --- API container app ---
echo ">>> Creating/updating concrisk-api"
if ! az containerapp show -n concrisk-api -g "$RG" >/dev/null 2>&1; then
  az containerapp create \
    -n concrisk-api -g "$RG" --environment "$ACA_ENV" \
    --image "$IMAGE" \
    --registry-server "$ACR_LOGIN" \
    --registry-username "$ACR_USER" --registry-password "$ACR_PASS" \
    --target-port 8080 --ingress external \
    --min-replicas 0 --max-replicas 1 \
    --command "/app/entrypoint.sh" --args "api" \
    --secrets "database-url=$DATABASE_URL" \
              "sec-user-agent=$SEC_USER_AGENT" \
              "openfigi-api-key=$OPENFIGI_API_KEY" \
              "anthropic-api-key=$ANTHROPIC_API_KEY" \
              "api-key=$API_KEY" \
    --env-vars ENV=prod \
               ANTHROPIC_MODEL="$ANTHROPIC_MODEL" \
               DATABASE_URL=secretref:database-url \
               SEC_USER_AGENT=secretref:sec-user-agent \
               OPENFIGI_API_KEY=secretref:openfigi-api-key \
               ANTHROPIC_API_KEY=secretref:anthropic-api-key \
               API_KEY=secretref:api-key \
    -o none
else
  echo "  (already exists — use 03-deploy.sh to roll a new image)"
fi

# --- Dashboard container app ---
echo ">>> Creating/updating concrisk-dashboard"
if ! az containerapp show -n concrisk-dashboard -g "$RG" >/dev/null 2>&1; then
  az containerapp create \
    -n concrisk-dashboard -g "$RG" --environment "$ACA_ENV" \
    --image "$IMAGE" \
    --registry-server "$ACR_LOGIN" \
    --registry-username "$ACR_USER" --registry-password "$ACR_PASS" \
    --target-port 8501 --ingress external \
    --min-replicas 0 --max-replicas 1 \
    --command "/app/entrypoint.sh" --args "dashboard" \
    --secrets "api-key=$API_KEY" \
              "anthropic-api-key=$ANTHROPIC_API_KEY" \
    --env-vars ENV=prod \
               CONCRISK_API_URL="$API_URL" \
               API_KEY=secretref:api-key \
               ANTHROPIC_API_KEY=secretref:anthropic-api-key \
               ANTHROPIC_MODEL="$ANTHROPIC_MODEL" \
    -o none
else
  echo "  (already exists — use 03-deploy.sh to roll a new image)"
fi

# --- ETL scheduled job ---
echo ">>> Creating/updating concrisk-etl job (cron: $ETL_CRON)"
if ! az containerapp job show -n concrisk-etl -g "$RG" >/dev/null 2>&1; then
  az containerapp job create \
    -n concrisk-etl -g "$RG" --environment "$ACA_ENV" \
    --image "$IMAGE" \
    --registry-server "$ACR_LOGIN" \
    --registry-username "$ACR_USER" --registry-password "$ACR_PASS" \
    --trigger-type Schedule --cron-expression "$ETL_CRON" \
    --replica-timeout 3600 --replica-retry-limit 1 \
    --parallelism 1 --replica-completion-count 1 \
    --command "/app/entrypoint.sh" --args "etl --quarters 1" \
    --secrets "database-url=$DATABASE_URL" \
              "sec-user-agent=$SEC_USER_AGENT" \
              "openfigi-api-key=$OPENFIGI_API_KEY" \
    --env-vars ENV=prod \
               DATABASE_URL=secretref:database-url \
               SEC_USER_AGENT=secretref:sec-user-agent \
               OPENFIGI_API_KEY=secretref:openfigi-api-key \
    -o none
else
  echo "  (already exists — use 03-deploy.sh to roll a new image)"
fi

echo
echo "================================================================"
echo "Container Apps up. Live URLs:"
echo "  API:        $API_URL"
echo "  Dashboard:  https://concrisk-dashboard.$ACA_DOMAIN"
echo "ETL job (run once manually to seed data):"
echo "  az containerapp job start -n concrisk-etl -g $RG"
echo "================================================================"
