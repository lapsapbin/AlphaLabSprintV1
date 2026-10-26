"""SYNTHETIC lag/history and target tests; no real-alpha inference."""
import numpy as np
import pandas as pd
import pytest

from alphalab.portfolio import base_gross_returns, risk_targets
from alphalab.backtest import PortfolioState, simulate
from alphalab.signals import momentum_12_2, target_weights
from alphalab.validation import ContractError


def base_fixture():
    calendar = pd.period_range('1999-01','2000-03',freq='M')
    weights = {'MOM5': pd.DataFrame({'A': [.8,.2,.8]*5,'B':[.2,.8,.2]*5}, index=calendar),
               'EW49': pd.DataFrame(.5, index=calendar, columns=['A','B'])}
    returns = pd.DataFrame({'A':np.arange(15)*.02-.15, 'B':np.arange(15)[::-1]*.003}, index=calendar)
    return weights, returns


def test_actual_historical_base_and_exact_12_lag_sigma():
    weights, returns = base_fixture()
    gross = base_gross_returns(weights, returns)
    expected = [sum(weights['MOM5'].iloc[i,j]*returns.iloc[i,j] for j in range(2)) for i in range(15)]
    np.testing.assert_allclose(gross.MOM5, expected)
    calendar = pd.period_range('2000-01','2000-03',freq='M')
    targets, risk = risk_targets(weights, gross, calendar)
    expected_sigma = np.std(expected[:12],ddof=1)*np.sqrt(12)
    row = risk.loc[(risk.holding_month==calendar[0]) & (risk.strategy=='MOM5_VOL10')].iloc[0]
    assert row.sigma_history_start=='1999-01' and row.sigma_history_end=='1999-12'
    assert row.sigma_annual == pytest.approx(expected_sigma)
    assert row.risk_scale == pytest.approx(min(1,.1/expected_sigma))
    assert risk.loc[(risk.holding_month==calendar[0]) & (risk.strategy=='EW49_VOL10'),'sigma_annual'].iloc[0] != row.sigma_annual
    changed = gross.copy(); changed.loc['2000-01':] = 9
    again, _ = risk_targets(weights, changed, calendar[:1])
    for name in targets:
        pd.testing.assert_frame_equal(targets[name].iloc[:1],again[name])
    changed = gross.copy(); changed.loc['1999-12','MOM5'] = 2
    past_changed, _ = risk_targets(weights,changed,calendar[:1])
    assert not past_changed['MOM5_VOL10'].equals(targets['MOM5_VOL10'].iloc[:1])
    for name, frame in targets.items():
        assert (frame.to_numpy()>=0).all() and (frame.sum(axis=1)<=1+1e-12).all()
    # Restore the last 12 base observations for a new segment; no reset/history shortcut.
    continued, _ = risk_targets(weights, gross.loc['1999-02':], calendar[1:])
    for name in targets:
        pd.testing.assert_frame_equal(targets[name].iloc[1:],continued[name])


def test_zero_vol_cap_and_missing_window_fail():
    weights, returns = base_fixture()
    gross = base_gross_returns(weights, returns)
    calendar = pd.period_range('2000-01',periods=1,freq='M')
    gross.loc[:,'MOM5'] = .01
    targets, risk = risk_targets(weights,gross,calendar)
    row = risk.loc[risk.strategy=='MOM5_VOL10'].iloc[0]
    assert row.sigma_annual==0 and row.risk_scale==1
    pd.testing.assert_frame_equal(targets['MOM5'],targets['MOM5_VOL10'])
    for bad in [gross.drop(gross.index[3]), gross.mask(gross.index.to_series().eq(gross.index[3]),axis=0)]:
        with pytest.raises(ContractError,match='12_complete|nonfinite'):
            risk_targets(weights,bad,calendar)


def test_end_to_end_current_future_invariance_and_historical_resume(config):
    labels=sorted(config['data']['labels'])
    months=pd.period_range('1998-01','2000-04',freq='M')
    values=np.arange(len(months))[:,None]*.002 + np.arange(49)[None,:]*.0003
    returns=pd.DataFrame(values,index=months,columns=labels)
    def bases(data, calendar):
        long=target_weights(momentum_12_2(data,calendar,labels))
        return {name:long.loc[long.strategy==name].pivot(index='holding_month',columns='industry',values='weight') for name in ('MOM5','EW49')}
    base=bases(returns,pd.period_range('1999-01','2000-04',freq='M'))
    gross=base_gross_returns(base,returns)
    target_calendar=pd.period_range('2000-01','2000-04',freq='M')
    whole,_=risk_targets(base,gross,target_calendar)
    changed=returns.copy(); changed.loc['2000-02':]=-0.9
    other_base=bases(changed,pd.period_range('1999-01','2000-04',freq='M'))
    other_gross=base_gross_returns(other_base,changed)
    other,_=risk_targets(other_base,other_gross,target_calendar)
    for name in whole:
        pd.testing.assert_frame_equal(whole[name].iloc[:2],other[name].iloc[:2])
    # Future-free target generation uses retained 12 raw months and base history.
    next_calendar=pd.period_range('2000-03',periods=1,freq='M')
    partial=bases(returns.loc['1999-03':'2000-02'],next_calendar)
    resumed,_=risk_targets(partial,gross.loc['1999-03':'2000-02'],next_calendar)
    for name in whole:
        pd.testing.assert_frame_equal(whole[name].loc[next_calendar],resumed[name])
    # Combined restoration: history-derived VOL target plus serialized NAV/drift.
    rf=pd.Series(.001,index=target_calendar)
    all_rows,_,all_state=simulate(whole['MOM5_VOL10'].iloc[:3],returns,rf,10)
    first,_,state=simulate(whole['MOM5_VOL10'].iloc[:2],returns,rf,10)
    resumed_rows,_,resumed_state=simulate(resumed['MOM5_VOL10'],returns,rf,10,PortfolioState.from_dict(state.to_dict()))
    pd.testing.assert_frame_equal(all_rows,pd.concat([first,resumed_rows],ignore_index=True))
    assert all_state==resumed_state
