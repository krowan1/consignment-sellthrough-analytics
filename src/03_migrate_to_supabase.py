"""
03_migrate_to_supabase.py

Loads the same Olist raw tables + rebuilds the same marts on real
Postgres (Supabase), using sql/postgres_schema.sql. Reads the connection
string from a local .env file (SUPABASE_DB_URL=...), which is gitignored
and never committed -- see README "Postgres via Supabase."

Run from repo root: python src/03_migrate_to_supabase.py
"""
import os
import csv
import psycopg2

RAW = "data/raw"


def load_db_url() -> str:
    if os.environ.get("SUPABASE_DB_URL"):
        return os.environ["SUPABASE_DB_URL"]
    with open(".env") as f:
        content = f.read().strip()
    _, _, url = content.partition("=")
    return url.strip()


TABLE_FILES = {
    "orders": "olist_orders_dataset.csv",
    "order_items": "olist_order_items_dataset.csv",
    "products": "olist_products_dataset.csv",
    "category_translation": "product_category_name_translation.csv",
    "reviews": "olist_order_reviews_dataset.csv",
    "sellers": "olist_sellers_dataset.csv",
}


def main():
    url = load_db_url()
    conn = psycopg2.connect(url)
    conn.autocommit = False
    cur = conn.cursor()

    print("Applying schema (sql/postgres_schema.sql, tables only)...")
    schema_sql = open("sql/postgres_schema.sql").read()
    # Split off just the CREATE TABLE (empty) statements for raw tables;
    # run those first, load data, then run the fact/mart CREATE TABLE AS
    # statements separately so COPY has tables to load into.
    raw_ddl, _, mart_ddl = schema_sql.partition("-- === Fact table")
    cur.execute(raw_ddl)
    conn.commit()
    print("Raw table DDL applied.")

    for table, filename in TABLE_FILES.items():
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
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        print(f"  Loaded {table}: {cur.fetchone()[0]:,} rows")

    print("\nBuilding fact + mart tables...")
    cur.execute("-- === Fact table" + mart_ddl)
    conn.commit()

    for t in ["fact_order_items", "mart_category_monthly_demand",
              "mart_category_summary", "mart_category_share_trend",
              "mart_order_satisfaction"]:
        cur.execute(f"SELECT COUNT(*) FROM {t}")
        print(f"  {t}: {cur.fetchone()[0]:,} rows")

    cur.close()
    conn.close()
    print("\nMigration complete.")


if __name__ == "__main__":
    main()
