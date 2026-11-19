"""
Download Spanish electricity prices from REE (REData API).

This endpoint only accepts hourly data (time_trunc=hour) and at most
about 7 days per request, so we ask week by week and then average the
hours into daily prices.

Progress is saved after every year, and already downloaded weeks are
skipped, so if it stops you can simply run it again to continue.

Run:  python prices_download.py
Output: data/raw/prices_daily.csv   (date, series, type, value = daily mean €/MWh)
"""

import time
from pathlib import Path

import pandas as pd
import requests

URL = "https://apidatos.ree.es/en/datos/mercados/precios-mercados-tiempo-real"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "Accept": "application/json",
}
HOURLY = Path("data/raw/prices_hourly.csv")
DAILY = Path("data/raw/prices_daily.csv")


def fetch_week(start, end):
    params = {"start_date": start, "end_date": end, "time_trunc": "hour"}
    for attempt in range(1, 4):
        r = requests.get(URL, params=params, headers=HEADERS, timeout=30)
        if r.status_code == 200:
            rows = []
            for s in r.json().get("included", []):
                a = s.get("attributes", {})
                for v in a.get("values", []):
                    rows.append({"datetime": v["datetime"][:16], "series": a.get("title"),
                                 "value": v["value"]})
            return rows
        if r.status_code == 400:          # bad request: retrying will not help
            print(f"    {start[:10]}: HTTP 400, skipped")
            return []
        wait = 20 * attempt               # 403/429/5xx: server busy or blocking
        print(f"    {start[:10]}: HTTP {r.status_code}, waiting {wait}s")
        time.sleep(wait)
    return None


def main():
    HOURLY.parent.mkdir(parents=True, exist_ok=True)
    old = pd.read_csv(HOURLY) if HOURLY.exists() else pd.DataFrame(columns=["datetime", "series", "value"])
    done = set(old["datetime"].str[:10])
    rows, fails = [], 0

    weeks = pd.date_range("2019-01-01", "2025-12-31", freq="7D")
    for i, w in enumerate(weeks):
        end_day = min(w + pd.Timedelta(days=6), pd.Timestamp("2025-12-31"))
        if w.strftime("%Y-%m-%d") in done and end_day.strftime("%Y-%m-%d") in done:
            continue
        got = fetch_week(w.strftime("%Y-%m-%dT00:00"), end_day.strftime("%Y-%m-%dT23:59"))
        if got is None:
            fails += 1
            if fails >= 3:
                print("\nServer keeps refusing. Progress saved; run the script again later to continue.")
                break
            continue
        fails = 0
        rows.extend(got)
        if w.month == 1 and w.day <= 7 or i % 10 == 0:
            print(f"  up to {end_day.date()} ok")
        if i % 52 == 51:                  # save progress about once a year of data
            pd.concat([old, pd.DataFrame(rows)]).to_csv(HOURLY, index=False)
        time.sleep(1)

    hourly = pd.concat([old, pd.DataFrame(rows)]).drop_duplicates(["datetime", "series"])
    hourly.to_csv(HOURLY, index=False)

    daily = (hourly.assign(date=hourly["datetime"].str[:10])
                   .groupby(["date", "series"], as_index=False)["value"].mean())
    daily["type"] = None
    daily[["date", "series", "type", "value"]].to_csv(DAILY, index=False)
    print(f"\nSaved {daily['date'].nunique():,} days "
          f"({daily['date'].min()} to {daily['date'].max()}) to {DAILY}")


if __name__ == "__main__":
    main()
