"""
02_charts.py

Illustrative charts supporting the findings, kept intentionally simple
(matplotlib, static PNG). These are placeholders for a Power BI report
built later directly against the marts (see README "Where Power BI
fits"), not the final visualization layer. Each chart carries its own
takeaway as a subtitle so it reads correctly without the surrounding
README prose.
"""
import duckdb
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

con = duckdb.connect("data/processed/olist.duckdb")

# --- Chart 1: seasonality curve for electronics (H1) ------------------
# Oct 2016 is Olist's marketplace launch month: 1 order platform-wide in
# electronics, then zero orders in Nov/Dec 2016 before real volume starts
# in Jan 2017. A straight line drawn across that zero-order gap would
# read as smooth growth no data point supports, so the chart starts at
# Jan 2017 and the excluded launch-noise point is footnoted instead.
df = con.execute("""
    SELECT order_month, items_sold FROM mart_category_monthly_demand
    WHERE category = 'electronics' AND order_month >= '2017-01-01'
    ORDER BY order_month
""").df()

fig, ax = plt.subplots(figsize=(9, 5))
ax.plot(df["order_month"], df["items_sold"], marker="o", color="#1f77b4", linewidth=2)

# Shade the holiday-season window the title/finding actually claims.
season_start = pd.Timestamp("2017-11-01")
season_end = pd.Timestamp("2018-02-28")
ax.axvspan(season_start, season_end, color="#1f77b4", alpha=0.10)
ax.text(pd.Timestamp("2017-12-15"), df["items_sold"].max() * 1.02,
        "Nov-Feb holiday ramp", ha="center", fontsize=9, color="#1f77b4")

fig.suptitle("Electronics: Monthly Demand Shows a Clear Seasonal Ramp (H1)",
             fontsize=13, fontweight="bold", y=0.98)
ax.set_title("Demand roughly triples heading into the holidays, then falls back by spring",
             fontsize=9.5, color="#444444", pad=10)
ax.set_ylabel("Items sold")
ax.xaxis.set_major_locator(mdates.MonthLocator(interval=1))
ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
fig.autofmt_xdate()
ax.spines[["top", "right"]].set_visible(False)
fig.text(0.01, 0.01,
         "Note: Oct 2016 (Olist's marketplace launch, 1 order platform-wide in "
         "electronics) is excluded as launch noise, not smoothed over.",
         fontsize=7.5, color="#666666")
fig.tight_layout(rect=[0, 0.04, 1, 0.90])
fig.savefig("output/h1_electronics_seasonality.png", dpi=150)
print("Wrote output/h1_electronics_seasonality.png")

# --- Chart 2: growing vs declining share-of-demand categories (H2) -----
df2 = con.execute("""
    SELECT category, share_trend_slope FROM mart_category_share_trend
    ORDER BY share_trend_slope ASC
""").df()
top = df2.tail(6)
bottom = df2.head(6)
combined = pd.concat([bottom, top])
colors = ["#d62728"] * len(bottom) + ["#2ca02c"] * len(top)

fig, ax = plt.subplots(figsize=(9, 6))
ax.barh(combined["category"], combined["share_trend_slope"] * 1000, color=colors)
fig.suptitle("Gaining vs. Losing Share of Total Demand (H2, net of platform growth)",
             fontsize=13, fontweight="bold", y=0.98)
ax.set_title(
    "Share = percent of that month's items sold (not revenue). A category\n"
    "can lose share here even while total platform volume is rising.",
    fontsize=9.5, color="#444444", pad=16)
ax.set_xlabel("Monthly change in demand share (x1000, positive = gaining share)")
ax.axvline(0, color="black", linewidth=0.8)
ax.spines[["top", "right"]].set_visible(False)
fig.tight_layout(rect=[0, 0, 1, 0.85])
fig.savefig("output/h2_share_trend.png", dpi=150)
print("Wrote output/h2_share_trend.png")

# --- Chart 3: delivery speed vs. review score (H3) ---------------------
# The regression (r/h3_delivery_satisfaction.R) is the actual H3 test;
# this chart makes its finding visible without reading a raw lm() dump.
df3 = con.execute("""
    SELECT delivery_days, review_score FROM mart_order_satisfaction
    WHERE delivery_days >= 0 AND delivery_days < 120
""").df()
bins = [-0.5, 5.5, 10.5, 20.5, 1000]
labels = ["0-5 days", "6-10 days", "11-20 days", "21+ days"]
df3["bucket"] = pd.cut(df3["delivery_days"], bins=bins, labels=labels)
summary = df3.groupby("bucket", observed=True)["review_score"].mean()

fig, ax = plt.subplots(figsize=(8, 5))
ax.bar(summary.index.astype(str), summary.values, color="#1f77b4")
ax.plot(summary.index.astype(str), summary.values, color="#d62728",
        marker="o", linewidth=2)
fig.suptitle("Faster Delivery Predicts Higher Review Scores (H3)",
             fontsize=13, fontweight="bold", y=0.98)
ax.set_title(
    "Each extra week of delivery time costs roughly a third of a star,\n"
    "holding price and category fixed (R² = 0.1085, p < 0.001)",
    fontsize=9.5, color="#444444", pad=16)
ax.set_ylabel("Average review score (1-5)")
ax.set_ylim(1, 5)
ax.spines[["top", "right"]].set_visible(False)
fig.tight_layout(rect=[0, 0, 1, 0.85])
fig.savefig("output/h3_delivery_satisfaction.png", dpi=150)
print("Wrote output/h3_delivery_satisfaction.png")
print("(Full regression detail: run r/h3_delivery_satisfaction.R -> output/h3_regression_summary.txt)")
