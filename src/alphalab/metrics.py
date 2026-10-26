"""Descriptive research metrics; no inference, regressions or model selection."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .validation import require


def performance(net: np.ndarray, rf: np.ndarray, nav: np.ndarray, start_nav: float = 1.0) -> dict:
    net, rf, nav = (np.asarray(x, dtype=float) for x in (net, rf, nav))
    require(net.ndim == rf.ndim == nav.ndim == 1 and len(net) == len(rf) == len(nav) >= 2, "metric_shapes")
    require(all(np.isfinite(x).all() for x in (net, rf, nav)) and np.isfinite(start_nav) and start_nav > 0
            and (nav > 0).all() and (net > -1).all(), "metric_finite_positive_wealth")
    require(np.allclose(nav, start_nav * np.cumprod(1 + net), rtol=1e-12, atol=1e-12), "metric_nav_identity")
    excess = net - rf
    volatility = 0.0 if np.ptp(net) == 0 else float(np.std(net, ddof=1) * np.sqrt(12))
    excess_std = 0.0 if np.ptp(excess) == 0 else float(np.std(excess, ddof=1))
    path = np.r_[start_nav, nav]
    drawdown = 1 - path / np.maximum.accumulate(path)
    return {"months": len(net), "terminal_nav": float(nav[-1]),
            "cagr": float((nav[-1] / start_nav) ** (12 / len(net)) - 1),
            "annualized_net_volatility": volatility,
            "sharpe": float(np.mean(excess) / excess_std * np.sqrt(12)) if excess_std > 0 else np.nan,
            "sharpe_defined": bool(excess_std > 0), "max_drawdown": float(drawdown.max())}


def summaries(monthly: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    summaries, active, differences = [], [], []
    for (strategy, cost), group in monthly.groupby(["strategy", "cost_bps"], sort=True):
        group = group.sort_values("holding_month").set_index("holding_month")
        row = {"strategy": strategy, "cost_bps": cost,
               **performance(group.net_return.to_numpy(), group.RF.to_numpy(), group.nav.to_numpy(), float(group.nav_before.iloc[0])),
               "mean_gross_traded_fraction": float(group.gross_traded_fraction.mean()),
               "annualized_gross_traded_fraction": float(12 * group.gross_traded_fraction.mean()),
               "mean_cash_weight": float(group.cash_weight.mean()),
               "mean_risky_weight": float(group.risky_weight.mean())}
        summaries.append(row)
        benchmarks = ["EW49"] + (["EW49_VOL10"] if strategy.endswith("_VOL10") else [])
        for benchmark in benchmarks:
            reference = monthly.loc[(monthly.strategy == benchmark) & (monthly.cost_bps == cost)].set_index("holding_month")
            require(group.index.equals(reference.index), "active_calendar_alignment")
            delta = group.net_return - reference.net_return
            active.extend({"holding_month": month, "strategy": strategy, "cost_bps": cost,
                           "benchmark": benchmark, "active_return": float(value)} for month, value in delta.items())
            ref_cagr = performance(reference.net_return.to_numpy(), reference.RF.to_numpy(), reference.nav.to_numpy(), float(reference.nav_before.iloc[0]))["cagr"]
            differences.append({"strategy": strategy, "cost_bps": cost, "benchmark": benchmark,
                                "annualized_mean_active_return": float(12 * delta.mean()),
                                "cagr_difference": row["cagr"] - ref_cagr})
    return pd.DataFrame(summaries), pd.DataFrame(active), pd.DataFrame(differences)
