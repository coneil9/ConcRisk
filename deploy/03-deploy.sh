#!/usr/bin/env bash
# Build the Docker image inside ACR (no local docker needed) and
# optionally bump the two Container Apps + one Job to the new revision.
#
# Required env vars:
#   RG, ACR_NAME
# Optional:
#   UPDATE_APPS=true|false (default true)
#   IMAGE_TAG              (default: short git SHA, or 'latest' outside git)
#
# Called from both the local `deploy/` flow and the deploy.yml GitHub
# Action.

set -euo pipefail

: "${RG:=rg-concrisk}"
: "${ACR_NAME:?ACR_NAME must be set}"
: "${UPDATE_APPS:=true}"

if [ -z "${IMAGE_TAG:-}" ]; then
  if command -v git >/dev/null && [ -d .git ]; then
    IMAGE_TAG=$(git rev-parse --short HEAD)
  else
    IMAGE_TAG=latest
  fi
fi

ACR_LOGIN=$(az acr show -n "$ACR_NAME" -g "$RG" --query loginServer -o tsv)
IMAGE="$ACR_LOGIN/concrisk:$IMAGE_TAG"
IMAGE_LATEST="$ACR_LOGIN/concrisk:latest"

echo ">>> Building $IMAGE in ACR (~5 min first time, faster with cache)"
az acr build \
  -r "$ACR_NAME" \
  -t "concrisk:$IMAGE_TAG" -t "concrisk:latest" \
  . \
  -o none

if [ "$UPDATE_APPS" = "true" ]; then
  echo ">>> Bumping concrisk-api to $IMAGE_TAG"
  az containerapp update -n concrisk-api -g "$RG" --image "$IMAGE" -o none

  echo ">>> Bumping concrisk-dashboard to $IMAGE_TAG"
  az containerapp update -n concrisk-dashboard -g "$RG" --image "$IMAGE" -o none

  echo ">>> Bumping concrisk-etl job to $IMAGE_TAG"
  az containerapp job update -n concrisk-etl -g "$RG" --image "$IMAGE" -o none
fi

echo
echo "Done. Image: $IMAGE  (also tagged :latest)"
