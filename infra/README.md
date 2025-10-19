# Infrastructure Overview

This directory contains Bicep templates for deploying the Azure resources required for the Octopus -> ADLS ingestion solution.

## Resources

Core resources deployed:

- Storage Account (Data Lake Gen2) for raw and curated data, plus state
- Azure Function App (Python) for scheduled ingestion
- App Service Plan / Consumption plan (depending on SKU) for Function
- Application Insights for telemetry
- Key Vault (optional future) for secrets (API key)
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
  --name octopus2adls-$(date +%Y%m%d%H%M%S) \
  --location northeurope \
  --template-file infra/main.bicep \
  --parameters @infra/parameters.dev.json
```

(Optionally use a resource group deployment instead of subscription if preferred.)

## Notes

- Storage account enforces HTTPS, TLS 1.2, and has hierarchical namespace enabled.
- Function App assigned managed identity used for Storage RBAC (Storage Blob Data Contributor) to avoid connection strings.
- API key for Octopus can be stored as Function App setting or later in Key Vault.
