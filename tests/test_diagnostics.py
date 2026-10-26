"""SYNTHETIC IC/quintile checks; no inference about real alpha."""
import numpy as np
import pandas as pd
import pytest

from alphalab import diagnostics


def test_spearman_sign_ties_alignment_and_constant():
    signal = pd.Series([1., 2., 3., 4.], index=list("abcd"))
    assert diagnostics.spearman_ic(signal, signal.iloc[::-1]) == pytest.approx(1.0)
    assert diagnostics.spearman_ic(signal, -signal) == pytest.approx(-1.0)
    ties_x = pd.Series([1., 1., 2., 3.], index=list("abcd"))
    ties_y = pd.Series([1., 2., 2., 4.], index=list("abcd"))
    # Centered average ranks [-1,-1,.5,1.5] and [-1.5,0,0,1.5]: 3.75/4.5.
    assert diagnostics.spearman_ic(ties_x, ties_y) == pytest.approx(5 / 6)
    constant = pd.Series(1., index=list("abcd"))
    assert np.isnan(diagnostics.spearman_ic(constant, signal))
    assert np.isnan(diagnostics.spearman_ic(signal, constant))


def test_quintile_sizes_direction_ties_and_hand_means():
    labels = [f"SYNTHETIC_{i:02d}" for i in range(49)]
    signal = pd.Series(np.arange(49) - 24., index=labels)
    returns = pd.Series(np.arange(49) / 100, index=labels)
    groups = diagnostics.quintile_members(signal.iloc[::-1])
    assert [len(v) for v in groups.values()] == [10, 10, 10, 10, 9]
    assert groups["Q1"] == labels[:10] and groups["Q5"] == labels[40:]
    values = diagnostics.quintile_returns(signal, returns.iloc[::-1])
    for key, expected in {"Q1": .045, "Q2": .145, "Q3": .245, "Q4": .345, "Q5": .44, "Q5_minus_Q1": .395}.items():
        assert values[key] == pytest.approx(expected)
    tied = diagnostics.quintile_members(pd.Series(-1., index=labels[::-1]))
    assert tied == groups


def test_research_calendar_selected_before_computation(config, monkeypatch):
    calendar = pd.period_range("1999-01", "2025-12", freq="M")
    labels = config["data"]["labels"]
    signals = pd.DataFrame(np.tile(np.arange(49), (len(calendar), 1)), index=calendar, columns=labels, dtype=float)
    returns = signals / 1000
    outside = (calendar < "2000-01") | (calendar > "2017-12")
    signals.loc[outside] = np.nan
    returns.loc[outside] = np.nan
    signals.loc["2005-06"] = 1.0
    returns.loc["2006-01"] = -returns.loc["2006-01"]
    original = diagnostics.spearman_ic
    seen = []
    def audited(signal, realized):
        assert pd.Period("2000-01", "M") <= signal.name <= pd.Period("2017-12", "M")
        assert realized.name == signal.name
        seen.append(signal.name)
        return original(signal, realized)
    monkeypatch.setattr(diagnostics, "spearman_ic", audited)
    ic, quintiles, summary = diagnostics.research_diagnostics(signals, returns)
    assert len(seen) == len(ic) == len(quintiles) == summary["months"] == 216
    assert summary["rank_ic"]["valid_months"] == 215
    assert summary["rank_ic"]["undefined_months"] == 1
    assert summary["rank_ic"]["mean"] == pytest.approx(213 / 215)
    assert summary["rank_ic"]["sample_std_ddof1"] == pytest.approx(2 / np.sqrt(215))
    assert summary["rank_ic"]["positive_fraction_of_valid"] == pytest.approx(214 / 215)
    assert ic.loc[ic["holding_month"] == "2005-06", "rank_ic"].isna().all()
    assert ic.loc[ic["holding_month"] == "2006-01", "rank_ic"].item() == pytest.approx(-1.0)
    assert ic.loc[ic["holding_month"] == "2006-02", "rank_ic"].item() == pytest.approx(1.0)
