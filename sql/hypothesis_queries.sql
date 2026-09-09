-- hypothesis_queries.sql
-- Run with: duckdb data/processed/olist.duckdb -c ".read sql/hypothesis_queries.sql"
-- Marts are already built by src/01_build_marts.py; this file only queries them.
-- See HYPOTHESES.md for the claim/decision framing behind each query.

-- H1: Is demand seasonal within categories? (top 10 categories by volume,
-- ranked by demand_volatility_cv, the coefficient of variation across
-- months)
SELECT category, total_items, avg_monthly_items, demand_volatility_cv
FROM mart_category_summary
ORDER BY total_items DESC
LIMIT 10;

-- H1 (supporting): month-by-month demand curve for the single most
-- seasonal high-volume category, to see the actual shape, not just the CV.
SELECT category, order_month, items_sold
FROM mart_category_monthly_demand
WHERE category = (
    SELECT category FROM mart_category_summary
    WHERE total_items >= 1000
    ORDER BY demand_volatility_cv DESC LIMIT 1
)
ORDER BY order_month;

-- H2: Which categories are gaining or losing SHARE of total demand?
-- (Real relative growth/decline, net of overall platform growth.)
-- (raw item-count trend is misleading here; see mart_category_share_trend
-- comment in src/01_build_marts.py for why).
SELECT category, total_items, share_trend_slope, share_trend_r2
FROM mart_category_share_trend
ORDER BY share_trend_slope DESC
LIMIT 8;

SELECT category, total_items, share_trend_slope, share_trend_r2
FROM mart_category_share_trend
ORDER BY share_trend_slope ASC
LIMIT 8;

-- H3 supporting query: raw correlation direction check (the actual R^2
-- test runs in r/h3_delivery_satisfaction.R). Average review score by
-- delivery-speed bucket, as a sanity check anyone can read without R.
SELECT
    CASE
        WHEN delivery_days <= 5 THEN '0-5 days'
        WHEN delivery_days <= 10 THEN '6-10 days'
        WHEN delivery_days <= 20 THEN '11-20 days'
        ELSE '21+ days'
    END AS delivery_bucket,
    COUNT(*) AS orders,
    ROUND(AVG(review_score), 3) AS avg_review_score
FROM mart_order_satisfaction
WHERE delivery_days BETWEEN 0 AND 120
GROUP BY delivery_bucket
ORDER BY MIN(delivery_days);
