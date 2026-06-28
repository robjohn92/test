#!/usr/bin/env python3
"""Clean a messy CSV/Excel file and load it into Azure SQL Database.

This handles the cleanup that real-world spreadsheets almost always need before
they belong in a database, then creates (or appends to) a table.

Cleaning steps applied (each can be toggled with a flag):
  * Drop fully-empty rows and columns
  * Strip leading/trailing whitespace from headers and text cells
  * Normalise column names -> snake_case, safe for SQL (no spaces/symbols)
  * De-duplicate column names (e.g. two "Total" columns -> total, total_2)
  * Trim trailing "Unnamed: N" junk columns Excel often adds
  * Infer better types (numbers, dates) instead of everything-is-text
  * Drop exact duplicate rows

Usage:
  pip install pandas sqlalchemy "pyodbc>=5" openpyxl

  python load_data.py messy.xlsx --table sales \
      --server myserver.database.windows.net \
      --database analytics --user sqladmin

  # password is read from the SQLPASSWORD env var or prompted for
  # add --dry-run to preview the cleaned data WITHOUT uploading

Requires the Microsoft ODBC Driver 18 for SQL Server on the machine running this.
"""
from __future__ import annotations

import argparse
import getpass
import os
import re
import sys
import urllib.parse

import pandas as pd


# --------------------------------------------------------------------------- #
# Cleaning
# --------------------------------------------------------------------------- #
def snake_case(name: str) -> str:
    """'  Total Sales (£) ' -> 'total_sales'."""
    name = str(name).strip().lower()
    name = re.sub(r"[^\w\s]", "", name)      # drop punctuation/symbols
    name = re.sub(r"\s+", "_", name)         # spaces -> underscores
    name = re.sub(r"_+", "_", name).strip("_")
    return name or "col"


def dedupe_columns(cols: list[str]) -> list[str]:
    """Make column names unique: ['total', 'total'] -> ['total', 'total_2']."""
    seen: dict[str, int] = {}
    out = []
    for c in cols:
        if c in seen:
            seen[c] += 1
            out.append(f"{c}_{seen[c]}")
        else:
            seen[c] = 1
            out.append(c)
    return out


def clean(df: pd.DataFrame) -> pd.DataFrame:
    # 1. Drop the "Unnamed: N" columns Excel adds for stray formatting.
    df = df.loc[:, ~df.columns.astype(str).str.match(r"^Unnamed:\s*\d+$")]

    # 2. Drop fully-empty rows and columns.
    df = df.dropna(axis=0, how="all").dropna(axis=1, how="all")

    # 3. Strip whitespace from every text cell.
    for col in df.select_dtypes(include="object"):
        df[col] = df[col].map(lambda v: v.strip() if isinstance(v, str) else v)
        # Turn empty strings into proper nulls.
        df[col] = df[col].replace({"": None})

    # 4. Normalise + de-duplicate headers.
    df.columns = dedupe_columns([snake_case(c) for c in df.columns])

    # 5. Let pandas re-infer numbers/dates that arrived as text.
    df = df.convert_dtypes()
    for col in df.select_dtypes(include="object"):
        parsed = pd.to_datetime(df[col], errors="coerce", dayfirst=True)
        # Only convert if it parses cleanly for most non-null values.
        non_null = df[col].notna().sum()
        if non_null and parsed.notna().sum() >= 0.8 * non_null:
            df[col] = parsed

    # 6. Drop exact duplicate rows.
    df = df.drop_duplicates().reset_index(drop=True)
    return df


# --------------------------------------------------------------------------- #
# Load
# --------------------------------------------------------------------------- #
def read_any(path: str) -> pd.DataFrame:
    if path.lower().endswith((".xlsx", ".xls")):
        return pd.read_excel(path)
    return pd.read_csv(path)


def make_engine(server: str, database: str, user: str, password: str):
    from sqlalchemy import create_engine

    odbc = (
        "Driver={ODBC Driver 18 for SQL Server};"
        f"Server=tcp:{server},1433;"
        f"Database={database};"
        f"Uid={user};Pwd={password};"
        "Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"
    )
    return create_engine(
        "mssql+pyodbc:///?odbc_connect=" + urllib.parse.quote_plus(odbc)
    )


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("file", help="Path to the .csv / .xlsx file")
    p.add_argument("--table", required=True, help="Destination table name")
    p.add_argument("--server", help="<name>.database.windows.net")
    p.add_argument("--database", help="Database name")
    p.add_argument("--user", help="SQL admin login")
    p.add_argument("--if-exists", choices=["fail", "replace", "append"],
                   default="append", help="What to do if the table exists (default: append)")
    p.add_argument("--dry-run", action="store_true",
                   help="Clean and preview only; do not connect or upload")
    args = p.parse_args()

    print(f"Reading {args.file} ...")
    raw = read_any(args.file)
    print(f"  raw shape: {raw.shape[0]} rows x {raw.shape[1]} cols")

    cleaned = clean(raw)
    print(f"  cleaned  : {cleaned.shape[0]} rows x {cleaned.shape[1]} cols")
    print("\nColumns and inferred types:")
    print(cleaned.dtypes.to_string())
    print("\nPreview:")
    print(cleaned.head(10).to_string(index=False))

    if args.dry_run:
        print("\n[dry-run] Not uploading. Re-run without --dry-run to load.")
        return 0

    for req in ("server", "database", "user"):
        if not getattr(args, req):
            p.error(f"--{req} is required unless --dry-run is set")

    password = os.environ.get("SQLPASSWORD") or getpass.getpass("SQL password: ")
    engine = make_engine(args.server, args.database, args.user, password)

    print(f"\nUploading to {args.database}.dbo.{args.table} (if_exists={args.if_exists}) ...")
    cleaned.to_sql(args.table, engine, schema="dbo",
                   if_exists=args.if_exists, index=False, chunksize=1000)
    print("Done. Refresh the data in Power BI to see the new rows.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
