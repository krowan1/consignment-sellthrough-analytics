-- postgres_schema.sql
-- Medallion-layered Postgres (Supabase) schema: raw (bronze) -> staging
-- (silver) -> marts (gold). Real foreign keys live in `raw` only, so the
-- Supabase Schema Visualizer renders an actual ER diagram; `staging` and
-- `marts` are intentionally denormalized (built to be queried, not
-- normalized). See README "Database Review" for the two data-quality
-- findings that shaped the FK/PK design below.

DROP SCHEMA IF EXISTS marts CASCADE;
DROP SCHEMA IF EXISTS staging CASCADE;
DROP SCHEMA IF EXISTS raw CASCADE;

CREATE SCHEMA raw;
CREATE SCHEMA staging;
CREATE SCHEMA marts;

-- =========================================================================
-- RAW (bronze): normalized, real FKs, as close to source as possible
-- =========================================================================

CREATE TABLE raw.category_translation (
    product_category_name TEXT PRIMARY KEY,
    product_category_name_english TEXT
);

CREATE TABLE raw.sellers (
    seller_id TEXT PRIMARY KEY,
    seller_zip_code_prefix TEXT,
    seller_city TEXT,
    seller_state TEXT
);

CREATE TABLE raw.products (
    product_id TEXT PRIMARY KEY,
    product_category_name TEXT REFERENCES raw.category_translation(product_category_name),
    product_name_lenght NUMERIC,
    product_description_lenght NUMERIC,
    product_photos_qty NUMERIC,
    product_weight_g NUMERIC,
    product_length_cm NUMERIC,
    product_height_cm NUMERIC,
    product_width_cm NUMERIC
);

CREATE TABLE raw.orders (
    order_id TEXT PRIMARY KEY,
    customer_id TEXT,
    order_status TEXT,
    order_purchase_timestamp TIMESTAMP,
    order_approved_at TIMESTAMP,
    order_delivered_carrier_date TIMESTAMP,
    order_delivered_customer_date TIMESTAMP,
    order_estimated_delivery_date TIMESTAMP
);

-- Grain: one row per (order, line item). Composite PK matches that grain.
CREATE TABLE raw.order_items (
    order_id TEXT REFERENCES raw.orders(order_id),
    order_item_id INT,
    product_id TEXT REFERENCES raw.products(product_id),
    seller_id TEXT REFERENCES raw.sellers(seller_id),
    shipping_limit_date TIMESTAMP,
    price NUMERIC,
    freight_value NUMERIC,
    PRIMARY KEY (order_id, order_item_id)
);

-- Database review finding: review_id is NOT unique on its own. The same
-- review_id appears against multiple distinct order_ids with identical
-- score/date (98,410 distinct review_id across 99,224 rows). Real grain
-- is (review_id, order_id); a bare review_id PRIMARY KEY would have
-- failed the load outright. See README "Database Review."
CREATE TABLE raw.reviews (
    review_id TEXT,
    order_id TEXT REFERENCES raw.orders(order_id),
    review_score INT,
    review_comment_title TEXT,
    review_comment_message TEXT,
    review_creation_date TIMESTAMP,
    review_answer_timestamp TIMESTAMP,
    PRIMARY KEY (review_id, order_id)
);

-- =========================================================================
-- STAGING (silver): cleaned, joined, single grain (delivered line items)
-- =========================================================================

CREATE TABLE staging.fact_order_items AS
SELECT
    oi.order_id,
    oi.product_id,
    oi.seller_id,
    o.order_purchase_timestamp AS purchase_ts,
    o.order_delivered_customer_date AS delivered_ts,
    DATE_TRUNC('month', o.order_purchase_timestamp) AS order_month,
    EXTRACT(DAY FROM (o.order_delivered_customer_date - o.order_purchase_timestamp))::INT AS delivery_days,
    oi.price,
    oi.freight_value,
    COALESCE(ct.product_category_name_english, p.product_category_name, 'unknown') AS category
FROM raw.order_items oi
JOIN raw.orders o ON o.order_id = oi.order_id
LEFT JOIN raw.products p ON p.product_id = oi.product_id
LEFT JOIN raw.category_translation ct ON ct.product_category_name = p.product_category_name
WHERE o.order_status = 'delivered'
  AND o.order_delivered_customer_date IS NOT NULL;

-- =========================================================================
-- MARTS (gold): denormalized, business-facing, no FKs by design
-- =========================================================================

CREATE TABLE marts.category_monthly_demand AS
SELECT
    category,
    order_month,
    COUNT(*) AS items_sold,
    ROUND(SUM(price), 2) AS revenue,
    ROUND(AVG(price), 2) AS avg_price
FROM staging.fact_order_items
GROUP BY category, order_month;

CREATE TABLE marts.category_summary AS
WITH monthly AS (
    SELECT category, order_month,
           ROW_NUMBER() OVER (PARTITION BY category ORDER BY order_month) AS month_idx,
           items_sold
    FROM marts.category_monthly_demand
),
totals AS (
    SELECT category, COUNT(*) AS months_active, SUM(items_sold) AS total_items,
           AVG(items_sold) AS avg_monthly_items,
           STDDEV_POP(items_sold) AS stdev_monthly_items
    FROM monthly GROUP BY category
),
trend AS (
    SELECT category, REGR_SLOPE(items_sold, month_idx) AS trend_slope,
           REGR_R2(items_sold, month_idx) AS trend_r2
    FROM monthly GROUP BY category
)
SELECT t.category, t.months_active, t.total_items,
       ROUND(t.avg_monthly_items, 1) AS avg_monthly_items,
       ROUND((t.stdev_monthly_items / NULLIF(t.avg_monthly_items, 0))::NUMERIC, 3) AS demand_volatility_cv,
       ROUND(tr.trend_slope::NUMERIC, 3) AS trend_slope_items_per_month,
       ROUND(tr.trend_r2::NUMERIC, 3) AS trend_r2
FROM totals t
JOIN trend tr USING (category)
WHERE t.total_items >= 30
ORDER BY t.total_items DESC;

CREATE TABLE marts.category_share_trend AS
WITH monthly AS (
    SELECT category, order_month, items_sold,
           SUM(items_sold) OVER (PARTITION BY order_month) AS month_total,
           ROW_NUMBER() OVER (PARTITION BY category ORDER BY order_month) AS month_idx
    FROM marts.category_monthly_demand
),
share AS (
    SELECT category, order_month, month_idx, items_sold::NUMERIC / month_total AS share
    FROM monthly
),
totals AS (
    SELECT category, SUM(items_sold) AS total_items
    FROM marts.category_monthly_demand GROUP BY category
),
trend AS (
    SELECT category, REGR_SLOPE(share, month_idx) AS share_trend_slope,
           REGR_R2(share, month_idx) AS share_trend_r2
    FROM share GROUP BY category
)
SELECT t.category, t.total_items,
       ROUND(tr.share_trend_slope::NUMERIC, 6) AS share_trend_slope,
       ROUND(tr.share_trend_r2::NUMERIC, 3) AS share_trend_r2
FROM totals t JOIN trend tr USING (category)
WHERE t.total_items >= 100
ORDER BY share_trend_slope DESC;

-- Database review finding #3: 547 orders have more than one row in
-- raw.reviews (a second review submission on the same order), which
-- would silently duplicate line-item rows if joined directly, inflating
-- the H3 regression's N for those orders without anyone noticing. Reviews
-- are resolved to one score per order (average, in case of disagreement)
-- BEFORE joining to line items, so the grain stays one row per delivered
-- line item (matching r/h3_delivery_satisfaction.R and the DuckDB build)
-- and no order's line items get counted twice.
CREATE TABLE marts.order_satisfaction AS
WITH review_per_order AS (
    SELECT order_id, ROUND(AVG(review_score)) AS review_score
    FROM raw.reviews
    WHERE review_score IS NOT NULL
    GROUP BY order_id
)
SELECT
    f.order_id,
    f.category,
    f.price,
    f.freight_value,
    f.delivery_days,
    rpo.review_score
FROM staging.fact_order_items f
JOIN review_per_order rpo ON rpo.order_id = f.order_id
WHERE f.delivery_days IS NOT NULL;
