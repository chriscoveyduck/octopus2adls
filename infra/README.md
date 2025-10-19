
# Infrastructure Overview

This directory contains Bicep templates for deploying the Azure resources required for the Energy Analytics Data Pipe solution (multi-source ingestion: Octopus, Tado, and future weather data).

## Resources


Core resources deployed:

- Storage Account (Data Lake Gen2) for raw and curated energy, heating, and weather data, plus state
- Azure Function App (Python) for scheduled ingestion from multiple sources
- App Service Plan / Consumption plan (depending on SKU) for Function
- Application Insights for telemetry
- Key Vault (optional future) for secrets (API keys)
- Log Analytics workspace for central logging (shared via diagnostic settings)

## Module Layout

```
infra/
  main.bicep              # orchestrates modules
  parameters.example.json # sample parameter file
  modules/
    storage.bicep
    functionapp.bicep
    insights.bicep
    roleAssignments.bicep
```

## Deployment


Example (Azure CLI):

```bash
az deployment sub create \
  --name energy-analytics-data-pipe-$(date +%Y%m%d%H%M%S) \
  --location northeurope \
  --template-file infra/main.bicep \
  --parameters @infra/parameters.dev.json
```

(Optionally use a resource group deployment instead of subscription if preferred.)

## Notes

- Storage account enforces HTTPS, TLS 1.2, and has hierarchical namespace enabled.
- Function App assigned managed identity used for Storage RBAC (Storage Blob Data Contributor) to avoid connection strings.
- API key for Octopus can be stored as Function App setting or later in Key Vault.
