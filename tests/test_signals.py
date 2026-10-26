"""SYNTHETIC timing and target fixtures; they are not evidence of real alpha."""
import math

import numpy as np
import pandas as pd
import pytest

from alphalab.signals import momentum_12_2, ranked_signals, return_panel, target_weights
from alphalab.validation import ContractError


@pytest.fixture
def history(config):
    calendar = pd.period_range("1998-01", "2001-12", freq="M", name="month")
    values = ((np.arange(48)[:, None] + 1) * (np.arange(49)[None, :] + 1)) / 10000 - 0.04
    return pd.DataFrame(values, index=calendar, columns=config["data"]["labels"])


def test_exact_calendar_product_and_long_form_alignment(history, config):
    labels = config["data"]["labels"]
    monthly = [0.01, -0.02, 0.03, 0.04, -0.05, 0.06, -0.07, 0.08, 0.09, -0.10, 0.11, 0.90]
    history.loc["1998", labels[0]] = monthly
    calendar = pd.period_range("1999-01", periods=1, freq="M")
    result = momentum_12_2(history, calendar, labels)
    assert result.loc["1999-01", labels[0]] == pytest.approx(math.prod(1 + x for x in monthly[:11]) - 1, abs=1e-14)
    assert result.loc["1999-01", labels[1]] == pytest.approx(math.prod(1 + (i * 2 / 10000 - 0.04) for i in range(1, 12)) - 1)
    long = history.reset_index().melt(id_vars="month", var_name="industry", value_name="return").sample(frac=1, random_state=17)
    rebuilt = momentum_12_2(return_panel(long, labels), calendar, labels)
    pd.testing.assert_frame_equal(result, rebuilt)


def test_skipped_current_future_and_truncation_invariance(history, config):
    labels = config["data"]["labels"]
    t = pd.Period("1999-01", "M")
    months = pd.period_range(t, periods=1, freq="M")
    expected = momentum_12_2(history.loc[:t - 1], months, labels)
    changed = history.copy()
    changed.loc[t - 1] = 0.87654321
    changed.loc[t:] = np.nan  # even unusable current/future values are not read
    actual = momentum_12_2(changed, months, labels)
    pd.testing.assert_frame_equal(expected, actual)
    pd.testing.assert_frame_equal(target_weights(expected), target_weights(actual))
    longer = pd.period_range("1999-01", "1999-12", freq="M")
    pd.testing.assert_frame_equal(momentum_12_2(history, longer, labels), momentum_12_2(history.loc[:"1999-11"], longer, labels))


def test_earliest_legal_month(history, config):
    labels = config["data"]["labels"]
    with pytest.raises(ContractError, match="signal_window_missing_months"):
        momentum_12_2(history, pd.period_range("1998-12", periods=1, freq="M"), labels)
    assert len(momentum_12_2(history.loc[:"1998-12"], pd.period_range("1999-01", periods=1, freq="M"), labels)) == 1


@pytest.mark.parametrize("mutation", ["missing_month", "nan", "inf", "duplicate", "label_change"])
def test_incomplete_window_is_rejected(history, config, mutation):
    if mutation == "missing_month": history = history.drop(pd.Period("1998-06", "M"))
    if mutation == "nan": history.iloc[5, 3] = np.nan
    if mutation == "inf": history.iloc[5, 3] = np.inf
    if mutation == "duplicate": history = pd.concat([history, history.iloc[[5]]])
    if mutation == "label_change": history = history.rename(columns={history.columns[0]: "SYNTHETIC_CHANGED"})
    with pytest.raises(ContractError):
        momentum_12_2(history, pd.period_range("1999-01", periods=1, freq="M"), config["data"]["labels"])


def test_ties_negative_signals_column_order_and_full_weights(config):
    labels = config["data"]["labels"]
    signal = pd.DataFrame(-0.2, index=pd.period_range("1999-01", periods=1, freq="M"), columns=labels)
    weights = target_weights(signal)
    pd.testing.assert_frame_equal(weights, target_weights(signal[labels[::-1]]))
    mom5 = weights.loc[weights["strategy"] == "MOM5"]
    assert mom5.loc[mom5["weight"] > 0, "industry"].tolist() == sorted(labels)[:5]
    for strategy, selected in weights.groupby("strategy"):
        assert len(selected) == 49 and (selected["weight"] >= 0).all()
        assert selected["weight"].sum() == pytest.approx(1.0)
        assert int((selected["weight"] > 0).sum()) == (5 if strategy == "MOM5" else 49)
    ranked = ranked_signals(signal)
    assert ranked.sort_values("rank")["industry"].tolist() == sorted(labels)
    assert set(ranked["rank"]) == set(range(1, 50))
