#!/usr/bin/env bash
# Provision the Azure SQL Database from azure/main.bicep.
#
# Prerequisites:
#   * Azure CLI installed and logged in:  az login
#   * Bicep:  az bicep install   (one-time)
#
# Usage:
#   ./deploy.sh
# then follow the prompts (or set the env vars below first).

set -euo pipefail

# ---- Settings (override via environment variables) -------------------------
RESOURCE_GROUP="${RESOURCE_GROUP:-rg-analytics}"
LOCATION="${LOCATION:-uksouth}"
SQL_SERVER_NAME="${SQL_SERVER_NAME:-}"          # must be globally unique
SQL_DATABASE_NAME="${SQL_DATABASE_NAME:-analytics}"
ADMIN_LOGIN="${ADMIN_LOGIN:-sqladmin}"
# ---------------------------------------------------------------------------

if [[ -z "$SQL_SERVER_NAME" ]]; then
  # default to a unique-ish name; change if you like
  SQL_SERVER_NAME="sql-analytics-$RANDOM"
fi

echo "Resource group : $RESOURCE_GROUP ($LOCATION)"
echo "SQL server     : $SQL_SERVER_NAME"
echo "Database       : $SQL_DATABASE_NAME"
echo "Admin login    : $ADMIN_LOGIN"
echo

# Password: read from env or prompt (never echoed, never stored in a file).
if [[ -z "${ADMIN_PASSWORD:-}" ]]; then
  read -rsp "Choose an admin password (min 8 chars, upper+lower+number+symbol): " ADMIN_PASSWORD
  echo
fi

# Detect this machine's public IP so we can connect to load data + run Power BI Desktop.
CLIENT_IP="$(curl -s https://api.ipify.org || true)"
echo "Detected client IP: ${CLIENT_IP:-<none, add manually later>}"
echo

az group create --name "$RESOURCE_GROUP" --location "$LOCATION" --output none

az deployment group create \
  --resource-group "$RESOURCE_GROUP" \
  --template-file "$(dirname "$0")/main.bicep" \
  --parameters \
      sqlServerName="$SQL_SERVER_NAME" \
      sqlDatabaseName="$SQL_DATABASE_NAME" \
      administratorLogin="$ADMIN_LOGIN" \
      administratorLoginPassword="$ADMIN_PASSWORD" \
      clientIpAddress="$CLIENT_IP" \
  --output table

FQDN="$(az sql server show --name "$SQL_SERVER_NAME" --resource-group "$RESOURCE_GROUP" --query fullyQualifiedDomainName -o tsv)"

echo
echo "================================================================"
echo " Done. Connection details for Power BI / sqlcmd / the loader:"
echo "   Server   : $FQDN"
echo "   Database : $SQL_DATABASE_NAME"
echo "   Login    : $ADMIN_LOGIN"
echo
echo " Next: load the sample schema —"
echo "   sqlcmd -S $FQDN -d $SQL_DATABASE_NAME -U $ADMIN_LOGIN -P '<password>' -i azure/schema.sql"
echo "================================================================"
