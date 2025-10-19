#!/usr/bin/env bash
set -euo pipefail

# Simple wrapper to deploy the Bicep template with a chosen parameter set.
# Usage: ./scripts/deploy.sh <env> <resource-group> [location]
# env: dev|prod or a custom name mapping to infra/parameters.<env>.json
# resource-group: name of the target resource group
# location: optional Azure region (defaults to northeurope)

ENV_NAME=${1:-dev}
RG_NAME=${2:-energy-analytics-dev}
LOCATION=${3:-northeurope}
PARAM_FILE="infra/parameters.${ENV_NAME}.json"

if [ ! -f "$PARAM_FILE" ]; then
  echo "Parameter file $PARAM_FILE not found" >&2
  exit 1
fi

echo "Creating resource group $RG_NAME in $LOCATION (idempotent)"
az group create -n "$RG_NAME" -l "$LOCATION" >/dev/null

echo "Deploying main.bicep with $PARAM_FILE"
az deployment group create \
  -g "$RG_NAME" \
  -f infra/main.bicep \
  -p @"$PARAM_FILE" \
  -o table

# Optional: show outputs
echo "Deployment outputs:"
az deployment group show -g "$RG_NAME" -n $(az deployment group list -g "$RG_NAME" --query '[0].name' -o tsv) --query properties.outputs
