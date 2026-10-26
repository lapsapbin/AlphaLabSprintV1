"""HQ-fixed OLS + Bartlett HAC(6), no correction, normal ±1.96 SE."""
from __future__ import annotations
import numpy as np
import pandas as pd
from statsmodels.regression.linear_model import OLS
from .portfolio import check_calendar
from .validation import require

FACTORS = ['Mkt-RF', 'SMB', 'HML', 'Mom']
HAC = {'maxlags': 6, 'kernel': 'bartlett', 'use_correction': False}


def ols_hac(y: np.ndarray, x: np.ndarray, names: list[str]) -> pd.DataFrame:
    y, x = np.asarray(y, float), np.asarray(x, float)
    require(y.ndim == 1 and x.shape == (len(y), len(names)) and len(y) > max(6, len(names)), 'hac_shapes')
    require(np.isfinite(x).all() and np.isfinite(y).all(), 'hac_nonfinite')
    require(names[0] == 'alpha' and np.array_equal(x[:, 0], np.ones(len(y))), 'hac_explicit_intercept')
    require(np.linalg.matrix_rank(x) == x.shape[1], 'hac_full_rank')
    fit = OLS(y, x, hasconst=True, missing='raise').fit(cov_type='HAC', cov_kwds=HAC, use_t=False)
    require(np.isfinite(fit.params).all() and np.isfinite(fit.bse).all(), 'hac_finite_estimates')
    rows=[]
    for i,name in enumerate(names):
        b,se=float(fit.params[i]),float(fit.bse[i])
        rows.append({'coefficient':name,'estimate':b,'hac_se':se,'ci_low':b-1.96*se,'ci_high':b+1.96*se,
                     'n_months':len(y),'r_squared':float(fit.rsquared),
                     'alpha_annual_arithmetic':12*b if name=='alpha' else np.nan,
                     'alpha_se_annual':12*se if name=='alpha' else np.nan,
                     'alpha_ci_low_annual':12*(b-1.96*se) if name=='alpha' else np.nan,
                     'alpha_ci_high_annual':12*(b+1.96*se) if name=='alpha' else np.nan})
    return pd.DataFrame(rows)


def factor_regression(net: pd.Series, factors: pd.DataFrame) -> pd.DataFrame:
    check_calendar(net.index)
    check_calendar(factors.index)
    require(net.index.equals(factors.index), 'regression_month_alignment')
    require(not factors.columns.has_duplicates and set(factors.columns)==set(FACTORS+['RF']), 'regression_factor_fields')
    values=factors[FACTORS+['RF']].to_numpy(float)
    require(np.isfinite(values).all(), 'regression_factor_nonfinite')
    x=np.column_stack([np.ones(len(net)), factors[FACTORS].to_numpy(float)])
    result=ols_hac(net.to_numpy(float)-factors.RF.to_numpy(float),x,['alpha']+FACTORS)
    result['start'],result['end']=str(net.index[0]),str(net.index[-1])
    return result


def ic_mean_hac(ic: pd.Series) -> dict:
    check_calendar(ic.index)
    values=ic.to_numpy(float)
    require(not np.isinf(values).any(), 'ic_hac_infinite')
    valid=int(np.isfinite(values).sum())
    common={'months':len(ic),'valid_months':valid,'undefined_months':len(ic)-valid,
            'start':str(ic.index[0]),'end':str(ic.index[-1])}
    if valid != len(ic):
        return {**common,'status':'UNDEFINED_IC_PREVENTS_CONTIGUOUS_HAC','mean':None,'hac_se':None,'ci_low':None,'ci_high':None}
    row=ols_hac(values,np.ones((len(values),1)),['alpha']).iloc[0]
    return {**common,'status':'PASS','mean':float(row.estimate),'hac_se':float(row.hac_se),
            'ci_low':float(row.ci_low),'ci_high':float(row.ci_high)}
