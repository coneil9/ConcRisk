# Deploying ConcRisk to Azure

End-to-end deploy to the SPEC §11 topology:
- Resource group `rg-concrisk`
- Postgres Flexible Server (Burstable Standard_B1ms)
- Azure Container Registry (Basic)
- Container Apps environment with Log Analytics
- Two Container Apps: `concrisk-api`, `concrisk-dashboard`
- One scheduled Container Apps Job: `concrisk-etl`

Total provisioning time: ~20 min. All resources scale to zero (apps) or run on cron (job), so standing-still cost is a few dollars per month on student credits.

---

## 0. Prerequisites

- **Azure subscription** with available credits (student or paid).
- **az CLI** installed and logged in:
  ```bash
  az login
  az account set --subscription "<your-subscription-id>"
  ```
- **Docker locally** (only needed if you want to smoke-test the image before shipping it).
- **Rotate your API keys first** — the `.env` keys were exposed during Phase 0's planning session. New Anthropic + OpenFIGI keys before you set them as Container Apps secrets.

Pick a globally unique ACR name (5–50 lowercase alphanumeric, must not collide with anyone else's `*.azurecr.io`). Use it everywhere below.

---

## 1. Provision infrastructure

```bash
export PG_PASS='pick-a-strong-password'          # Postgres admin password
export ACR_NAME='<your-unique-acr-name>'         # e.g. concriskacr123
export ALLOW_LOCAL_IP=1                          # optional: let your laptop psql in

bash deploy/01-provision.sh
```

Takes ~10 min. The last block of output gives you the env vars you need for step 2 — copy them.

If you want to be able to `psql` into the DB from your laptop, keep `ALLOW_LOCAL_IP=1`.

---

## 2. First-time deploy of the Docker image

Before step 3 can create the Container Apps that pull `your-acr.azurecr.io/concrisk:latest`, the image needs to exist. Build it once in ACR:

```bash
export RG=rg-concrisk
export ACR_NAME='<your-unique-acr-name>'
export UPDATE_APPS=false   # apps don't exist yet; skip the update step

bash deploy/03-deploy.sh
```

Takes ~5 min on first build (slower than local because `az acr build` runs on a VM with no local cache).

---

## 3. Create the Container Apps and the ETL job

Paste the env vars from step 1's output, plus your secrets:

```bash
export RG=rg-concrisk
export ACA_ENV=concrisk-env
export ACR_LOGIN='<your-acr-name>.azurecr.io'
export ACR_NAME='<your-acr-name>'
export ACA_DOMAIN='<the-defaultDomain-from-01-output>'

export DATABASE_URL='postgresql://concrisk:<PG_PASS>@<PG_FQDN>:5432/concrisk'
export SEC_USER_AGENT='Your Name your.email@example.com'
export OPENFIGI_API_KEY='<rotated-key>'
export ANTHROPIC_API_KEY='<rotated-key>'
export API_KEY="$(openssl rand -hex 32)"   # strong random for X-API-Key auth
export ANTHROPIC_MODEL='claude-sonnet-4-6'

bash deploy/02-containerapps.sh
```

Takes ~5 min. Prints the live URLs at the end.

---

## 4. Apply migrations and seed data

Apply the Alembic migrations once:
```bash
az containerapp exec -n concrisk-api -g rg-concrisk \
  --command "/app/entrypoint.sh migrate"
```

Trigger the ETL job manually to seed your first filings (don't wait 24h for the cron):
```bash
az containerapp job start -n concrisk-etl -g rg-concrisk
az containerapp job execution list -n concrisk-etl -g rg-concrisk --output table
# wait a few minutes for it to complete, then:
az containerapp job logs show -n concrisk-etl -g rg-concrisk --container concrisk-etl
```

The default job command is `etl --quarters 1`. Edit `02-containerapps.sh` and re-run to change (e.g. `--quarters 8` for the initial backfill).

---

## 5. Verify the live stack

```bash
API=https://concrisk-api.$ACA_DOMAIN
DASH=https://concrisk-dashboard.$ACA_DOMAIN

curl -sf -H "X-API-Key: $API_KEY" $API/health            # {"status":"ok","db":"ok"}
curl -sf -H "X-API-Key: $API_KEY" $API/funds | head -c 200
open $DASH
```

The dashboard calls the API with the same `API_KEY` because step 3 wires it as the dashboard's `API_KEY` env var.

---

## 6. GitHub Actions CD (optional)

The CI workflow builds and pushes images to GHCR on every push to `main` automatically — no secrets needed. The CD workflow (`.github/workflows/deploy.yml`) is `workflow_dispatch` only and runs `03-deploy.sh` inside the Action. To enable it:

1. Create a service principal scoped to the resource group:
   ```bash
   SUB_ID=$(az account show --query id -o tsv)
   az ad sp create-for-rbac --name concrisk-github-cd --sdk-auth \
     --role contributor \
     --scopes /subscriptions/$SUB_ID/resourceGroups/rg-concrisk
   ```
   Copy the entire JSON blob — this is `AZURE_CREDENTIALS`.

2. In GitHub → Settings → Secrets → Actions, add:
   - `AZURE_CREDENTIALS` — paste the JSON
   - `ACR_NAME` — your registry name
   - `RESOURCE_GROUP` — optional (defaults to `rg-concrisk`)

3. Actions → "Deploy to Azure" → **Run workflow**. Pick `update_apps: true` to roll a new revision after the build.

---

## 7. Budget alert

The SPEC calls for a subscription budget alert. One place I didn't automate — set it in the Azure portal:

**Cost Management + Billing → Budgets → + Add** → scope your subscription → monthly budget (e.g. $20) → threshold alerts at 50%, 80%, 100% → notify your email.

---

## Teardown

Drop everything in one command when the demo is over:

```bash
az group delete -n rg-concrisk --yes --no-wait
```

Also revoke the service principal if you created one:
```bash
az ad sp delete --id <appId-from-AZURE_CREDENTIALS-json>
```

---

## Known limitations / upgrade paths

- **Public PG endpoint.** Fine for a demo. Lock down with a VNet + private endpoint for prod — adds `az network vnet create` + `--vnet-name` on the PG and ACA env create commands.
- **Container Registry admin user enabled.** Easier for scripts; swap to managed identity for prod.
- **CORS allow_origins=["*"].** Permissive but still gated by `X-API-Key`. Tighten to `https://concrisk-dashboard.<domain>` after first deploy — one edit in `src/concrisk/api/main.py`.
- **No alerting.** Container Apps logs land in Log Analytics; wire up Azure Monitor alerts (health probe failures, ETL job failures) when you need them.
- **ETL job doesn't apply migrations.** If a schema change ships, run step 4's `migrate` command before the next ETL run.
