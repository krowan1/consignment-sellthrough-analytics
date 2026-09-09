"""
03_migrate_to_supabase.py

Loads the Olist raw tables into a proper raw/staging/marts (bronze/
silver/gold) Postgres schema on Supabase, applying two data-quality
fixes surfaced by a pre-migration review (see README "Database Review"):

  1. raw.category_translation is missing English translations for two
     categories that real products reference ('pc_gamer' and
     'portateis_cozinha_e_preparadores_de_alimentos'), added explicitly
     below so the products -> category_translation FK is enforceable
     honestly instead of silently failing or being left unconstrained.
     'pc_gamer' maps to itself (already an English/brand term), but the
     row still has to exist for the FK, so it's inserted like the other.
  2. raw.reviews has no usable single-column key: the same review_id
     appears against multiple order_ids, and 547 orders have more than
     one review row. The composite (review_id, order_id) IS unique and
     is used as the real primary key; marts.order_satisfaction resolves
     the order-level fan-out (rare multi-review orders) to one score per
     order before joining to line items, so no line item gets counted
     twice.

Load order matters here because of real foreign keys: parents before
children (category_translation/sellers -> products -> orders ->
order_items/reviews).

Run from repo root: python src/03_migrate_to_supabase.py
"""
import os
import csv
import psycopg2

RAW = "data/raw"

# Data-quality fix #1 (see docstring): translations Olist's own lookup
# table is missing for categories that real products actually use.
MISSING_TRANSLATIONS = [
    ("pc_gamer", "pc_gamer"),  # already effectively English/brand term
    ("portateis_cozinha_e_preparadores_de_alimentos", "portable_kitchen_and_food_prep"),
]

# (schema-qualified table, source CSV, whether this table has FKs that
# require its parents to already be loaded, which drives load order)
LOAD_ORDER = [
    ("raw.category_translation", "product_category_name_translation.csv"),
    ("raw.sellers", "olist_sellers_dataset.csv"),
    ("raw.products", "olist_products_dataset.csv"),
    ("raw.orders", "olist_orders_dataset.csv"),
    ("raw.order_items", "olist_order_items_dataset.csv"),
    ("raw.reviews", "olist_order_reviews_dataset.csv"),
]


def load_db_url() -> str:
    if os.environ.get("SUPABASE_DB_URL"):
        return os.environ["SUPABASE_DB_URL"]
    with open(".env") as f:
        content = f.read().strip()
    _, _, url = content.partition("=")
    return url.strip()


def main():
    url = load_db_url()
    conn = psycopg2.connect(url)
    cur = conn.cursor()

    print("Applying schema (sql/postgres_schema.sql)...")
    schema_sql = open("sql/postgres_schema.sql").read()
    # Run just the DROP/CREATE SCHEMA + raw table DDL first; staging/marts
    # are CREATE TABLE AS and need raw data loaded before they can run.
    raw_ddl, _, rest = schema_sql.partition("-- =========================================================================\n-- STAGING")
    cur.execute(raw_ddl)
    conn.commit()
    print("Schemas + raw table DDL applied.")

    for table, filename in LOAD_ORDER:
        path = os.path.join(RAW, filename)
        with open(path, encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            header = next(reader)
        cols = ",".join(header)
        with open(path, encoding="utf-8-sig") as f:
            cur.copy_expert(
                f"COPY {table} ({cols}) FROM STDIN WITH (FORMAT csv, HEADER true, NULL '')",
                f,
            )
        conn.commit()

        if table == "raw.category_translation":
            cur.executemany(
                "INSERT INTO raw.category_translation VALUES (%s, %s) ON CONFLICT DO NOTHING",
                MISSING_TRANSLATIONS,
            )
            conn.commit()
            print(f"  Patched raw.category_translation with {len(MISSING_TRANSLATIONS)} missing translations")

        cur.execute(f"SELECT COUNT(*) FROM {table}")
        print(f"  Loaded {table}: {cur.fetchone()[0]:,} rows")

    print("\nBuilding staging + marts tables...")
    _, _, staging_and_marts = schema_sql.partition("-- STAGING")
    cur.execute("-- STAGING" + staging_and_marts)
    conn.commit()

    for t in ["staging.fact_order_items", "marts.category_monthly_demand",
              "marts.category_summary", "marts.category_share_trend",
              "marts.order_satisfaction"]:
        cur.execute(f"SELECT COUNT(*) FROM {t}")
        print(f"  {t}: {cur.fetchone()[0]:,} rows")

    cur.close()
    conn.close()
    print("\nMigration complete.")


if __name__ == "__main__":
    main()
