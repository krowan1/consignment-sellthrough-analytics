"""
04_rebuild_marts.py

Rebuilds just the fact/mart tables (not the raw tables -- those don't
change) against Supabase Postgres, and logs row counts + a couple of
headline KPIs. This is what the scheduled GitHub Action runs
(.github/workflows/rebuild_marts.yml) -- it's the "keep Supabase alive
and prove the pipeline still works end to end" job described in the
README.

Reads SUPABASE_DB_URL from the environment (set as a GitHub Actions
secret in CI; falls back to a local .env for manual runs).
"""
import os
import sys
import psycopg2


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

    schema_sql = open("sql/postgres_schema.sql").read()
    drops, _, mart_ddl = schema_sql.partition("CREATE TABLE orders")
    # Only drop the fact/mart tables here -- raw tables (orders, order_items,
    # etc.) are untouched; this script rebuilds derived tables, not source data.
    mart_drops = "\n".join(
        line for line in drops.splitlines()
        if line.startswith("DROP TABLE") and ("mart_" in line or "fact_order_items" in line)
    )
    _, _, mart_ddl = schema_sql.partition("-- === Fact table")
    cur.execute(mart_drops + "\n-- === Fact table" + mart_ddl)
    conn.commit()

    print("Marts rebuilt. Row counts:")
    for t in ["fact_order_items", "mart_category_monthly_demand",
              "mart_category_summary", "mart_category_share_trend",
              "mart_order_satisfaction"]:
        cur.execute(f"SELECT COUNT(*) FROM {t}")
        print(f"  {t}: {cur.fetchone()[0]:,}")

    cur.execute("""
        SELECT category, share_trend_slope, share_trend_r2
        FROM mart_category_share_trend
        ORDER BY share_trend_slope DESC LIMIT 1
    """)
    top = cur.fetchone()
    print(f"\nTop share-gaining category: {top[0]} (slope={top[1]}, r2={top[2]})")

    cur.close()
    conn.close()
    print("\nOK: pipeline verified end to end against Supabase.")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"FAILED: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)
