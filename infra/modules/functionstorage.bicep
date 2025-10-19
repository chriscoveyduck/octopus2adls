@description('Base name prefix')
param baseName string
param location string
@description('Storage SKU for function runtime account')
param sku string = 'Standard_LRS'
param tags object = {}

var funcStorageName = toLower(replace('${baseName}funcstore', '-', ''))
var cleaned = replace(replace(funcStorageName, '_', ''), '.', '')
var storageName = length(cleaned) > 24 ? substring(cleaned, 0, 24) : cleaned

resource funcStorage 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: storageName
  location: location
  sku: { name: sku }
  kind: 'StorageV2'
  properties: {
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
    supportsHttpsTrafficOnly: true
    isHnsEnabled: false // classic storage for function internal usage
  }
  tags: tags
}

output functionStorageAccountName string = funcStorage.name
