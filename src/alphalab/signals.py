"""Calendar-aligned 12–2 momentum and deterministic targets. No backtesting."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .validation import ContractError, require


def return_panel(long: pd.DataFrame, labels: list[str]) -> pd.DataFrame:
    """Align a long table; missing observations stay missing and cannot be skipped."""
    require(set(["month", "industry", "return"]).issubset(long.columns), "return_fields")
    require(isinstance(long["month"].dtype, pd.PeriodDtype) and long["month"].dt.freq.name == "ME", "monthly_period_type")
    require(not long.duplicated(["month", "industry"]).any(), "duplicate_month_industry")
    require(set(long["industry"]) == set(labels), "signal_industry_universe")
    return long.pivot(index="month", columns="industry", values="return").reindex(columns=sorted(labels)).sort_index()


def momentum_12_2(returns: pd.DataFrame, holding_months: pd.PeriodIndex, labels: list[str]) -> pd.DataFrame:
    return momentum_window(returns, holding_months, labels, 12)


def momentum_window(returns: pd.DataFrame, holding_months: pd.PeriodIndex, labels: list[str], lookback: int) -> pd.DataFrame:
    """For each t, use exactly t−12,...,t−2. No t−1/t/future value is inspected.

    An explicit target calendar permits computing t using only historical input
    through t−1. No realized t return is needed to create a signal or target.
    """
    require(isinstance(returns.index, pd.PeriodIndex) and returns.index.freqstr == "M", "monthly_period_type")
    require(not returns.index.has_duplicates, "duplicate_months")
    require(len(labels) == len(set(labels)) == 49 and all(isinstance(x, str) and x == x.strip() for x in labels), "signal_49_normalized_labels")
    require(not returns.columns.has_duplicates and set(returns.columns) == set(labels), "signal_industry_universe")
    require(isinstance(holding_months, pd.PeriodIndex) and holding_months.freqstr == "M", "holding_month_calendar")
    require(len(holding_months) > 0 and not holding_months.has_duplicates and holding_months.is_monotonic_increasing, "holding_month_order")
    require(holding_months.equals(pd.period_range(holding_months[0], holding_months[-1], freq="M")), "holding_calendar_gap")
    require(lookback in {6, 12}, "fixed_momentum_window")
    ordered = sorted(labels)
    results = []
    for month in holding_months:
        window = pd.period_range(month - lookback, month - 2, freq="M")
        require(len(window.difference(returns.index)) == 0, "signal_window_missing_months")
        # Index by explicit calendar, not row position or rolling skipna behavior.
        try:
            values = returns.loc[window, ordered].to_numpy(dtype=float)
        except (TypeError, ValueError):
            raise ContractError("signal_window_numeric_type") from None
        require(values.shape == (lookback - 1, 49) and np.isfinite(values).all(), "signal_window_incomplete_or_nonfinite")
        require((values >= -1).all(), "signal_window_return_below_minus_100_percent")
        signal = np.prod(1.0 + values, axis=0) - 1.0
        require(np.isfinite(signal).all(), "signal_nonfinite")
        results.append(signal)
    return pd.DataFrame(results, index=holding_months.rename("holding_month"), columns=ordered)


def ranked_signals(signals: pd.DataFrame) -> pd.DataFrame:
    """Rank 1 is highest signal; label ascending breaks exact ties for targets."""
    require(isinstance(signals.index, pd.PeriodIndex) and signals.index.freqstr == "M", "holding_month_calendar")
    require(not signals.index.has_duplicates and not signals.columns.has_duplicates, "duplicate_signal_key")
    require(len(signals.columns) == 49 and all(isinstance(x, str) and x == x.strip() for x in signals.columns), "signal_49_normalized_labels")
    require(np.isfinite(signals.to_numpy(dtype=float)).all(), "signal_nonfinite")
    long = signals.rename_axis("holding_month").reset_index().melt(id_vars="holding_month", var_name="industry", value_name="signal")
    ordered = long.sort_values(["holding_month", "signal", "industry"], ascending=[True, False, True], kind="stable")
    ordered["rank"] = ordered.groupby("holding_month", sort=False).cumcount() + 1
    return ordered.sort_values(["holding_month", "industry"], kind="stable").reset_index(drop=True)


def target_weights(signals: pd.DataFrame) -> pd.DataFrame:
    """Full 49-industry vectors for MOM5 and EW49, including zero allocations."""
    ranked = ranked_signals(signals)
    mom5 = ranked[["holding_month", "industry"]].copy()
    mom5["strategy"] = "MOM5"
    mom5["weight"] = np.where(ranked["rank"].to_numpy() <= 5, 0.2, 0.0)
    ew49 = ranked[["holding_month", "industry"]].copy()
    ew49["strategy"] = "EW49"
    ew49["weight"] = 1.0 / 49
    return pd.concat([mom5, ew49], ignore_index=True)[["holding_month", "strategy", "industry", "weight"]].sort_values(
        ["holding_month", "strategy", "industry"], kind="stable").reset_index(drop=True)
