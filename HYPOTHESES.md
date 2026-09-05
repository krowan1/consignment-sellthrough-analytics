# Hypotheses

Framed as a resale/consignment operator's buy-and-sell-timing question:
**"What should we buy more of, what should we hold off on, and when should
we be listing each category?"** Every hypothesis below is stated before
looking at the result, tested against real data, and closed out with a
stated decision — not retrofitted to a chart that already looked
interesting.

## H1 — Category demand is seasonal, not flat
**Claim:** Monthly order volume within a category varies enough by
calendar month that "when to stock" is a real, category-specific decision
— not a single answer for the whole catalog.
**Test:** Monthly order count and revenue by category (`mart_category_monthly_demand`),
coefficient of variation across months per category.
**Decision if true:** Build category-specific buy calendars instead of one
blanket inventory cadence.
**Decision if false:** Deprioritize seasonality as a planning input; focus
buy-timing decisions on price/margin signals instead.

## H2 — Some categories are structurally growing or shrinking, independent of season
**Claim:** Beyond month-to-month noise, certain categories show a real
trend (up or down) across the dataset's full time span.
**Test:** Linear trend fit (month index -> order volume) per top category;
categories with a statistically significant, non-trivial slope are flagged
growing/declining.
**Decision if true:** Weight buy volume toward growing categories now,
before a trend is obvious from raw sales; flag declining categories for
markdown/exit rather than restock.
**Decision if false:** Trend isn't a reliable lever here; fall back to
season-only planning (H1).

## H3 — Delivery speed is associated with customer satisfaction (review score)
**Claim:** Faster time-to-delivery predicts higher review scores, holding
price and category roughly constant — i.e., "getting product to market
fast" is not just an internal ops metric, it's a demand-side lever
(satisfied buyers → repeat business → resale reputation, which matters
disproportionately in consignment/resale).
**Test:** Linear regression (R, reported with R²): review_score ~
delivery_days + price + freight_value + category.
**Decision if true:** Delivery-time SLAs become a prioritized operational
investment, not just a cost center — justify the spend with the
satisfaction linkage.
**Decision if false (or R² trivial):** Don't over-invest in delivery-speed
initiatives on customer-satisfaction grounds alone; look for other levers.

## Explicit limitation (read before judging "days to sell")
Olist is a direct-sale marketplace — every row is an already-completed
purchase, so there's no "days an item sat unsold" the way there would be
in a real consignment inventory system. `mart_category_monthly_demand`
and the seasonality/trend work are the honest proxy for buy/sell timing
available in this data: how fast a category is moving right now, and
whether that's accelerating or decelerating. This is stated up front, not
discovered by a reader three tables in.
