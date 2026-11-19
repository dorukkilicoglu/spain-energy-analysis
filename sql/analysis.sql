-- Spain Electricity Market Analysis: SQL queries
-- Runs on the clean "daily" table built by analysis.py:
--   date, demand_gwh, generation_gwh, renewable_gwh, wind_gwh, solar_gwh,
--   renewable_share, wind_solar_share, price_eur_mwh
-- Each query starts with a "-- name:" line so analysis.py can run and report it.

-- name: yearly_demand
-- Total demand per year and year-over-year change (CTE + LAG window function)
WITH yearly AS (
    SELECT substr(date, 1, 4) AS year,
           ROUND(SUM(demand_gwh), 0) AS demand_gwh
    FROM daily
    GROUP BY year
)
SELECT year,
       demand_gwh,
       ROUND(100.0 * (demand_gwh - LAG(demand_gwh) OVER (ORDER BY year))
             / LAG(demand_gwh) OVER (ORDER BY year), 1) AS yoy_change_pct
FROM yearly
ORDER BY year;

-- name: yearly_renewable_share
-- Share of generation from renewables and from wind + solar, per year
SELECT substr(date, 1, 4) AS year,
       ROUND(100.0 * SUM(renewable_gwh) / SUM(generation_gwh), 1) AS renewable_pct,
       ROUND(100.0 * SUM(wind_gwh + solar_gwh) / SUM(generation_gwh), 1) AS wind_solar_pct,
       ROUND(100.0 * SUM(solar_gwh) / SUM(generation_gwh), 1) AS solar_pct
FROM daily
GROUP BY year
ORDER BY year;

-- name: yearly_price
-- Average, minimum and maximum daily price per year
SELECT substr(date, 1, 4) AS year,
       ROUND(AVG(price_eur_mwh), 1) AS avg_price,
       ROUND(MIN(price_eur_mwh), 1) AS min_price,
       ROUND(MAX(price_eur_mwh), 1) AS max_price,
       SUM(CASE WHEN price_eur_mwh < 10 THEN 1 ELSE 0 END) AS days_below_10
FROM daily
GROUP BY year
ORDER BY year;

-- name: price_by_month_of_year
-- Seasonality: average price by calendar month (excluding the 2022 crisis year)
SELECT CAST(substr(date, 6, 2) AS INTEGER) AS month,
       ROUND(AVG(price_eur_mwh), 1) AS avg_price,
       ROUND(AVG(100 * wind_solar_share), 1) AS avg_wind_solar_pct
FROM daily
WHERE substr(date, 1, 4) <> '2022'
GROUP BY month
ORDER BY month;

-- name: top_10_expensive_days
-- Most expensive days with demand and renewable share on the same day
SELECT date,
       ROUND(price_eur_mwh, 1) AS price,
       ROUND(demand_gwh, 0) AS demand_gwh,
       ROUND(100 * wind_solar_share, 1) AS wind_solar_pct
FROM daily
ORDER BY price_eur_mwh DESC
LIMIT 10;

-- name: price_by_wind_solar_bucket
-- Core question: are days with more wind + solar cheaper? (2023 onward, after the gas crisis)
WITH bucketed AS (
    SELECT price_eur_mwh,
           CASE
               WHEN wind_solar_share < 0.30 THEN '1) < 30%'
               WHEN wind_solar_share < 0.40 THEN '2) 30-40%'
               WHEN wind_solar_share < 0.50 THEN '3) 40-50%'
               ELSE '4) > 50%'
           END AS wind_solar_bucket
    FROM daily
    WHERE date >= '2023-01-01'
)
SELECT wind_solar_bucket,
       COUNT(*) AS days,
       ROUND(AVG(price_eur_mwh), 1) AS avg_price
FROM bucketed
GROUP BY wind_solar_bucket
ORDER BY wind_solar_bucket;

-- name: weekday_vs_weekend
-- Demand and price on weekdays vs weekends
SELECT CASE WHEN strftime('%w', date) IN ('0', '6') THEN 'Weekend' ELSE 'Weekday' END AS day_type,
       ROUND(AVG(demand_gwh), 0) AS avg_demand_gwh,
       ROUND(AVG(price_eur_mwh), 1) AS avg_price
FROM daily
GROUP BY day_type;
