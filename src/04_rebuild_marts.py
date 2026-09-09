"""
04_rebuild_marts.py

Rebuilds just the staging + marts tables (raw tables don't change) against
Supabase Postgres, and logs row counts + a headline KPI. Run by the
scheduled GitHub Action (.github/workflows/rebuild_marts.yml), which
keeps the free-tier Supabase project active and re-verifies the pipeline
still runs cleanly end to end against real Postgres.

Reads SUPABASE_DB_URL from the environment (GitHub Actions secret in CI;
falls back to a local .env for manual runs).
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
    _, _, staging_and_marts = schema_sql.partition("-- STAGING")
    cur.execute("""
        DROP SCHEMA IF EXISTS marts CASCADE;
        DROP SCHEMA IF EXISTS staging CASCADE;
        CREATE SCHEMA staging;
        CREATE SCHEMA marts;
    """)
    cur.execute("-- STAGING" + staging_and_marts)
    conn.commit()

    print("Staging + marts rebuilt. Row counts:")
    for t in ["staging.fact_order_items", "marts.category_monthly_demand",
              "marts.category_summary", "marts.category_share_trend",
              "marts.order_satisfaction"]:
        cur.execute(f"SELECT COUNT(*) FROM {t}")
        print(f"  {t}: {cur.fetchone()[0]:,}")

    cur.execute("""
        SELECT category, share_trend_slope, share_trend_r2
        FROM marts.category_share_trend
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
