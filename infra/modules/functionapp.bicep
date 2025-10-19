param baseName string
param location string
param planSku string = 'Y1'
param storageAccountName string
@secure()
@description('Optional Octopus API Key (prefer setting after deploy / Key Vault). Leave empty to skip.')
param octopusApiKey string = ''
@description('Optional Octopus Account Number')
param octopusAccountNumber string = ''
param appInsightsConnectionString string
param tags object = {}

var planName = toLower('${baseName}-plan')
var funcName = toLower('${baseName}-func')
// existing storage account for key retrieval
resource storage 'Microsoft.Storage/storageAccounts@2023-01-01' existing = {
  name: storageAccountName
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
        // Construct full connection string (required by Functions runtime)
        {
          name: 'AzureWebJobsStorage'
          // Using instance function listKeys() for clearer dependency graph
          value: 'DefaultEndpointsProtocol=https;AccountName=${storage.name};AccountKey=${storage.listKeys().keys[0].value};EndpointSuffix=core.windows.net'
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
      ]
    }
    httpsOnly: true
  }
  tags: tags
}

output functionAppName string = functionApp.name
output identityPrincipalId string = functionApp.identity.principalId
