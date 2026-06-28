// Azure SQL Database — serverless, low-cost setup for Power BI.
//
// Deploys:
//   * A logical SQL Server (the host/endpoint)
//   * A serverless SQL Database (auto-pauses when idle so you only pay while in use)
//   * Firewall rules so Azure services (incl. Power BI) and your own IP can connect
//
// Deploy with azure/deploy.sh (which wraps `az deployment group create`).

@description('Azure region, e.g. uksouth, eastus. Defaults to the resource group location.')
param location string = resourceGroup().location

@description('Globally-unique name for the logical SQL server (lowercase letters, numbers, hyphens).')
param sqlServerName string

@description('Name of the database to create.')
param sqlDatabaseName string = 'analytics'

@description('Admin username for the SQL server.')
param administratorLogin string

@description('Admin password. Min 8 chars, mix of upper/lower/number/symbol. Passed in at deploy time, never stored in the template.')
@secure()
param administratorLoginPassword string

@description('Your current public IP so you can connect from this machine. Leave blank to skip (you can add it later in the portal).')
param clientIpAddress string = ''

resource sqlServer 'Microsoft.Sql/servers@2023-08-01-preview' = {
  name: sqlServerName
  location: location
  properties: {
    administratorLogin: administratorLogin
    administratorLoginPassword: administratorLoginPassword
    minimalTlsVersion: '1.2'
    publicNetworkAccess: 'Enabled'
  }
}

resource sqlDatabase 'Microsoft.Sql/servers/databases@2023-08-01-preview' = {
  parent: sqlServer
  name: sqlDatabaseName
  location: location
  sku: {
    // Serverless General Purpose, 1 vCore max. Cheapest tier that Power BI talks to happily.
    name: 'GP_S_Gen5_1'
    tier: 'GeneralPurpose'
  }
  properties: {
    autoPauseDelay: 60          // pause after 60 min idle -> compute billing stops
    minCapacity: json('0.5')    // scales down to 0.5 vCore
    maxSizeBytes: 34359738368   // 32 GB
    zoneRedundant: false
  }
}

// Lets Azure-internal services (including the Power BI service) reach the server.
resource allowAzureServices 'Microsoft.Sql/servers/firewallRules@2023-08-01-preview' = {
  parent: sqlServer
  name: 'AllowAllAzureIPs'
  properties: {
    startIpAddress: '0.0.0.0'
    endIpAddress: '0.0.0.0'
  }
}

// Lets your own machine connect (for loading data and Power BI Desktop). Only created if an IP was supplied.
resource allowClientIp 'Microsoft.Sql/servers/firewallRules@2023-08-01-preview' = if (!empty(clientIpAddress)) {
  parent: sqlServer
  name: 'AllowClientIP'
  properties: {
    startIpAddress: clientIpAddress
    endIpAddress: clientIpAddress
  }
}

@description('Server endpoint to use in Power BI / connection strings.')
output sqlServerFqdn string = sqlServer.properties.fullyQualifiedDomainName
@description('Database name.')
output databaseName string = sqlDatabase.name
