# Azure SQL Database + Power BI setup

Stand up a low-cost Azure SQL Database, load data into it, and connect Power BI.
The flow: **deploy → create the sample table → connect Power BI → load your real data**.

## What gets created

| File | Purpose |
|------|---------|
| `main.bicep` | Infrastructure: a logical SQL server + a **serverless** SQL database (auto-pauses when idle, so you mostly pay only while in use) and firewall rules. |
| `deploy.sh` | One command to provision everything with the Azure CLI. |
| `schema.sql` | A `sales` sample table with a few rows so you can prove the path works before touching your own data. |
| `load_data.py` | Cleans a messy CSV/Excel file and loads it into a table. |

## Prerequisites

- An Azure subscription
- [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli): `az login`
- [`sqlcmd`](https://learn.microsoft.com/sql/tools/sqlcmd/sqlcmd-utility) (to run `schema.sql`)
- For the loader: Python 3, the [ODBC Driver 18 for SQL Server](https://learn.microsoft.com/sql/connect/odbc/download-odbc-driver-for-sql-server), and
  `pip install pandas sqlalchemy "pyodbc>=5" openpyxl`
- [Power BI Desktop](https://powerbi.microsoft.com/desktop/) (free)

---

## Step 1 — Deploy the database

```bash
cd azure
./deploy.sh
```

It prompts for an admin password, auto-detects your public IP for the firewall, and
prints the **server name**, **database**, and **login** at the end. Keep those.

> Cost note: the serverless tier auto-pauses after 60 min idle. While paused you pay
> only for storage (a few cents/day for a small DB). It auto-resumes on the next query
> — the first one after a pause takes a few extra seconds.

## Step 2 — Create the sample table

```bash
sqlcmd -S <server>.database.windows.net -d analytics -U sqladmin -P '<password>' -i schema.sql
```

This is the "make sure everything works" step before involving your own data.

## Step 3 — Connect Power BI

1. Open **Power BI Desktop** → **Home → Get data → Azure → Azure SQL database**.
2. **Server:** `<server>.database.windows.net`  **Database:** `analytics`.
3. Choose **Import** (snapshots the data, fastest) or **DirectQuery** (always live).
4. Sign in with **Database** authentication → your `sqladmin` login + password.
5. Pick the `sales` table → **Load**. Build a chart (e.g. `amount` by `region`).

If Power BI can't connect, it's almost always the firewall — add the IP it reports in
the Azure portal under **SQL server → Networking → Firewall rules**.

## Step 4 — Load your real data

Preview the cleaning first (no upload, no connection needed):

```bash
python load_data.py "Q1 numbers.xlsx" --table sales --dry-run
```

Then load for real:

```bash
export SQLPASSWORD='<password>'
python load_data.py "Q1 numbers.xlsx" --table sales \
    --server <server>.database.windows.net --database analytics --user sqladmin \
    --if-exists append          # or: replace
```

Back in Power BI, **Home → Refresh** to pull the new rows.

---

## Cleaning messy spreadsheets

`load_data.py` applies the fixes spreadsheets almost always need before they belong in
a database. Run with `--dry-run` to see exactly what it did:

| Mess in the spreadsheet | What the loader does |
|-------------------------|----------------------|
| Blank rows / columns, stray `Unnamed: 3` columns | Dropped automatically. |
| Header like `"Total Sales (£)"` | Normalised to a SQL-safe name → `total_sales`. |
| Two columns both named `Total` | De-duplicated → `total`, `total_2`. |
| Leading/trailing spaces, empty strings | Trimmed; empty strings become real `NULL`s. |
| Numbers/dates stored as text | Re-typed so Power BI treats them as numbers/dates (needed for sums, time charts). |
| Exact duplicate rows | Removed. |

What it deliberately does **not** guess (these need a human decision):

- **Merged cells / multi-row headers** — flatten these in Excel first so row 1 is a
  single clean header row.
- **Inconsistent categories** — `"North"`, `"north "`, `"N."` won't be merged
  automatically. Standardise key columns, or do it later in Power BI's Power Query editor.
- **Multiple tables on one sheet** — split them into separate sheets/files first; one
  table per file.
- **Units mixed in a value column** — e.g. `"5kg"` vs `"5"`. Decide on one unit and
  strip the text.

A good rule of thumb: get each file to **one header row + one table + one topic**, then
let the loader handle the mechanical cleanup. For ongoing/repeatable transforms, Power
BI's **Power Query** editor (Transform data) records your steps and re-applies them on
every refresh — ideal once your structure settles.
