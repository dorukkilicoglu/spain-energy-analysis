"""
Spain Electricity Market Analysis (2019-2025)

Steps:
  1. Load raw REData CSVs (from ree_download.py)
  2. Clean them into one tidy daily table and store it in SQLite
  3. Run the SQL queries in sql/analysis.sql and save the results
  4. Make charts and a regression of price on wind + solar share
  5. Write output/findings.md with the key numbers

Run:  python analysis.py
"""

import re
import sqlite3
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression

RAW = Path("data/raw")
DB = Path("data/energy.db")
OUT = Path("output")
FIG = OUT / "figures"

plt.rcParams.update({
    "figure.dpi": 150, "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.alpha": 0.3, "font.size": 10,
})
BLUE, GREEN, ORANGE, GREY = "#2E5EAA", "#3A9D5D", "#E07B39", "#8A8A8A"


# ---------------------------------------------------------------- 1. load & clean
def has(text, *words):
    text = str(text).lower()
    return any(w in text for w in words)


def is_renewable(type_value):
    t = str(type_value).lower()
    return ("renov" in t or "renew" in t) and not ("no-" in t or "non" in t or "no " in t)


def build_daily() -> pd.DataFrame:
    demand = pd.read_csv(RAW / "demand_daily.csv", parse_dates=["date"])
    gen = pd.read_csv(RAW / "generation_daily.csv", parse_dates=["date"])
    prices = pd.read_csv(RAW / "prices_daily.csv", parse_dates=["date"])

    # Demand: one series; MWh -> GWh
    d = demand.groupby("date")["value"].sum().div(1000).rename("demand_gwh")

    # Generation: drop the "total" row and sum technologies ourselves
    gen = gen[~gen["series"].apply(has, args=("total",))]
    g = pd.DataFrame({
        "generation_gwh": gen.groupby("date")["value"].sum(),
        "renewable_gwh": gen[gen["type"].apply(is_renewable)].groupby("date")["value"].sum(),
        "wind_gwh": gen[gen["series"].apply(has, args=("wind", "eólica"))].groupby("date")["value"].sum(),
        "solar_gwh": gen[gen["series"].apply(has, args=("solar",))].groupby("date")["value"].sum(),
    }).fillna(0).div(1000)

    # Prices: prefer the wholesale spot price, fall back to PVPC
    spot = prices[prices["series"].apply(has, args=("spot", "mercado", "market"))]
    p_src = spot if not spot.empty else prices[prices["series"].apply(has, args=("pvpc",))]
    p = p_src.groupby("date")["value"].mean().rename("price_eur_mwh")

    daily = pd.concat([d, g, p], axis=1).dropna().sort_index()
    daily["renewable_share"] = daily["renewable_gwh"] / daily["generation_gwh"]
    daily["wind_solar_share"] = (daily["wind_gwh"] + daily["solar_gwh"]) / daily["generation_gwh"]
    daily.index.name = "date"

    print(f"Price series used: {sorted(p_src['series'].unique())}")
    print(f"Daily table: {len(daily):,} days, {daily.index.min().date()} to {daily.index.max().date()}")
    return daily


# ---------------------------------------------------------------- 2-3. SQL
def run_sql(daily: pd.DataFrame) -> dict:
    con = sqlite3.connect(DB)
    out = daily.reset_index()
    out["date"] = out["date"].dt.strftime("%Y-%m-%d")
    out.to_sql("daily", con, if_exists="replace", index=False)

    text = Path("sql/analysis.sql").read_text(encoding="utf-8")
    results = {}
    for block in re.split(r"(?m)^-- name:\s*", text)[1:]:
        name, _, query = block.partition("\n")
        results[name.strip()] = pd.read_sql_query(query, con)
    con.close()

    with open(OUT / "sql_results.md", "w", encoding="utf-8") as f:
        f.write("# SQL query results\n\n")
        for name, df in results.items():
            f.write(f"## {name}\n\n{df.to_markdown(index=False)}\n\n")
    return results


# ---------------------------------------------------------------- 4. charts
def save(fig, name):
    fig.tight_layout()
    fig.savefig(FIG / name)
    plt.close(fig)


def charts(daily: pd.DataFrame, r: dict):
    # Yearly demand
    y = r["yearly_demand"]
    fig, ax = plt.subplots(figsize=(7, 3.8))
    ax.bar(y["year"], y["demand_gwh"] / 1000, color=BLUE)
    ax.set_title("Annual electricity demand in Spain")
    ax.set_ylabel("TWh")
    for x, v in zip(y["year"], y["demand_gwh"] / 1000):
        ax.text(x, v, f"{v:.0f}", ha="center", va="bottom")
    save(fig, "01_yearly_demand.png")

    # Generation mix
    s = r["yearly_renewable_share"]
    fig, ax = plt.subplots(figsize=(7, 3.8))
    ax.plot(s["year"], s["renewable_pct"], marker="o", color=GREEN, label="All renewables")
    ax.plot(s["year"], s["wind_solar_pct"], marker="o", color=ORANGE, label="Wind + solar")
    ax.plot(s["year"], s["solar_pct"], marker="o", color=GREY, label="Solar")
    ax.set_title("Share of electricity generation")
    ax.set_ylabel("%")
    ax.legend(frameon=False)
    save(fig, "02_renewable_share.png")

    # Price over time with 30-day rolling mean
    fig, ax = plt.subplots(figsize=(9, 3.8))
    ax.plot(daily.index, daily["price_eur_mwh"], color=BLUE, alpha=0.25, lw=0.7, label="Daily")
    ax.plot(daily.index, daily["price_eur_mwh"].rolling(30).mean(), color=BLUE, lw=1.8, label="30-day average")
    ax.set_title("Daily wholesale electricity price")
    ax.set_ylabel("€/MWh")
    ax.legend(frameon=False)
    save(fig, "03_price_timeline.png")

    # Price vs wind + solar share (2023+)
    recent = daily[daily.index >= "2023-01-01"]
    fig, ax = plt.subplots(figsize=(6.5, 4.5))
    sc = ax.scatter(100 * recent["wind_solar_share"], recent["price_eur_mwh"],
                    c=recent.index.month, cmap="twilight", s=10, alpha=0.7)
    ax.set_title("Price vs wind + solar share (2023 onward)")
    ax.set_xlabel("Wind + solar share of generation (%)")
    ax.set_ylabel("€/MWh")
    fig.colorbar(sc, ax=ax, label="Month")
    save(fig, "04_price_vs_wind_solar.png")

    # Bucket comparison
    b = r["price_by_wind_solar_bucket"]
    fig, ax = plt.subplots(figsize=(6.5, 3.8))
    ax.bar(b["wind_solar_bucket"].str[3:], b["avg_price"], color=GREEN)
    for i, v in enumerate(b["avg_price"]):
        ax.text(i, v, f"{v:.0f}", ha="center", va="bottom")
    ax.set_title("Average price by wind + solar share (2023 onward)")
    ax.set_xlabel("Wind + solar share of the day's generation")
    ax.set_ylabel("€/MWh")
    save(fig, "05_price_by_bucket.png")

    # Seasonality
    m = r["price_by_month_of_year"]
    fig, ax1 = plt.subplots(figsize=(7, 3.8))
    ax1.bar(m["month"], m["avg_price"], color=BLUE, alpha=0.8)
    ax1.set_ylabel("Average price (€/MWh)", color=BLUE)
    ax2 = ax1.twinx()
    ax2.plot(m["month"], m["avg_wind_solar_pct"], color=ORANGE, marker="o")
    ax2.set_ylabel("Wind + solar share (%)", color=ORANGE)
    ax2.grid(False)
    ax1.set_xticks(range(1, 13))
    ax1.set_title("Seasonality: price and wind + solar share by month (excl. 2022)")
    save(fig, "06_seasonality.png")


# ---------------------------------------------------------------- regression
def regression(daily: pd.DataFrame) -> dict:
    """Price ~ wind+solar share + demand + month dummies, on 2023+ data."""
    d = daily[daily.index >= "2023-01-01"].copy()
    X = pd.get_dummies(d.index.month, prefix="m", drop_first=True).astype(float)
    X.index = d.index
    X.insert(0, "demand_gwh", d["demand_gwh"])
    X.insert(0, "wind_solar_pp", 100 * d["wind_solar_share"])  # per percentage point
    model = LinearRegression().fit(X, d["price_eur_mwh"])
    return {
        "per_pp": model.coef_[0],
        "per_10pp": 10 * model.coef_[0],
        "per_100gwh_demand": 100 * model.coef_[1],
        "r2": model.score(X, d["price_eur_mwh"]),
        "corr": np.corrcoef(d["wind_solar_share"], d["price_eur_mwh"])[0, 1],
        "n": len(d),
    }


# ---------------------------------------------------------------- 5. findings
def findings(r: dict, reg: dict):
    y, s, p, b = (r["yearly_demand"], r["yearly_renewable_share"],
                  r["yearly_price"], r["price_by_wind_solar_bucket"])
    first, last = s.iloc[0], s.iloc[-1]
    peak = p.loc[p["avg_price"].idxmax()]
    lines = [
        "# Key findings",
        "",
        f"- **Renewables grew from {first.renewable_pct}% of generation in {first.year} "
        f"to {last.renewable_pct}% in {last.year}**; wind + solar alone went from "
        f"{first.wind_solar_pct}% to {last.wind_solar_pct}%, driven mostly by solar "
        f"({first.solar_pct}% → {last.solar_pct}%).",
        f"- **Prices peaked in {peak.year} at an average of {peak.avg_price} €/MWh** "
        f"(gas crisis), versus {p.iloc[-1].avg_price} €/MWh in {p.iloc[-1].year}.",
        f"- **Since 2023, days with the most wind + solar are much cheaper:** average price "
        f"{b.iloc[0].avg_price} €/MWh on days below 30% vs {b.iloc[-1].avg_price} €/MWh above 50% "
        f"({b.iloc[0].days} and {b.iloc[-1].days} days).",
        f"- **Controlling for demand and season**, each extra 10 percentage points of wind + solar "
        f"is associated with a price change of {reg['per_10pp']:.1f} €/MWh "
        f"(linear regression, R² = {reg['r2']:.2f}, n = {reg['n']} days, 2023 onward).",
        f"- **Demand in {y.iloc[-1].year} was {y.iloc[-1].demand_gwh/1000:.0f} TWh**, "
        f"compared with {y.iloc[0].demand_gwh/1000:.0f} TWh in {y.iloc[0].year}.",
        "",
        f"Days with an average price below 10 €/MWh: "
        + ", ".join(f"{a}: {c}" for a, c in zip(p["year"], p["days_below_10"])),
        "",
        "_Note: association, not proof of causation. Gas prices, hydro conditions and "
        "interconnection flows also move prices and are not in this dataset._",
    ]
    (OUT / "findings.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


def main():
    FIG.mkdir(parents=True, exist_ok=True)
    daily = build_daily()
    daily.to_csv("data/daily_clean.csv")  # also the input for the Power BI dashboard
    results = run_sql(daily)
    charts(daily, results)
    reg = regression(daily)
    findings(results, reg)


if __name__ == "__main__":
    main()
