"""
02_charts.py

Two illustrative charts supporting the findings -- kept intentionally
simple (matplotlib, static PNG). These are placeholders for a Power BI
report built later directly against the marts (see README "Where Power BI
fits") -- not the final visualization layer.
"""
import duckdb
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

con = duckdb.connect("data/processed/olist.duckdb")

# Chart 1: seasonality curve for electronics (clear holiday-season ramp)
df = con.execute("""
    SELECT order_month, items_sold FROM mart_category_monthly_demand
    WHERE category = 'electronics' ORDER BY order_month
""").df()
fig, ax = plt.subplots(figsize=(9, 4.5))
ax.plot(df["order_month"], df["items_sold"], marker="o", color="#1f77b4", linewidth=2)
ax.set_title("Electronics: Monthly Demand Shows a Clear Seasonal Ramp (H1)")
ax.set_ylabel("Items sold")
ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
fig.autofmt_xdate()
ax.spines[["top", "right"]].set_visible(False)
fig.tight_layout()
fig.savefig("output/h1_electronics_seasonality.png", dpi=150)
print("Wrote output/h1_electronics_seasonality.png")

# Chart 2: growing vs declining share-of-demand categories (H2)
df2 = con.execute("""
    SELECT category, share_trend_slope FROM mart_category_share_trend
    ORDER BY share_trend_slope ASC
""").df()
top = df2.tail(6)
bottom = df2.head(6)
combined = pd_concat = __import__("pandas").concat([bottom, top])
colors = ["#d62728"] * len(bottom) + ["#2ca02c"] * len(top)

fig, ax = plt.subplots(figsize=(9, 5.5))
ax.barh(combined["category"], combined["share_trend_slope"] * 1000, color=colors)
ax.set_title("Gaining vs. Losing Share of Total Demand (H2, net of platform growth)")
ax.set_xlabel("Monthly change in demand share (x1000, positive = gaining share)")
ax.axvline(0, color="black", linewidth=0.8)
ax.spines[["top", "right"]].set_visible(False)
fig.tight_layout()
fig.savefig("output/h2_share_trend.png", dpi=150)
print("Wrote output/h2_share_trend.png")
