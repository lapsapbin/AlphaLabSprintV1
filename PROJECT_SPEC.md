# AlphaLab Sprint v1 — public methodology guide

This is a reader-oriented derivative of the accepted specification, not the private frozen SPEC bytes. Research code/configuration are copied unchanged for inspection; their private Git, authorization, evidence and full input dependencies are excluded. Do not use this package to launch production research or OOS commands.

- Data: Kenneth French 49 value-weighted industry total returns, monthly FF3/RF and Mom, current vintage downloaded 14 October 2026. Percent inputs were converted once to decimals after missing-marker recognition. No filling or clipping.
- Calendar: 1998–1999 warmup; 2000–2017 research (216 months); 2018–2023 validation (72 months) with fixed 2018–2020/2021–2023 subdivisions; 2024–2025 final evaluation (24 months), already observed.
- Momentum for holding t: compound returns t−12 through t−2, eleven months, skip t−1. Top5 exact ties use normalized industry labels ascending; five weights of 0.2 even if all scores are negative. EW49 uses 1/49 each.
- VOL10: each base strategy's own historical unscaled gross returns t−12 through t−1; sample standard deviation ddof=1 times sqrt(12); exposure min(1, 0.10/sigma), one at zero sigma. Residual cash earns same-month RF. No leverage or shorts.
- Fees: c = 0/0.001/0.002 one way; 10 bps primary. Solve k = 1 − c Σ|k w_i − b_i| with drifted pretrade b and post-cost target w. Both buys and sells count; no division by two. N = k(1+G)−1; drift divides by 1+G. Initial 2000 construction is charged; state continues across segments; no terminal liquidation.
- Segment CAGR uses the segment's first nav_before. Drawdown includes that initial point and excludes earlier peaks. Sharpe subtracts RF once. Active comparisons use matching months and costs, plus the scaled benchmark for scaled portfolios.
- Rank IC uses average ranks, same-month holding returns. Quintiles have 10/10/10/10/9 members; Q5 highest. Q5−Q1 is a gross diagnostic, not a tradable net strategy.
- Attribution: explicit-intercept OLS on Mkt-RF/SMB/HML/Mom; dependent net return minus RF. Bartlett HAC(6), no correction, normal inference, ±1.96 SE; annual alpha is 12 times monthly intercept.
- Two prespecified sensitivities: Top10 12–2 and Top5 6–2, only research/validation, 10 bps, no VOL variants or OOS paths. No post-OOS tuning.

See the [full report](reports/final_report.md), unchanged [configuration](config/research.yaml), [experiment list](config/experiments.json), [sources](docs/DATA_SOURCES.md) and [reproduction boundary](docs/REPRODUCIBILITY.md). Static LOCKED/DAY4 labels in copied configuration preserve the old implementation; actual OOS is observed. No authorization is included or granted here.
