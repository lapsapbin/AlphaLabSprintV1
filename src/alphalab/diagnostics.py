"""Research-only rank IC and gross quintile diagnostics; no HAC or alpha claims."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .validation import require


def _align(signal: pd.Series, realized: pd.Series) -> tuple[pd.Series, pd.Series]:
    require(not signal.index.has_duplicates and not realized.index.has_duplicates, "diagnostic_duplicate_labels")
    require(set(signal.index) == set(realized.index), "diagnostic_label_alignment")
    signal = signal.sort_index()
    realized = realized.reindex(signal.index)
    require(np.isfinite(signal.to_numpy(dtype=float)).all() and np.isfinite(realized.to_numpy(dtype=float)).all(), "diagnostic_nonfinite_input")
    return signal, realized


def spearman_ic(signal: pd.Series, realized: pd.Series) -> float:
    """Pearson correlation of average ranks, including ties; constant => NaN."""
    signal, realized = _align(signal, realized)
    x = signal.rank(method="average").to_numpy(dtype=float)
    y = realized.rank(method="average").to_numpy(dtype=float)
    x, y = x - x.mean(), y - y.mean()
    denominator = np.sqrt(np.dot(x, x) * np.dot(y, y))
    return float(np.dot(x, y) / denominator) if denominator > 0 else float("nan")


def quintile_members(signal: pd.Series) -> dict[str, list[str]]:
    require(len(signal) == 49 and not signal.index.has_duplicates, "quintile_49_labels")
    require(np.isfinite(signal.to_numpy(dtype=float)).all(), "quintile_nonfinite_signal")
    ordered = pd.DataFrame({"industry": signal.index, "signal": signal.to_numpy()}).sort_values(
        ["signal", "industry"], ascending=[True, True], kind="stable")["industry"].tolist()
    edges = [0, 10, 20, 30, 40, 49]
    return {f"Q{i + 1}": ordered[edges[i]:edges[i + 1]] for i in range(5)}


def quintile_returns(signal: pd.Series, realized: pd.Series) -> dict[str, float]:
    signal, realized = _align(signal, realized)
    values = {group: float(realized.loc[labels].mean()) for group, labels in quintile_members(signal).items()}
    values["Q5_minus_Q1"] = values["Q5"] - values["Q1"]
    return values


def research_diagnostics(signals: pd.DataFrame, returns: pd.DataFrame, start: str = "2000-01", end: str = "2017-12") -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """An explicit calendar is selected before any diagnostic arithmetic; Day2 defaults preserved."""
    calendar = pd.period_range(start, end, freq="M", name="holding_month")
    for frame in (signals, returns):
        require(isinstance(frame.index, pd.PeriodIndex) and frame.index.freqstr == "M", "monthly_period_type")
        require(not frame.index.has_duplicates, "diagnostic_duplicate_months")
        require(len(calendar.difference(frame.index)) == 0, "diagnostic_missing_months")
    selected_signals = signals.loc[calendar].copy()
    selected_returns = returns.loc[calendar].copy()
    require(selected_signals.shape == selected_returns.shape == (len(calendar), 49), "diagnostic_research_shape")
    ic_rows, quintile_rows = [], []
    for month in calendar:
        signal, realized = selected_signals.loc[month], selected_returns.loc[month]
        ic_rows.append({"holding_month": month, "rank_ic": spearman_ic(signal, realized)})
        quintile_rows.append({"holding_month": month, **quintile_returns(signal, realized)})
    ic, quintiles = pd.DataFrame(ic_rows), pd.DataFrame(quintile_rows)
    valid = ic["rank_ic"].dropna()
    summary = {
        "range": [str(calendar[0]), str(calendar[-1])], "months": len(calendar),
        "rank_ic": {"valid_months": len(valid), "undefined_months": len(ic) - len(valid),
                    "mean": float(valid.mean()) if len(valid) else None,
                    "sample_std_ddof1": float(valid.std(ddof=1)) if len(valid) > 1 else None,
                    "positive_fraction_of_valid": float((valid > 0).mean()) if len(valid) else None},
        "quintile_monthly_mean": {column: float(quintiles[column].mean()) for column in quintiles.columns if column != "holding_month"},
        "quintile_counts": [10, 10, 10, 10, 9], "units": "decimal_monthly_return",
        "interpretation": "gross research diagnostics; Q5-Q1 is not a tradable net long-short strategy; no significance inference",
    }
    return ic, quintiles, summary
