"""
Download daily Spanish electricity data from Red Eléctrica (REData API)
and save it as CSV files plus a SQLite database for SQL practice.

No API key is needed. Run on your own computer:
    pip install requests pandas
    python ree_download.py

Output:
    data/raw/demand_daily.csv
    data/raw/generation_daily.csv
    data/raw/prices_daily.csv
    data/energy.db   (tables: demand, generation, prices)
"""

import sqlite3
import time
from pathlib import Path

import pandas as pd
import requests

BASE_URL = "https://apidatos.ree.es/en/datos"
START_YEAR = 2019
END_YEAR = 2025

# (category, widget, output table name)
DATASETS = [
    ("demanda", "evolucion", "demand"),
    ("generacion", "estructura-generacion", "generation"),
    ("mercados", "precios-mercados-tiempo-real", "prices"),
]

DATA_DIR = Path("data")
RAW_DIR = DATA_DIR / "raw"


def month_ranges(start_year: int, end_year: int):
    """Yield (start, end) strings for every month, so each request stays small."""
    for start in pd.date_range(f"{start_year}-01-01", f"{end_year}-12-01", freq="MS"):
        end = start + pd.offsets.MonthEnd(0)
        yield start.strftime("%Y-%m-%dT00:00"), end.strftime("%Y-%m-%dT23:59")


def fetch(category: str, widget: str, start: str, end: str) -> list[dict]:
    """Call the API once and flatten the JSON into rows."""
    url = f"{BASE_URL}/{category}/{widget}"
    params = {"start_date": start, "end_date": end, "time_trunc": "day"}
    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()

    rows = []
    for series in response.json().get("included", []):
        attrs = series.get("attributes", {})
        for point in attrs.get("values", []):
            rows.append(
                {
                    "date": point["datetime"][:10],
                    "series": attrs.get("title"),
                    "type": attrs.get("type"),  # e.g. Renovable / No-Renovable
                    "value": point["value"],
                }
            )
    return rows


def download(category: str, widget: str) -> pd.DataFrame:
    all_rows = []
    for start, end in month_ranges(START_YEAR, END_YEAR):
        try:
            all_rows.extend(fetch(category, widget, start, end))
            print(f"  {widget}: {start[:7]} ok")
        except requests.RequestException as err:
            print(f"  {widget}: {start[:7]} FAILED ({err})")
        time.sleep(0.5)  # be polite to the server
    return pd.DataFrame(all_rows)


def main():
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DATA_DIR / "energy.db")

    for category, widget, table in DATASETS:
        print(f"Downloading {table} ...")
        df = download(category, widget)
        if df.empty:
            print(f"  No data for {table}, skipping.")
            continue
        df.to_csv(RAW_DIR / f"{table}_daily.csv", index=False)
        df.to_sql(table, con, if_exists="replace", index=False)
        print(f"  Saved {len(df):,} rows -> {table}")

    con.close()
    print("Done.")


if __name__ == "__main__":
    main()
