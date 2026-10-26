"""Exact self-financing monthly accounting with a small serializable state."""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from .portfolio import check_calendar, check_weights
from .validation import require


@dataclass
class PortfolioState:
    nav: float
    industry_weights: dict[str, float]
    cash_weight: float
    last_month: str | None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict) -> "PortfolioState":
        return cls(**value)


def solve_cost(pretrade: np.ndarray, target: np.ndarray, cost_rate: float) -> tuple[float, float]:
    """Solve k + c sum|kw-b| = 1; D is two-sided industry trading, not half."""
    b, w = np.asarray(pretrade, dtype=float), np.asarray(target, dtype=float)
    check_weights(b)
    check_weights(w)
    require(b.shape == w.shape, "cost_weight_alignment")
    require(np.isfinite(cost_rate) and 0 <= cost_rate < 1, "invalid_cost_rate")
    if cost_rate == 0 or np.array_equal(b, w):
        return 1.0, float(np.abs(w - b).sum())
    lo, hi = 0.0, 1.0
    for _ in range(80):
        mid = (lo + hi) / 2
        residual = mid + cost_rate * float(np.abs(mid * w - b).sum()) - 1
        if residual > 0:
            hi = mid
        else:
            lo = mid
    k = (lo + hi) / 2
    traded = float(np.abs(k * w - b).sum())
    require(0 < k <= 1 and abs(k + cost_rate * traded - 1) <= 1e-12, "cost_equation_residual")
    return k, traded


def simulate(targets: pd.DataFrame, returns: pd.DataFrame, rf: pd.Series, cost_bps: int,
             state: PortfolioState | None = None) -> tuple[pd.DataFrame, pd.DataFrame, PortfolioState]:
    """Month-open costs then realized total returns; resume only next calendar month.

    Targets/risk history are explicit inputs, independent of fee scenario. A fresh
    run must start in 2000-01 from cash; later chunks require the prior state.
    """
    check_calendar(targets.index)
    require(not targets.columns.has_duplicates and set(targets.columns) == set(returns.columns), "backtest_label_alignment")
    require(not returns.index.has_duplicates and not returns.columns.has_duplicates and not rf.index.has_duplicates, "backtest_duplicate_key")
    require(len(targets.index.difference(returns.index)) == len(targets.index.difference(rf.index)) == 0, "backtest_missing_returns")
    require(cost_bps in (0, 10, 20), "fixed_cost_scenarios_required")
    labels = sorted(targets.columns)
    if state is None:
        require(str(targets.index[0]) == "2000-01", "later_segment_requires_prior_state")
        state = PortfolioState(1.0, dict.fromkeys(labels, 0.0), 1.0, None)
    else:
        require(state.last_month is not None and pd.Period(state.last_month, "M") + 1 == targets.index[0], "state_calendar_continuity")
    require(set(state.industry_weights) == set(labels), "state_label_alignment")
    require(np.isfinite(state.nav) and state.nav > 0, "state_positive_wealth")
    b = np.array([state.industry_weights[label] for label in labels], dtype=float)
    require(np.isfinite(state.cash_weight) and state.cash_weight >= 0
            and abs(check_weights(b) - state.cash_weight) <= 1e-12, "state_cash_balance")
    nav = float(state.nav)
    pretrade_cash = float(state.cash_weight)
    rows, drift_rows = [], []
    for month in targets.index:
        w = targets.loc[month, labels].to_numpy(dtype=float)
        cash = check_weights(w)
        # Cost and target decision does not read current-month returns or RF.
        k, traded = solve_cost(b, w, cost_bps / 10000)
        realized = returns.loc[month, labels].to_numpy(dtype=float)
        cash_return = float(rf.loc[month])
        require(np.isfinite(realized).all() and (realized >= -1).all()
                and np.isfinite(cash_return) and cash_return >= -1, "backtest_invalid_realized_return")
        gross = float(np.dot(w, realized) + cash * cash_return)
        asset_wealth = float(np.dot(w, 1 + realized) + cash * (1 + cash_return))
        require(np.isfinite(gross) and asset_wealth > 0 and 1 + gross > 0, "portfolio_zero_or_nonfinite_gross_wealth")
        net = gross if cost_bps == 0 else k * (1 + gross) - 1
        next_nav = nav * (1 + net)
        require(np.isfinite(next_nav) and next_nav > 0, "portfolio_nonpositive_or_nonfinite_nav")
        cost_fraction = 1 - k
        residual = k + cost_bps / 10000 * traded - 1
        require(abs(residual) <= 1e-12, "cost_equation_residual")
        require(abs(gross - net - cost_fraction * (1 + gross)) <= 1e-12, "gross_net_identity")
        require(abs((nav * k * (w.sum() + cash) + nav * cost_fraction) / nav - 1) <= 1e-12, "self_financing_identity")
        next_b = w * (1 + realized) / (1 + gross)
        next_cash = cash * (1 + cash_return) / (1 + gross)
        require(abs(check_weights(next_b) - next_cash) <= 1e-12, "drift_cash_balance")
        rows.append({"holding_month": month, "gross_return": gross, "net_return": net,
                     "nav_before": nav, "nav": next_nav, "k": k, "gross_traded_fraction": traded,
                     "cost_fraction": cost_fraction, "cost_amount": nav * cost_fraction,
                     "cost_equation_residual": residual, "cash_weight": cash,
                     "risky_weight": float(w.sum()), "pretrade_cash_weight": pretrade_cash,
                     "end_cash_weight": float(next_cash), "RF": cash_return})
        drift_rows.extend({"holding_month": month, "industry": label,
                           "pretrade_weight": float(b[i]), "target_weight": float(w[i]),
                           "end_weight": float(next_b[i])} for i, label in enumerate(labels))
        nav, b, pretrade_cash = next_nav, next_b, float(next_cash)
    final = PortfolioState(nav, dict(zip(labels, map(float, b), strict=True)), float(next_cash), str(targets.index[-1]))
    return pd.DataFrame(rows), pd.DataFrame(drift_rows), final
