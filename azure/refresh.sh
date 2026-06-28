#!/usr/bin/env bash
# Reload the master spreadsheet into Azure SQL (macOS/Linux version of refresh.bat).
#
# The database becomes an exact mirror of the file (full reload via
# --if-exists replace), so adding rows to the file each period and running this
# keeps the DB current with no duplicate risk.
#
# Requires: refresh.config (copy from refresh.config.example) and the
# SQLPASSWORD environment variable. Schedule with cron for auto-refresh.
set -euo pipefail
cd "$(dirname "$0")"

if [[ ! -f refresh.config ]]; then
  echo "[ERROR] refresh.config not found. Copy refresh.config.example to refresh.config and edit it." >&2
  exit 1
fi

# shellcheck disable=SC1091
source refresh.config

if [[ -z "${SQLPASSWORD:-}" ]]; then
  echo "[ERROR] SQLPASSWORD environment variable is not set." >&2
  exit 1
fi

echo "Reloading \"$DATA_FILE\" into $DATABASE.$TABLE ..."
python3 load_data.py "$DATA_FILE" \
  --table "$TABLE" \
  --server "$SERVER" \
  --database "$DATABASE" \
  --user "$DB_USER" \
  --if-exists replace

echo "Done. Refresh your Power BI report to see the latest data."
