@description('Base name for plan and function app')
param baseName string
@description('Deployment location')
param location string
@description('Plan SKU (Y1 consumption or EP* for Elastic Premium)')
param planSku string = 'Y1'
@description('Function internal storage account (AzureWebJobsStorage)')
param functionStorageAccountName string
@description('Data lake storage account name for ingestion (exposed as STORAGE_ACCOUNT_NAME)')
param dataLakeAccountName string
@secure()
@description('Optional Octopus API Key (prefer post-deploy / Key Vault)')
param octopusApiKey string = ''
@description('Optional Octopus Account Number')
param octopusAccountNumber string = ''
@description('JSON array of meters to process')
param metersJson string = ''
@description('App Insights connection string')
param appInsightsConnectionString string
@description('Key Vault name for storing secrets')
param keyVaultName string
@description('Tags to apply')
param tags object = {}

var planName = toLower('${baseName}-plan')
var funcName = toLower('${baseName}-func')

// Reference existing storage (needed only for key list)
resource funcStorage 'Microsoft.Storage/storageAccounts@2023-01-01' existing = {
  name: functionStorageAccountName
}

resource plan 'Microsoft.Web/serverfarms@2023-12-01' = {
  name: planName
  location: location
  sku: {
    name: planSku
    tier: planSku == 'Y1' ? 'Dynamic' : 'ElasticPremium'
  }
  kind: 'functionapp,linux'
  properties: {
    reserved: true
  }
  tags: tags
}

resource functionApp 'Microsoft.Web/sites@2023-12-01' = {
  name: funcName
  location: location
  kind: 'functionapp,linux'
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    siteConfig: {
      linuxFxVersion: 'Python|3.11'
      appSettings: [
        {
          name: 'FUNCTIONS_EXTENSION_VERSION'
          value: '~4'
        }
        {
          name: 'FUNCTIONS_WORKER_RUNTIME'
          value: 'python'
        }
        {
          name: 'PYTHON_VERSION'
          value: '3.11'
        }
        {
          name: 'AzureWebJobsStorage'
          value: 'DefaultEndpointsProtocol=https;AccountName=${funcStorage.name};AccountKey=${funcStorage.listKeys().keys[0].value};EndpointSuffix=core.windows.net'
        }
        {
          name: 'STORAGE_ACCOUNT_NAME'
          value: dataLakeAccountName
        }
        {
          name: 'KEY_VAULT_NAME'
          value: keyVaultName
        }
        {
          name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
          value: appInsightsConnectionString
        }
        {
          name: 'OCTOPUS_API_KEY'
          value: length(octopusApiKey) > 0 ? octopusApiKey : ''
        }
        {
          name: 'OCTOPUS_ACCOUNT_NUMBER'
          value: octopusAccountNumber
        }
        {
          name: 'METERS_JSON'
          value: metersJson
        }
      ]
    }
  }
  tags: tags
}

output functionAppName string = functionApp.name
output identityPrincipalId string = functionApp.identity.principalId
