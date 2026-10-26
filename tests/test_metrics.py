"""SYNTHETIC wealth paths; exact metric conventions, not financial evidence."""
import numpy as np
import pandas as pd
import pytest

from alphalab.metrics import performance, summaries


def test_initial_point_drawdown_rf_once_and_annualization():
    net=np.array([-.2,.25,.1]); nav=np.array([.8,1,1.1]); rf=np.array([.01,.02,.03])
    result=performance(net,rf,nav)
    excess=np.array([-.21,.23,.07])
    assert result['max_drawdown']==pytest.approx(.2)
    assert result['cagr']==pytest.approx(1.1**4-1)
    assert result['annualized_net_volatility']==pytest.approx(np.std(net,ddof=1)*np.sqrt(12))
    assert result['sharpe']==pytest.approx(excess.mean()/np.std(excess,ddof=1)*np.sqrt(12))
    zero=performance(np.full(216,.01),np.full(216,.001),np.cumprod(np.full(216,1.01)))
    assert np.isnan(zero['sharpe']) and not zero['sharpe_defined']


def test_active_return_named_benchmarks_and_cagr_difference():
    rows=[]
    months=pd.period_range('2000-01',periods=3,freq='M')
    for name,ret in [('EW49',[.01,.02,-.01]),('MOM5',[.03,-.01,.04]),('EW49_VOL10',[.005,.01,0]),('MOM5_VOL10',[.02,0,.03])]:
        nav=1
        for month,value in zip(months,ret):
            nav_before=nav
            nav*=1+value
            rows.append(dict(holding_month=month,strategy=name,cost_bps=10,net_return=value,nav=nav,nav_before=nav_before,RF=.001,gross_traded_fraction=.2,cash_weight=.3,risky_weight=.7))
    summary,active,differences=summaries(pd.DataFrame(rows))
    row=differences.loc[(differences.strategy=='MOM5_VOL10') & (differences.benchmark=='EW49_VOL10')].iloc[0]
    assert row.annualized_mean_active_return==pytest.approx(12*np.mean([.015,-.01,.03]))
    cagr=summary.set_index('strategy').cagr
    assert row.cagr_difference==pytest.approx(cagr['MOM5_VOL10']-cagr['EW49_VOL10'])
    assert set(active.loc[active.strategy=='MOM5_VOL10','benchmark'])=={'EW49','EW49_VOL10'}
    np.testing.assert_allclose(summary.annualized_gross_traded_fraction,2.4)
