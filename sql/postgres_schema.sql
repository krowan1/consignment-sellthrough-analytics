-- postgres_schema.sql
-- Real Postgres (Supabase) version of the pipeline built on DuckDB.
-- Same tables, same mart logic -- Postgres has native regr_slope/regr_r2
-- aggregates too, so the trend math is unchanged from the DuckDB SQL.
-- Run once via src/03_migrate_to_supabase.py (handles COPY + this DDL).

DROP TABLE IF EXISTS mart_order_satisfaction;
DROP TABLE IF EXISTS mart_category_share_trend;
DROP TABLE IF EXISTS mart_category_summary;
DROP TABLE IF EXISTS mart_category_monthly_demand;
DROP TABLE IF EXISTS fact_order_items;
DROP TABLE IF EXISTS reviews;
DROP TABLE IF EXISTS category_translation;
DROP TABLE IF EXISTS products;
DROP TABLE IF EXISTS order_items;
DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS sellers;

CREATE TABLE orders (
    order_id TEXT PRIMARY KEY,
    customer_id TEXT,
    order_status TEXT,
    order_purchase_timestamp TIMESTAMP,
    order_approved_at TIMESTAMP,
    order_delivered_carrier_date TIMESTAMP,
    order_delivered_customer_date TIMESTAMP,
    order_estimated_delivery_date TIMESTAMP
);

CREATE TABLE order_items (
    order_id TEXT,
    order_item_id INT,
    product_id TEXT,
    seller_id TEXT,
    shipping_limit_date TIMESTAMP,
    price NUMERIC,
    freight_value NUMERIC
);

CREATE TABLE products (
    product_id TEXT PRIMARY KEY,
    product_category_name TEXT,
    product_name_lenght NUMERIC,
    product_description_lenght NUMERIC,
    product_photos_qty NUMERIC,
    product_weight_g NUMERIC,
    product_length_cm NUMERIC,
    product_height_cm NUMERIC,
    product_width_cm NUMERIC
);

CREATE TABLE category_translation (
    product_category_name TEXT PRIMARY KEY,
    product_category_name_english TEXT
);

CREATE TABLE reviews (
    review_id TEXT,
    order_id TEXT,
    review_score INT,
    review_comment_title TEXT,
    review_comment_message TEXT,
    review_creation_date TIMESTAMP,
    review_answer_timestamp TIMESTAMP
);

CREATE TABLE sellers (
    seller_id TEXT PRIMARY KEY,
    seller_zip_code_prefix TEXT,
    seller_city TEXT,
    seller_state TEXT
);

-- === Fact table (delivered orders only) ===
CREATE TABLE fact_order_items AS
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
FROM order_items oi
JOIN orders o ON o.order_id = oi.order_id
LEFT JOIN products p ON p.product_id = oi.product_id
LEFT JOIN category_translation ct ON ct.product_category_name = p.product_category_name
WHERE o.order_status = 'delivered'
  AND o.order_delivered_customer_date IS NOT NULL;

-- === Mart: category monthly demand (H1, H2) ===
CREATE TABLE mart_category_monthly_demand AS
SELECT
    category,
    order_month,
    COUNT(*) AS items_sold,
    ROUND(SUM(price), 2) AS revenue,
    ROUND(AVG(price), 2) AS avg_price
FROM fact_order_items
GROUP BY category, order_month;

-- === Mart: category summary (H1, H2 raw trend) ===
CREATE TABLE mart_category_summary AS
WITH monthly AS (
    SELECT category, order_month,
           ROW_NUMBER() OVER (PARTITION BY category ORDER BY order_month) AS month_idx,
           items_sold
    FROM mart_category_monthly_demand
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

-- === Mart: category share-of-demand trend (H2, corrected for platform growth) ===
CREATE TABLE mart_category_share_trend AS
WITH monthly AS (
    SELECT category, order_month, items_sold,
           SUM(items_sold) OVER (PARTITION BY order_month) AS month_total,
           ROW_NUMBER() OVER (PARTITION BY category ORDER BY order_month) AS month_idx
    FROM mart_category_monthly_demand
),
share AS (
    SELECT category, order_month, month_idx, items_sold::NUMERIC / month_total AS share
    FROM monthly
),
totals AS (
    SELECT category, SUM(items_sold) AS total_items
    FROM mart_category_monthly_demand GROUP BY category
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

-- === Mart: order-level fact for the delivery/satisfaction regression (H3) ===
CREATE TABLE mart_order_satisfaction AS
SELECT
    f.order_id,
    f.category,
    f.price,
    f.freight_value,
    f.delivery_days,
    r.review_score
FROM fact_order_items f
JOIN reviews r ON r.order_id = f.order_id
WHERE f.delivery_days IS NOT NULL AND r.review_score IS NOT NULL;
