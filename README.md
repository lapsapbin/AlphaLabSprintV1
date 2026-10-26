# Cost-Aware Industry Momentum Research

**Owner-authorized complete research presentation.** This repository shares the project implementation, analysis and independently calculated research outputs; raw/processed source data are excluded. No additional software license is granted. See [rights and scope](docs/RIGHTS_STATUS.md).

[![Synthetic demo guards](https://github.com/lapsapbin/AlphaLabSprintV1/actions/workflows/demo-ci.yml/badge.svg)](https://github.com/lapsapbin/AlphaLabSprintV1/actions/workflows/demo-ci.yml)
The linked workflow reports its actual status; local checks alone do not establish remote CI success.

Does simple industry momentum survive allocation costs and a fixed risk rule? This fixed-design study uses 49 US industries, 12–2 momentum, Top5 allocation and an equal-weight benchmark, each with and without a capped 10% volatility rule. Four portfolios × 0/10/20 bps are retained across research, validation and final evaluation.

At 10 bps in the already observed 2024–2025 final interval:

| Portfolio | CAGR | Maximum drawdown | Mean industry exposure |
|---|---:|---:|---:|
| MOM5 | 5.0438% | 10.7026% | 100.0000% |
| EW49 | 15.3700% | 9.4698% | 100.0000% |
| MOM5_VOL10 | 5.1033% | 4.2561% | 50.5953% |
| EW49_VOL10 | 11.5225% | 6.5232% | 65.4382% |

The final comparison is unfavorable to momentum. IC and main-cost OOS intercept intervals include zero; 24 months are exploratory and have limited statistical power. Reduced exposure/drawdown is not alpha. No parameters were changed to rescue this result.

![Accepted continuous retrospective wealth and drawdown](reports/figures/day6_release/01_wealth_drawdown.png)

Read the [full report](reports/final_report.md), [one walkthrough Notebook](notebooks/01_research_walkthrough.ipynb), [methodology](PROJECT_SPEC.md), and [all fixed performance tables](reports/figures/day6_release/performance_all_fixed.csv). The report preserves three segments, fixed validation subdivisions, all costs, attribution, diagnostic intervals and the two research/validation-only sensitivities. The 2000–2025 full path is retrospective, not another untouched test.

Use the [demonstration quickstart](tools/walkthrough/README.md) to display saved results in a fresh kernel. The small [synthetic workflow](.github/workflows/demo-ci.yml) checks file/path guards and teaching code-source only. Neither path runs a strategy or opens a new holdout. There were two historical formal OOS executions, the first evaluation and its identical repeat.

The unchanged [research source](src/alphalab/cli.py), [configuration](config/research.yaml), root dependencies and research tests are included for reading. Production execution needs excluded private inputs, Git/evidence and authorization; it is not the supported quickstart and its guards are not bypassed. [Reproduction scope](docs/REPRODUCIBILITY.md) explains what was actually verified.

Data are a revised current vintage, not historical PIT. Industry research portfolios are not tradable ETFs; assumed allocation costs omit internal turnover, impact, taxes and capacity. [Data sources](docs/DATA_SOURCES.md), [rights status](docs/RIGHTS_STATUS.md), [source mapping](PUBLIC_SOURCE_MAP.json) and [payload index](PUBLIC_PAYLOAD_MANIFEST.json) separate provenance from permission. The owner has authorized this complete presentation scope. That decision does not grant general third-party data redistribution rights or imply legal clearance; source datasets remain excluded.
