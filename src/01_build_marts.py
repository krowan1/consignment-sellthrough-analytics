"""
01_build_marts.py

Loads the real Olist Brazilian e-commerce dataset (public, Kaggle:
olistbr/brazilian-ecommerce, CC-BY-NC-SA-4.0), roughly 99k real orders
across relational tables, into DuckDB and builds governed marts that
answer the hypotheses in HYPOTHESES.md. Marts, not raw tables, are what
a BI tool (Power BI) should ever connect to; see README "Where Power BI
fits."

DuckDB is used instead of a live Postgres server so the repo runs for
anyone who clones it with zero setup; the SQL is written in portable
ANSI style and would move to Postgres unchanged if this became a real
service. See README for the reasoning.
"""
import duckdb
import os

RAW = "data/raw"
DB_PATH = "data/processed/olist.duckdb"

os.makedirs("data/processed", exist_ok=True)
if os.path.exists(DB_PATH):
    os.remove(DB_PATH)

con = duckdb.connect(DB_PATH)

# --- Load raw tables ---------------------------------------------------
con.execute(f"CREATE TABLE orders AS SELECT * FROM read_csv_auto('{RAW}/olist_orders_dataset.csv')")
con.execute(f"CREATE TABLE order_items AS SELECT * FROM read_csv_auto('{RAW}/olist_order_items_dataset.csv')")
con.execute(f"CREATE TABLE products AS SELECT * FROM read_csv_auto('{RAW}/olist_products_dataset.csv')")
con.execute(f"CREATE TABLE category_translation AS SELECT * FROM read_csv_auto('{RAW}/product_category_name_translation.csv')")
con.execute(f"CREATE TABLE reviews AS SELECT * FROM read_csv_auto('{RAW}/olist_order_reviews_dataset.csv')")
con.execute(f"CREATE TABLE sellers AS SELECT * FROM read_csv_auto('{RAW}/olist_sellers_dataset.csv')")

print("Raw tables loaded:")
for t in ["orders", "order_items", "products", "category_translation", "reviews", "sellers"]:
    n = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    print(f"  {t}: {n:,} rows")

# --- Core joined line-item fact table (delivered orders only) ---------
con.execute("""
    CREATE TABLE fact_order_items AS
    SELECT
        oi.order_id,
        oi.product_id,
        oi.seller_id,
        o.order_purchase_timestamp::TIMESTAMP AS purchase_ts,
        o.order_delivered_customer_date::TIMESTAMP AS delivered_ts,
        DATE_TRUNC('month', o.order_purchase_timestamp::TIMESTAMP) AS order_month,
        DATEDIFF('day', o.order_purchase_timestamp::TIMESTAMP,
                 o.order_delivered_customer_date::TIMESTAMP) AS delivery_days,
        oi.price,
        oi.freight_value,
        COALESCE(ct.product_category_name_english, p.product_category_name, 'unknown') AS category
    FROM order_items oi
    JOIN orders o USING (order_id)
    LEFT JOIN products p USING (product_id)
    LEFT JOIN category_translation ct USING (product_category_name)
    WHERE o.order_status = 'delivered'
      AND o.order_delivered_customer_date IS NOT NULL
""")
n = con.execute("SELECT COUNT(*) FROM fact_order_items").fetchone()[0]
print(f"\nfact_order_items (delivered only): {n:,} rows")

# --- Mart: category monthly demand (H1, H2) -----------------------------
con.execute("""
    CREATE TABLE mart_category_monthly_demand AS
    SELECT
        category,
        order_month,
        COUNT(*) AS items_sold,
        ROUND(SUM(price), 2) AS revenue,
        ROUND(AVG(price), 2) AS avg_price
    FROM fact_order_items
    GROUP BY category, order_month
""")

# --- Mart: category summary with trend + seasonality stats (H1, H2) ----
con.execute("""
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
        -- simple OLS slope of items_sold on month_idx per category
        SELECT category, regr_slope(items_sold, month_idx) AS trend_slope,
               regr_r2(items_sold, month_idx) AS trend_r2
        FROM monthly GROUP BY category
    )
    SELECT t.category, t.months_active, t.total_items,
           ROUND(t.avg_monthly_items, 1) AS avg_monthly_items,
           ROUND(t.stdev_monthly_items / NULLIF(t.avg_monthly_items, 0), 3) AS demand_volatility_cv,
           ROUND(tr.trend_slope, 3) AS trend_slope_items_per_month,
           ROUND(tr.trend_r2, 3) AS trend_r2
    FROM totals t
    JOIN trend tr USING (category)
    WHERE t.total_items >= 30  -- drop long-tail categories too sparse to trend reliably
    ORDER BY t.total_items DESC
""")

# --- Mart: category SHARE-OF-DEMAND trend (H2, corrected for platform growth)
# Raw item-count trend conflates category-specific growth with Olist's
# overall marketplace growth over this period (almost every category's raw
# count trends up simply because total order volume scaled up). Trending
# each category's *share* of total monthly demand isolates real relative
# growth/decline, the actual test of H2.
con.execute("""
    CREATE TABLE mart_category_share_trend AS
    WITH monthly AS (
        SELECT category, order_month, items_sold,
               SUM(items_sold) OVER (PARTITION BY order_month) AS month_total,
               ROW_NUMBER() OVER (PARTITION BY category ORDER BY order_month) AS month_idx
        FROM mart_category_monthly_demand
    ),
    share AS (
        SELECT category, order_month, month_idx, items_sold * 1.0 / month_total AS share
        FROM monthly
    ),
    totals AS (
        SELECT category, SUM(items_sold) AS total_items
        FROM mart_category_monthly_demand GROUP BY category
    ),
    trend AS (
        SELECT category, regr_slope(share, month_idx) AS share_trend_slope,
               regr_r2(share, month_idx) AS share_trend_r2
        FROM share GROUP BY category
    )
    SELECT t.category, t.total_items,
           ROUND(tr.share_trend_slope, 6) AS share_trend_slope,
           ROUND(tr.share_trend_r2, 3) AS share_trend_r2
    FROM totals t JOIN trend tr USING (category)
    WHERE t.total_items >= 100
    ORDER BY share_trend_slope DESC
""")

# --- Mart: order-level fact for the delivery/satisfaction regression (H3)
# Database review finding: raw reviews has no clean single-column key --
# the same review_id appears against multiple order_ids, and 547 orders
# have more than one review row. Joining fact_order_items to reviews
# directly on order_id would silently duplicate line-item rows for those
# 547 orders. Reviews are resolved to one score per order (average, in
# case of disagreement) BEFORE joining, so the grain stays one row per
# delivered line item and no order's items get double-counted. See
# sql/postgres_schema.sql for the equivalent Postgres version and
# README "Database Review" for how this was found.
con.execute("""
    CREATE TABLE review_per_order AS
    SELECT order_id, ROUND(AVG(review_score)) AS review_score
    FROM reviews
    WHERE review_score IS NOT NULL
    GROUP BY order_id
""")
con.execute("""
    CREATE TABLE mart_order_satisfaction AS
    SELECT
        f.order_id,
        f.category,
        f.price,
        f.freight_value,
        f.delivery_days,
        rpo.review_score
    FROM fact_order_items f
    JOIN review_per_order rpo USING (order_id)
    WHERE f.delivery_days IS NOT NULL
""")

for t in ["mart_category_monthly_demand", "mart_category_summary", "mart_category_share_trend", "mart_order_satisfaction"]:
    n = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    print(f"{t}: {n:,} rows")

# Export CSVs too, for the R script and for easy Power-BI-later loading.
con.execute("COPY mart_category_monthly_demand TO 'data/processed/mart_category_monthly_demand.csv' (HEADER, DELIMITER ',')")
con.execute("COPY mart_category_summary TO 'data/processed/mart_category_summary.csv' (HEADER, DELIMITER ',')")
con.execute("COPY mart_category_share_trend TO 'data/processed/mart_category_share_trend.csv' (HEADER, DELIMITER ',')")
con.execute("COPY mart_order_satisfaction TO 'data/processed/mart_order_satisfaction.csv' (HEADER, DELIMITER ',')")

con.close()
print("\nWrote data/processed/olist.duckdb and mart CSVs.")
