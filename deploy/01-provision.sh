#!/usr/bin/env bash
# One-shot Azure infrastructure provisioning for ConcRisk.
# Idempotent-ish — safe to re-run; az commands will succeed if the
# resource already exists.
#
# Prerequisites:
#   - az CLI logged in (`az login`) to the subscription that holds your
#     student credits
#   - All env vars below either set in your shell or edited inline
#
# Run from the repo root: `bash deploy/01-provision.sh`

set -euo pipefail

# --- editable config ---
: "${RG:=rg-concrisk}"
: "${LOC:=eastus}"
: "${PG_NAME:=concrisk-pg}"
: "${PG_ADMIN:=concrisk}"
: "${PG_PASS:?PG_PASS must be set — pick a strong password}"
: "${PG_DB:=concrisk}"
: "${ACR_NAME:?ACR_NAME must be set — 5-50 lowercase alphanumeric, globally unique}"
: "${LAW_NAME:=concrisk-logs}"
: "${ACA_ENV:=concrisk-env}"

echo ">>> Creating resource group $RG in $LOC"
az group create -n "$RG" -l "$LOC" -o none

echo ">>> Creating Postgres Flexible Server $PG_NAME (Standard_B1ms, ~10 min)"
az postgres flexible-server create \
  -n "$PG_NAME" -g "$RG" --location "$LOC" \
  --tier Burstable --sku-name Standard_B1ms \
  --storage-size 32 --version 16 \
  --admin-user "$PG_ADMIN" --admin-password "$PG_PASS" \
  --public-access 0.0.0.0 \
  --database-name "$PG_DB" \
  --yes -o none

echo ">>> Allowing Azure services to reach PG"
az postgres flexible-server firewall-rule create \
  -n "$PG_NAME" -g "$RG" \
  --rule-name allow-azure-services \
  --start-ip-address 0.0.0.0 --end-ip-address 0.0.0.0 \
  -o none

if [ "${ALLOW_LOCAL_IP:-}" = "1" ]; then
  MY_IP=$(curl -s https://api.ipify.org)
  echo ">>> Allowing your local IP $MY_IP for psql access"
  az postgres flexible-server firewall-rule create \
    -n "$PG_NAME" -g "$RG" \
    --rule-name allow-local-dev \
    --start-ip-address "$MY_IP" --end-ip-address "$MY_IP" \
    -o none
fi

echo ">>> Creating Container Registry $ACR_NAME (Basic SKU, ~1 min)"
az acr create -n "$ACR_NAME" -g "$RG" --sku Basic --admin-enabled true -o none

echo ">>> Creating Log Analytics workspace $LAW_NAME"
az monitor log-analytics workspace create -n "$LAW_NAME" -g "$RG" -o none

LAW_ID=$(az monitor log-analytics workspace show -n "$LAW_NAME" -g "$RG" --query customerId -o tsv)
LAW_KEY=$(az monitor log-analytics workspace get-shared-keys -n "$LAW_NAME" -g "$RG" --query primarySharedKey -o tsv)

echo ">>> Creating Container Apps environment $ACA_ENV"
az containerapp env create \
  -n "$ACA_ENV" -g "$RG" --location "$LOC" \
  --logs-workspace-id "$LAW_ID" \
  --logs-workspace-key "$LAW_KEY" \
  -o none

PG_FQDN=$(az postgres flexible-server show -n "$PG_NAME" -g "$RG" --query fullyQualifiedDomainName -o tsv)
ACR_LOGIN=$(az acr show -n "$ACR_NAME" -g "$RG" --query loginServer -o tsv)
ACA_DOMAIN=$(az containerapp env show -n "$ACA_ENV" -g "$RG" --query properties.defaultDomain -o tsv)

cat <<EOF

================================================================
Provision complete. Values to paste into 02-containerapps.sh:
================================================================
export RG=$RG
export ACA_ENV=$ACA_ENV
export ACR_LOGIN=$ACR_LOGIN
export ACR_NAME=$ACR_NAME
export PG_FQDN=$PG_FQDN
export DATABASE_URL="postgresql://${PG_ADMIN}:<password>@${PG_FQDN}:5432/${PG_DB}"
export ACA_DOMAIN=$ACA_DOMAIN
# After step 02, your apps will be reachable at:
#   https://concrisk-api.$ACA_DOMAIN
#   https://concrisk-dashboard.$ACA_DOMAIN
================================================================
EOF
