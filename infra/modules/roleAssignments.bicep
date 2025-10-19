@description('Principal (managed identity) object id to assign role to')
param principalId string
@description('Target storage account name for data access')
param storageAccountName string
@description('Target Key Vault name for secret access')
param keyVaultName string

@description('Assign Storage Blob Data Contributor to Function managed identity')
resource storage 'Microsoft.Storage/storageAccounts@2023-01-01' existing = {
  name: storageAccountName
}

// Use uniqueString on static scope + constant seed to keep name stable yet avoid dependency on runtime reference object shape.
@description('Assign Storage Blob Data Contributor role')
resource storageBlobDataContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  // Deterministic GUID: based on subscription + storage scope + constant seed
  name: guid(subscription().id, storage.id, 'blobdatacontrib')
  scope: storage
  properties: {
    principalId: principalId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'ba92f5b4-2d11-453d-a403-e96b0029c9fe')
    principalType: 'ServicePrincipal'
  }
}

// Reference Key Vault for role assignment
resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: keyVaultName
}


// Assign Key Vault Secrets User role to Function managed identity (read/list secrets)
resource keyVaultSecretsUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(subscription().id, keyVault.id, 'secretsuser')
  scope: keyVault
  properties: {
    principalId: principalId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '4633458b-17de-408a-b874-0445c86b69e6')
    principalType: 'ServicePrincipal'
  }
}

// Assign Key Vault Secrets Officer role to Function managed identity (read/write secrets)
resource keyVaultSecretsOfficer 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(subscription().id, keyVault.id, 'secretsofficer')
  scope: keyVault
  properties: {
    principalId: principalId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'b86a8fe4-44ce-4948-aee5-eccb2c155cd7')
    principalType: 'ServicePrincipal'
  }
}

output roleAssignmentName string = storageBlobDataContributor.name
output keyVaultRoleAssignmentName string = keyVaultSecretsUser.name
