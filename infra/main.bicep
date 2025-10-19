@description('Base name prefix for all resources')
param baseName string

@description('Location for resources')
param location string = resourceGroup().location

@description('Storage account SKU')
@allowed([ 'Standard_LRS','Standard_GRS' ])
param storageSku string = 'Standard_LRS'

@description('Enable creation of Log Analytics workspace')
param enableLogAnalytics bool = true

@description('Function App plan SKU (Y1 for consumption)')
param functionSku string = 'Y1'

@description('Function storage account SKU')
@allowed([ 'Standard_LRS','Standard_GRS' ])
param functionStorageSku string = 'Standard_LRS'

@description('Tags to apply to all resources')
param tags object = {}

@secure()
@description('Octopus Energy API Key')
param octopusApiKey string = ''

@description('Octopus Energy Account Number') 
param octopusAccountNumber string = ''

@description('JSON array of meters to process')
param metersJson string = ''

// Create Key Vault for storing secrets
module keyVault './modules/keyvault.bicep' = {
  name: '${baseName}-keyvault'
  params: {
    baseName: baseName
    location: location
    tags: tags
  }
}

// Create storage account for data lake
module storage './modules/storage.bicep' = {
  name: '${baseName}-storage'
  params: {
    baseName: baseName
    location: location
    sku: storageSku
    tags: tags
  }
}

// MODULE: Function internal storage
module functionstorage 'modules/functionstorage.bicep' = {
  name: '${baseName}-functionstore'
  params: {
    baseName: baseName
    location: location
    sku: functionStorageSku
    tags: tags
  }
}

// MODULE: App Insights & (optional) Log Analytics
module insights 'modules/insights.bicep' = {
  name: '${baseName}-insights'
  params: {
    baseName: baseName
    location: location
    enableLogAnalytics: enableLogAnalytics
    tags: tags
  }
}

// MODULE: Function App (Linux)
module function 'modules/function.bicep' = {
  name: '${baseName}-function'
  params: {
    baseName: baseName
    location: location
    planSku: functionSku
    functionStorageAccountName: functionstorage.outputs.functionStorageAccountName
    dataLakeAccountName: storage.outputs.storageAccountName
    keyVaultName: keyVault.outputs.keyVaultName
    appInsightsConnectionString: insights.outputs.appInsightsConnectionString
    octopusApiKey: octopusApiKey
    octopusAccountNumber: octopusAccountNumber
    metersJson: metersJson
    tags: tags
  }
}

// Assign RBAC permissions for Function to access storage and Key Vault
module rbac './modules/roleAssignments.bicep' = {
  name: '${baseName}-rbac'
  params: {
    principalId: function.outputs.identityPrincipalId
    storageAccountName: storage.outputs.storageAccountName
    keyVaultName: keyVault.outputs.keyVaultName
  }
}

// Diagnostics (if Log Analytics enabled)
module diagnostics 'modules/diagnostics.bicep' = if (enableLogAnalytics) {
  name: '${baseName}-diag'
  params: {
    functionAppName: function.outputs.functionAppName
    storageAccountName: storage.outputs.storageAccountName
    workspaceId: insights.outputs.logAnalyticsWorkspaceId
  }
}

output storageAccountName string = storage.outputs.storageAccountName
output functionAppName string = function.outputs.functionAppName
