param baseName string
param location string
param enableLogAnalytics bool = true
param tags object = {}

var aiName = toLower('${baseName}-ai')
var lawName = toLower('${baseName}-law')

resource ai 'Microsoft.Insights/components@2020-02-02' = {
  name: aiName
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    // Add properties that Azure sets automatically to avoid perpetual what-if drift
    Flow_Type: 'Bluefield'
    Request_Source: 'rest'
  }
  tags: tags
}

resource law 'Microsoft.OperationalInsights/workspaces@2022-10-01' = if (enableLogAnalytics) {
  name: lawName
  location: location
  // Align with service response shape to prevent drift (sku & retention inside properties)
  properties: {
    retentionInDays: 30
    sku: {
      name: 'PerGB2018'
    }
  }
  tags: tags
}

output appInsightsConnectionString string = ai.properties.ConnectionString
output appInsightsInstrumentationKey string = ai.properties.InstrumentationKey
output logAnalyticsWorkspaceId string = enableLogAnalytics ? law.id : ''
