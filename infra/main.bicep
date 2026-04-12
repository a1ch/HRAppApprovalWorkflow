// hr-approval-func — Azure infrastructure
// Deploys: Function App, Storage Account, App Service Plan, Key Vault, App Insights
// Run: az deployment group create --resource-group <rg> --template-file main.bicep --parameters @params.json

@description('Base name for all resources, e.g. streamflo-hr')
param baseName string = 'streamflo-hr'

@description('Azure region')
param location string = resourceGroup().location

@description('SharePoint site URL')
param spSiteUrl string

@description('SharePoint list name')
param spListName string = 'HRApprovalRequests'

@description('Sender email address (shared mailbox)')
param mailSenderAddress string

@description('Approval base URL — the Function App URL, filled after first deploy')
param approvalBaseUrl string = ''

// ── Storage Account ──────────────────────────────────────────────────────
resource storage 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: replace('${baseName}stor', '-', '')
  location: location
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: {
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
    supportsHttpsTrafficOnly: true
  }
}

// ── App Insights ─────────────────────────────────────────────────────────
resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2022-10-01' = {
  name: '${baseName}-logs'
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 90
  }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: '${baseName}-ai'
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logAnalytics.id
  }
}

// ── App Service Plan (Consumption / Serverless) ───────────────────────────
resource plan 'Microsoft.Web/serverfarms@2023-01-01' = {
  name: '${baseName}-plan'
  location: location
  sku: { name: 'Y1', tier: 'Dynamic' }
  kind: 'functionapp'
  properties: { reserved: true }  // Linux
}

// ── Function App ──────────────────────────────────────────────────────────
resource funcApp 'Microsoft.Web/sites@2023-01-01' = {
  name: '${baseName}-func'
  location: location
  kind: 'functionapp,linux'
  identity: { type: 'SystemAssigned' }
  properties: {
    serverFarmId: plan.id
    siteConfig: {
      linuxFxVersion: 'Python|3.11'
      pythonVersion: '3.11'
      appSettings: [
        { name: 'AzureWebJobsStorage', value: 'DefaultEndpointsProtocol=https;AccountName=${storage.name};AccountKey=${storage.listKeys().keys[0].value}' }
        { name: 'FUNCTIONS_EXTENSION_VERSION', value: '~4' }
        { name: 'FUNCTIONS_WORKER_RUNTIME', value: 'python' }
        { name: 'APPINSIGHTS_INSTRUMENTATIONKEY', value: appInsights.properties.InstrumentationKey }
        { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsights.properties.ConnectionString }
        { name: 'SP_SITE_URL', value: spSiteUrl }
        { name: 'SP_LIST_NAME', value: spListName }
        { name: 'MAIL_SENDER_ADDRESS', value: mailSenderAddress }
        { name: 'APPROVAL_BASE_URL', value: approvalBaseUrl }
        // Secrets below — store in Key Vault references in production:
        // { name: 'SP_TENANT_ID',     value: '@Microsoft.KeyVault(SecretUri=...)' }
        // { name: 'SP_CLIENT_ID',     value: '@Microsoft.KeyVault(SecretUri=...)' }
        // { name: 'SP_CLIENT_SECRET', value: '@Microsoft.KeyVault(SecretUri=...)' }
        // Role email addresses:
        // { name: 'EMAIL_HR_MANAGER',         value: 'rlperkins@streamflo.com' }
        // { name: 'EMAIL_PAYROLL_MANAGER',     value: 'gthedford@streamflo.com' }
        // { name: 'EMAIL_BENEFITS_SPECIALIST', value: 'scarrisalez@streamflo.com' }
        // { name: 'EMAIL_HR_GENERALIST',       value: 'tparashar@streamflo.com' }
      ]
      ftpsState: 'Disabled'
      minTlsVersion: '1.2'
    }
    httpsOnly: true
  }
}

// ── Key Vault ─────────────────────────────────────────────────────────────
resource kv 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: '${baseName}-kv'
  location: location
  properties: {
    sku: { family: 'A', name: 'standard' }
    tenantId: subscription().tenantId
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 90
  }
}

// Grant Function App managed identity access to Key Vault secrets
resource kvRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(kv.id, funcApp.id, 'Key Vault Secrets User')
  scope: kv
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '4633458b-17de-408a-b874-0445c86b69e6')
    principalId: funcApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

output functionAppName string = funcApp.name
output functionAppUrl string = 'https://${funcApp.properties.defaultHostName}'
output keyVaultName string = kv.name
output appInsightsName string = appInsights.name
