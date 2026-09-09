# h3_delivery_satisfaction.R
#
# Tests H3 (see HYPOTHESES.md): does delivery speed predict review score,
# holding price/freight/category constant? "Getting product to market
# fast" as a demand-side lever, not just an ops cost.
#
# Honest framing: review_score is ordinal (1-5) and OLS on an ordinal
# outcome is a simplification, reported and used here because the
# coefficient direction/size and R^2 are the things this analysis needs,
# not a publication-grade model. A real deployment would use ordinal
# logistic regression; that tradeoff is stated, not hidden.
#
# Run from repo root: Rscript r/h3_delivery_satisfaction.R

df <- read.csv("data/processed/mart_order_satisfaction.csv",
                stringsAsFactors = TRUE)
# drop bad/extreme delivery timestamps
df <- df[df$delivery_days >= 0 & df$delivery_days < 120, ]

model <- lm(review_score ~ delivery_days + price + freight_value + category,
            data = df)
s <- summary(model)

cat("=== H3: review_score ~ delivery_days + price + freight_value",
    "+ category ===\n")
cat(sprintf("R-squared: %.4f | Adjusted R-squared: %.4f | N: %d\n\n",
            s$r.squared, s$adj.r.squared, nrow(df)))

cat("delivery_days coefficient (the H3 test):\n")
coefs <- as.data.frame(s$coefficients)
print(coefs["delivery_days", ])

cat(sprintf(paste0(
  "\nInterpretation: each additional day of delivery time is associated ",
  "with a %.4f-point change in review score (1-5 scale), holding ",
  "price/freight/category fixed. "
), coefs["delivery_days", "Estimate"]))
if (coefs["delivery_days", "Pr(>|t|)"] < 0.001) {
  cat("This is highly statistically significant given the sample size,",
      "but note the practical size of the effect against R^2 below",
      "before treating it as a major lever.\n")
} else {
  cat("Not statistically significant at conventional thresholds.\n")
}

sink("output/h3_regression_summary.txt")
cat("H3: review_score ~ delivery_days + price + freight_value + category\n")
cat(sprintf("R-squared: %.4f | Adjusted R-squared: %.4f | N: %d\n\n",
            s$r.squared, s$adj.r.squared, nrow(df)))
print(s)
sink()
cat("\nWrote output/h3_regression_summary.txt\n")
