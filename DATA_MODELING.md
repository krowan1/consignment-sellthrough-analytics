# Data Modeling Notes

Why the schema is shaped the way it is, and which standard warehouse modeling patterns were deliberately used, adapted, or skipped — and why.

## `raw` / `staging` / `marts` — and why raw isn't "one flat table"

The textbook medallion pattern (bronze → silver → gold) is often described as "bronze is one big raw table, silver is where you split it into a clean structure." That description fits one specific kind of source: a **flat/semi-structured feed** — logs, an API JSON dump, a single wide event stream — where bronze really is schema-on-read, minimally touched, and silver is where you parse and split it into normalized entities.

That's not this source. Olist's data *arrives* already relational — nine tables from what was originally a real OLTP production database (orders, order_items, products, sellers, reviews are already distinct entities with their own keys). Bronze's actual rule is "preserve the source faithfully, minimal transformation" — and since the source itself is already multi-table, the faithful `raw` layer is multi-table too. There's nothing flat to split apart.

So `staging.fact_order_items` does the same *kind* of work the "split it out" intuition describes, just in the direction this source actually needs: instead of splitting one table into several, it **joins** several raw tables into one clean, business-grain table (delivered line items only, category resolved, bad rows filtered). Silver's job is always "turn bronze into something clean and conformed at a stated grain" — whether that means splitting or joining depends entirely on the shape of what bronze started as.

## Platform-provided schemas: `storage` and `vault`

Not part of this project's design — Supabase provisions both automatically on every project:
- **`storage`** backs Supabase's file/object storage service (`storage.buckets`, `storage.objects`), present whether or not the feature is used.
- **`vault`** is Supabase's encrypted-secrets extension (`vault.secrets`, built on `pgsodium`) — for secrets a database function needs to use internally. Not used here: the one secret this project has (the DB connection string) lives outside the database entirely (a local `.env`, gitignored, and a `SUPABASE_DB_URL` GitHub Actions secret), which is the correct place for the credential that connects *to* the database, as opposed to a secret the database needs *for itself*.

## Star schema vs. Data Vault (hub-and-spoke) — neither was implemented, and why that's a deliberate call, not an oversight

**Star schema**: one central **fact** table surrounded by **dimension** tables (category, date, seller — descriptive, slowly-changing context), foreign-keyed out. Built for BI query performance and, more importantly, for *reusing* dimensions across multiple facts.

**Data Vault (hub-and-spoke)**: **Hubs** (bare business keys), **Links** (relationships/transactions between hubs), **Satellites** (timestamped descriptive attributes, so history is preserved as it changes). An integration-layer pattern for reconciling **many source systems over time** with full auditability — not typically exposed straight to a BI tool; a star schema (or similar) usually sits on top of a Data Vault for consumption.

**Not Data Vault**, because that pattern earns its complexity when integrating multiple live, competing source systems with a real historization/auditability requirement (e.g., merging CRM + ERP + support-ticket systems over years, needing to answer "what did we believe was true on a given date"). This project has one static dataset snapshot, no incremental loads, and no source-system reconciliation problem — Data Vault here would be modeling complexity added for a problem that doesn't exist.

**Not a formal star schema either — and this is a real gap worth naming, not just a non-fit.** `staging.fact_order_items` is fact-table-*shaped* (one row per delivered line item, clear grain), but the marts embed descriptive attributes (`category` as text) directly instead of joining out to real dimension tables (`dim_category`, `dim_date`). That's a flat, denormalized mart design, not a star schema. The honest reason: a star schema's main payoff is dimension *reuse* across multiple fact tables, and there's currently only one fact table — nothing yet needs to share `dim_category` or `dim_date`. The threshold for revisiting this: the moment a second fact table (e.g., a returns/refunds fact) would also need those same dimensions, factoring them out stops being premature and starts being necessary — not doing it at that point would mean duplicating logic across facts.
