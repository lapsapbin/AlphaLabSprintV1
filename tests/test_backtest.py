"""SYNTHETIC accounting fixtures; no test is evidence of financial alpha."""
from decimal import Decimal, localcontext
import json

import numpy as np
import pandas as pd
import pytest

from alphalab.backtest import PortfolioState, simulate, solve_cost
from alphalab.validation import ContractError


def decimal_path(weights, returns, rf, c):
    """Independent piecewise closed form, not the production bisection."""
    with localcontext() as ctx:
        ctx.prec = 50
        D = lambda x: Decimal(str(x))
        b = [D(0)] * len(weights[0]); nav = D(1); fee = D(c)
        result = []
        for row, ret, cash_return in zip(weights, returns, rf, strict=True):
            w, r, rf_value = list(map(D, row)), list(map(D, ret)), D(cash_return)
            breaks = sorted({D(0), D(1)} | {bi / wi for bi, wi in zip(b, w) if wi and 0 < bi / wi < 1})
            for lo, hi in zip(breaks[:-1], breaks[1:], strict=True):
                mid = (lo + hi) / 2
                signs = [D(1) if mid * wi >= bi else D(-1) for bi, wi in zip(b, w)]
                k = (1 + fee * sum(s * bi for s, bi in zip(signs, b))) / (1 + fee * sum(s * wi for s, wi in zip(signs, w)))
                if lo <= k <= hi:
                    break
            else:
                raise AssertionError('No closed-form root')
            traded = sum(abs(k * wi - bi) for wi, bi in zip(w, b))
            cash = 1 - sum(w)
            gross = sum(wi * ri for wi, ri in zip(w, r)) + cash * rf_value
            net = k * (1 + gross) - 1
            next_nav = nav * (1 + net)
            b = [wi * (1 + ri) / (1 + gross) for wi, ri in zip(w, r)]
            next_cash = cash * (1 + rf_value) / (1 + gross)
            result.append(dict(k=float(k), gross_traded_fraction=float(traded), cost_fraction=float(1-k),
                               cost_amount=float(nav*(1-k)), gross_return=float(gross), net_return=float(net),
                               nav=float(next_nav), end_cash_weight=float(next_cash), b=list(map(float,b))))
            nav = next_nav
        return result


@pytest.mark.parametrize('b,w,k_factor,d_factor', [
    ([0, 0], [1, 0], 'entry', 'entry'),
    ([1, 0], [0, 1], 'switch', 'switch'),
    ([.3, .5], [.3, .5], 'same', 'same'),
])
def test_closed_form_cost_calibrations(b, w, k_factor, d_factor):
    c = Decimal('.001')
    expected_k = {'entry': 1/(1+c), 'switch': (1-c)/(1+c), 'same': Decimal(1)}[k_factor]
    expected_d = {'entry': expected_k, 'switch': 1+expected_k, 'same': Decimal(0)}[d_factor]
    k, traded = solve_cost(np.array(b), np.array(w), float(c))
    assert k == pytest.approx(float(expected_k), abs=1e-15)
    assert traded == pytest.approx(float(expected_d), abs=1e-15)
    assert k + float(c)*traded == pytest.approx(1, abs=1e-15)
    assert k * sum(w) + k * (1-sum(w)) + (1-k) == pytest.approx(1)
    # Independently carry each calibration through the production settlement.
    calendar=pd.period_range('2000-01',periods=1,freq='M')
    target=pd.DataFrame([w],index=calendar,columns=['A','B'])
    realized=pd.DataFrame([[.10,-.05]],index=calendar,columns=['A','B'])
    state=PortfolioState(2.,dict(zip(['A','B'],b)),1-sum(b),'1999-12')
    settled,_,_=simulate(target,realized,pd.Series(.003,index=calendar),10,state)
    wd=list(map(lambda x:Decimal(str(x)),w))
    expected_gross=wd[0]*Decimal('.10')+wd[1]*Decimal('-.05')+(1-sum(wd))*Decimal('.003')
    expected_net=expected_k*(1+expected_gross)-1
    assert settled.loc[0,'cost_fraction']==pytest.approx(float(1-expected_k),abs=1e-15)
    assert settled.loc[0,'cost_amount']==pytest.approx(float(2*(1-expected_k)),abs=1e-15)
    assert settled.loc[0,'net_return']==pytest.approx(float(expected_net),abs=1e-15)
    assert settled.loc[0,'nav']==pytest.approx(float(2*(1+expected_net)),abs=1e-15)


def example():
    calendar = pd.period_range('2000-01', periods=3, freq='M')
    weights = pd.DataFrame([[.5,.5],[.5,.5],[.2,.3]], index=calendar, columns=['A','B'])
    returns = pd.DataFrame([[.1,-.1],[-.05,.2],[.08,-.04]], index=calendar, columns=['A','B'])
    rf = pd.Series([.002,.003,.004], index=calendar)
    return weights, returns, rf


def test_decimal_multimonth_cash_drift_nav_and_self_financing():
    weights, returns, rf = example()
    actual, drift, final = simulate(weights, returns, rf, 10)
    expected = decimal_path(weights.to_numpy().tolist(), returns.to_numpy().tolist(), rf.tolist(), '.001')
    for i, row in enumerate(expected):
        for name, value in row.items():
            if name != 'b':
                assert actual.loc[i, name] == pytest.approx(value, abs=2e-15)
        np.testing.assert_allclose(drift.loc[drift.holding_month == weights.index[i], 'end_weight'], row['b'], atol=1e-15)
    assert actual.loc[1, 'gross_traded_fraction'] > .09  # Same names/targets; unequal returns cause rebalancing.
    assert actual.loc[2, 'cash_weight'] == .5
    assert (actual[['cash_weight','pretrade_cash_weight','end_cash_weight']].to_numpy()>=0).all()
    assert final.nav == pytest.approx(expected[-1]['nav'])
    np.testing.assert_allclose(actual.gross_return-actual.net_return, actual.cost_fraction*(1+actual.gross_return), atol=1e-15)
    np.testing.assert_allclose(actual.nav_before, actual.nav_before*actual.k+actual.cost_amount, atol=1e-15)
    # Current/future returns and RF affect settlement, not current target/cost.
    altered = returns.copy(); altered.iloc[1:] += .2
    altered_rf = rf.copy(); altered_rf.iloc[1:] += .1
    changed, _, _ = simulate(weights, altered, altered_rf, 10)
    np.testing.assert_array_equal(actual.loc[:1, ['k','gross_traded_fraction']], changed.loc[:1, ['k','gross_traded_fraction']])


def test_zero_cost_monotone_wealth_and_resume_json_state():
    weights, returns, rf = example()
    outputs = [simulate(weights, returns, rf, c)[0] for c in (0,10,20)]
    np.testing.assert_array_equal(outputs[0].gross_return, outputs[0].net_return)
    for low, high in zip(outputs[:-1], outputs[1:], strict=True):
        assert (low.nav >= high.nav).all()
        np.testing.assert_array_equal(low.gross_return, high.gross_return)
    whole, drift_whole, end_whole = simulate(weights, returns, rf, 10)
    first, drift_first, state = simulate(weights.iloc[:1], returns.iloc[:1], rf.iloc[:1], 10)
    restored = PortfolioState.from_dict(json.loads(json.dumps(state.to_dict())))
    second, drift_second, end_second = simulate(weights.iloc[1:], returns.iloc[1:], rf.iloc[1:], 10, restored)
    pd.testing.assert_frame_equal(whole, pd.concat([first,second], ignore_index=True))
    pd.testing.assert_frame_equal(drift_whole, pd.concat([drift_first,drift_second], ignore_index=True))
    assert end_whole == end_second
    with pytest.raises(ContractError, match='prior_state'):
        simulate(weights.iloc[1:], returns.iloc[1:], rf.iloc[1:], 10)
    with pytest.raises(ContractError, match='continuity'):
        simulate(weights.iloc[2:], returns.iloc[2:], rf.iloc[2:], 10, state)


def test_bad_weights_nonfinite_and_zero_wealth_fail():
    weights, returns, rf = example()
    for vector in ([-.1,1.1],[.6,.6],[np.nan,.5]):
        with pytest.raises(ContractError):
            solve_cost(np.zeros(2), np.array(vector), .001)
    returns.iloc[0] = -1
    with pytest.raises(ContractError, match='zero_or_nonfinite'):
        simulate(weights, returns, rf, 10)
    returns.iloc[0] = np.nan
    with pytest.raises(ContractError, match='invalid_realized'):
        simulate(weights, returns, rf, 10)
    # Floating-point 49*(1/49) must not invent cash that rescues zero wealth.
    ew=pd.DataFrame(1/49,index=weights.index,columns=[f'I{i}' for i in range(49)])
    dead=pd.DataFrame(-1.,index=weights.index,columns=ew.columns)
    with pytest.raises(ContractError,match='zero_or_nonfinite'):
        simulate(ew,dead,rf,10)
