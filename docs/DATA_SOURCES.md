# Sources, snapshot and rights boundary

Official source: [Kenneth French Data Library](https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html), with [49-industry construction](https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/Data_Library/det_49_ind_port.html), [FF3/RF construction](https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/Data_Library/f-f_factors.html) and [momentum factor construction](https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/Data_Library/det_mom_factor.html). Pages were checked on 25 October 2026. No new financial data were downloaded for this publication.

| Original archive (excluded) | SHA-256 |
|---|---|
| 49_Industry_Portfolios_CSV.zip | 16b3f20bf5bd1db8f5cd7a1b29f5cab1350eb0d5106c5309f77a6629590b1c0e |
| F-F_Research_Data_Factors_CSV.zip | 593f4fbef03181bc0b22ff6292f217689dd1fb79355049ca905d95b262040a66 |
| F-F_Momentum_Factor_CSV.zip | c06d1c2e9a5e4f6985879722f23c6bb585f46b34eaf3fcb681d4de887e353f3e |

The [original metadata manifest](../data/manifest.json) records official archive URLs, download times on 14 October 2026 UTC, parser version and original/product hashes. It contains metadata, not the excluded data. Headers identify a 202608 CRSP input vintage. A later download at the same URL need not match; hashes identify this snapshot, not a right to redistribute it.

Only value-weighted monthly industry total returns were parsed; annual/equal-weight blocks were excluded. FF3/RF and Mom use monthly decimals after one percentage conversion. Within-industry value weighting differs from between-industry equal allocation. Complete calendars/missing-marker rules are described in the [methodology](../PROJECT_SPEC.md).

The official Data Library explains the FIZ-to-CIZ transition starting with the January 2025 release: monthly construction and dividend reinvestment conventions differ, and history can be revised. The FF3 page identifies the RF source change beginning June 2024. This is a current-vintage retrospective study, not historical PIT reconstruction.

The official home page displays a Kenneth R. French copyright notice. The checked pages did not establish a general third-party data redistribution grant, and this repository claims none. That absence is not presented as proof of a specific prohibition or as legal clearance. The owner has authorized publication of the project implementation, analysis and independently calculated research outputs. Official attribution and snapshot metadata are retained; full raw/processed source data, factor input sequences, industry input slices and industry holdings are excluded. The publication decision does not grant rights in source data. See [rights status](RIGHTS_STATUS.md).
