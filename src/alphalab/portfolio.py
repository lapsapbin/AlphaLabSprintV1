"""Unscaled historical base portfolios and strictly lagged VOL10 targets."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .validation import require

BASES = ("MOM5", "EW49")
STRATEGIES = ("MOM5", "EW49", "MOM5_VOL10", "EW49_VOL10")


def check_weights(values: np.ndarray) -> float:
    values = np.asarray(values, dtype=float)
    require(values.ndim == 1 and len(values) > 0 and np.isfinite(values).all(), "weights_finite_vector")
    require((values >= 0).all() and values.sum() <= 1 + 1e-12, "weights_long_only_no_leverage")
    total = float(values.sum())
    # A fully invested 49 * (1/49) vector can sum a few ulps below one.
    return 0.0 if abs(total - 1) <= 1e-14 else 1.0 - total


def check_calendar(index: pd.Index) -> None:
    require(isinstance(index, pd.PeriodIndex) and index.freqstr == "M", "monthly_period_type")
    require(len(index) > 0 and index.is_unique and index.is_monotonic_increasing, "calendar_order_or_duplicate")
    require(index.equals(pd.period_range(index[0], index[-1], freq="M")), "calendar_missing_month")


def base_gross_returns(weights: dict[str, pd.DataFrame], returns: pd.DataFrame) -> pd.DataFrame:
    """Use each historical month's actual unscaled target, never today's selection."""
    require(set(weights) == set(BASES), "two_base_portfolios_required")
    result = {}
    for name in BASES:
        target = weights[name]
        check_calendar(target.index)
        require(not target.columns.has_duplicates and set(target.columns) == set(returns.columns), "base_label_alignment")
        require(not returns.index.has_duplicates and not returns.columns.has_duplicates, "base_duplicate_key")
        require(len(target.index.difference(returns.index)) == 0, "base_missing_returns")
        realized = returns.loc[target.index, target.columns].to_numpy(dtype=float)
        require(np.isfinite(realized).all() and (realized >= -1).all(), "base_invalid_returns")
        for row in target.to_numpy(dtype=float):
            require(check_weights(row) <= 1e-12 and abs(row.sum() - 1) <= 1e-12, "base_fully_invested")
        result[name] = pd.Series(np.sum(target.to_numpy(dtype=float) * realized, axis=1), index=target.index)
    require(weights[BASES[0]].index.equals(weights[BASES[1]].index), "base_calendar_alignment")
    return pd.DataFrame(result).rename_axis("holding_month")


def risk_targets(base_weights: dict[str, pd.DataFrame], base_gross: pd.DataFrame,
                 calendar: pd.PeriodIndex) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    """For t, only base gross t-12..t-1 determines sigma; no RF input exists."""
    check_calendar(calendar)
    require(set(base_weights) == set(BASES) and set(base_gross.columns) == set(BASES), "two_base_portfolios_required")
    require(isinstance(base_gross.index, pd.PeriodIndex) and base_gross.index.freqstr == "M"
            and not base_gross.index.has_duplicates, "risk_history_months")
    targets, rows = {}, []
    for base in BASES:
        weights = base_weights[base]
        require(not weights.index.has_duplicates and not weights.columns.has_duplicates, "target_duplicate_key")
        require(len(calendar.difference(weights.index)) == 0, "target_missing_months")
        selected = weights.loc[calendar].copy()
        scales = []
        for month in calendar:
            window = pd.period_range(month - 12, month - 1, freq="M")
            require(len(window.difference(base_gross.index)) == 0, "risk_requires_12_complete_months")
            history = base_gross.loc[window, base].to_numpy(dtype=float)
            require(len(history) == 12 and np.isfinite(history).all(), "risk_history_nonfinite")
            sigma = 0.0 if np.ptp(history) == 0 else float(np.std(history, ddof=1) * np.sqrt(12))
            require(np.isfinite(sigma), "risk_sigma_nonfinite")
            scale = 1.0 if sigma == 0 else min(1.0, 0.10 / sigma)
            scales.append(scale)
            require(check_weights(selected.loc[month].to_numpy(dtype=float)) <= 1e-12, "base_fully_invested")
            for strategy, applied in [(base, 1.0), (base + "_VOL10", scale)]:
                rows.append({"holding_month": month, "strategy": strategy, "base_strategy": base,
                             "sigma_history_start": str(window[0]), "sigma_history_end": str(window[-1]),
                             "sigma_annual": sigma, "risk_scale": applied, "cash_weight": 1 - applied})
        targets[base] = selected
        targets[base + "_VOL10"] = selected.mul(scales, axis=0)
    return targets, pd.DataFrame(rows).sort_values(["holding_month", "strategy"]).reset_index(drop=True)
