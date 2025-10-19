@description('Base name prefix')
param baseName string
param location string
param sku string = 'Standard_LRS'
param tags object = {}

var rawName = toLower(replace('${baseName}data', '-', ''))
// enforce length 3-24 alphanumeric by trimming and removing non-alphanumerics
// Generate storage account name: letters & digits only, <=24 chars
var cleaned = replace(replace(rawName, '_', ''), '.', '')
var storageName = length(cleaned) > 24 ? substring(cleaned, 0, 24) : cleaned

resource storage 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: storageName
  location: location
  sku: { name: sku }
  kind: 'StorageV2'
  properties: {
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
    supportsHttpsTrafficOnly: true
    isHnsEnabled: true
  }
  tags: tags
}

// Consumption (Octopus) container
resource containerConsumption 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-01-01' = {
  name: '${storage.name}/default/consumption'
  properties: {
    publicAccess: 'None'
  }
}

// Demand (Tado) container
resource containerDemand 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-01-01' = {
  name: '${storage.name}/default/demand'
  properties: {
    publicAccess: 'None'
  }
}

// Temps (Tado) container
resource containerTemps 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-01-01' = {
  name: '${storage.name}/default/temps'
  properties: {
    publicAccess: 'None'
  }
}
// Heating (combined demand + temperature) container (replaces prior 'demand' and 'temps')
resource containerHeating 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-01-01' = {
  name: '${storage.name}/default/heating'
  properties: {
    publicAccess: 'None'
  }
}

// Weather container
resource containerWeather 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-01-01' = {
  name: '${storage.name}/default/weather'
  properties: {
    publicAccess: 'None'
  }
}

// Shared curated / refined outputs
resource containerCurated 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-01-01' = {
  name: '${storage.name}/default/curated'
  properties: {
    publicAccess: 'None'
  }
}

output storageAccountName string = storage.name
output storageAccountId string = storage.id
output consumptionContainerName string = 'consumption'
// No key outputs (security best practice)
