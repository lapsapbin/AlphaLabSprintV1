"""Shared fixed numerical path for Day4 and future authorized Day5 continuation.

No IO or access authority here: callers must select the permitted data first.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from .backtest import PortfolioState, simulate
from .diagnostics import research_diagnostics
from .inference import factor_regression, ic_mean_hac, FACTORS
from .metrics import summaries, performance
from .portfolio import BASES, STRATEGIES, base_gross_returns, risk_targets, check_calendar
from .signals import momentum_12_2, momentum_window, ranked_signals, target_weights
from .validation import require


def wide_history(records, key):
    frame=pd.DataFrame(records).set_index(key)
    frame.index=pd.PeriodIndex(frame.index,freq='M',name=key)
    return frame


def targets_and_history(panel, calendar, labels, prior=None):
    signal_calendar=pd.period_range(calendar[0] if prior else '1999-01',calendar[-1],freq='M')
    signals=momentum_12_2(panel,signal_calendar,labels)
    long=target_weights(signals)
    weights={b:long.loc[long.strategy==b].pivot(index='holding_month',columns='industry',values='weight').sort_index() for b in BASES}
    gross=base_gross_returns(weights,panel)
    if prior:
        gross=pd.concat([wide_history(prior['base_gross_history'],'holding_month'),gross])
        check_calendar(gross.index)
    targets,risk=risk_targets(weights,gross,calendar)
    return signals,gross,targets,risk


def main_path(panel, factors, calendar, labels, prior=None):
    check_calendar(calendar)
    require(factors.index.equals(panel.index), 'evaluation_factor_alignment')
    signals,gross,targets,risk=targets_and_history(panel,calendar,labels,prior)
    results,drifts,states,target_tables=[],[],{},[]
    for strategy in STRATEGIES:
        view=risk.loc[risk.strategy==strategy].set_index('holding_month')
        long=targets[strategy].rename_axis('holding_month').reset_index().melt(id_vars='holding_month',var_name='industry',value_name='weight')
        long['strategy']=strategy;target_tables.append(long)
        for cost in (0,10,20):
            initial=PortfolioState.from_dict(prior['states'][f'{strategy}:{cost}']) if prior else None
            monthly,drift,state=simulate(targets[strategy],panel.loc[calendar],factors.loc[calendar,'RF'],cost,initial)
            monthly['strategy'],monthly['cost_bps']=strategy,cost
            monthly['risk_scale']=monthly.holding_month.map(view.risk_scale)
            monthly['sigma_annual']=monthly.holding_month.map(view.sigma_annual)
            results.append(monthly)
            if cost==0:
                reference=drift.copy();drift['strategy']=strategy;drifts.append(drift)
            else: require(reference.equals(drift),'evaluation_cost_invariant_drift')
            states[f'{strategy}:{cost}']=state.to_dict()
    hist=panel.loc[:calendar[-1]].iloc[-12:].reset_index();hist['month']=hist['month'].astype(str)
    gh=gross.loc[:calendar[-1]].iloc[-12:].reset_index();gh['holding_month']=gh['holding_month'].astype(str)
    terminal={'last_month':str(calendar[-1]),'states':states,'signal_return_history':hist.to_dict('records'),
              'base_gross_history':gh.to_dict('records'),'continuation_rule':'Continue last_month+1 with NAV, drift and historical gross returns.'}
    tables={'monthly_results.csv':pd.concat(results).sort_values(['holding_month','strategy','cost_bps']).reset_index(drop=True),
            'target_weights.csv':pd.concat(target_tables).sort_values(['holding_month','strategy','industry']).reset_index(drop=True),
            'drift_weights.csv':pd.concat(drifts).sort_values(['holding_month','strategy','industry']).reset_index(drop=True),
            'risk_estimates.csv':risk,'base_gross_returns.csv':gross.reset_index(),'momentum_12_2.csv':ranked_signals(signals)}
    return tables,terminal,signals


def segment_reports(tables, signals, panel, factors, segments, inference_segments, market_start_nav=1.0):
    monthly=tables['monthly_results.csv']; perf,active,diff,diags,ic_all,q_all,reg,ic_hac,market_s=[],[],[],[],[],[],[],[],[]
    calendar=pd.PeriodIndex(sorted(monthly.holding_month.unique()),freq='M')
    mret=factors.loc[calendar,'Mkt-RF']+factors.loc[calendar,'RF']
    nav=market_start_nav*np.cumprod(1+mret.to_numpy())
    market=pd.DataFrame({'holding_month':calendar,'total_return':mret.to_numpy(),'RF':factors.loc[calendar,'RF'].to_numpy(),
                         'nav':nav,'nav_before':np.r_[market_start_nav,nav[:-1]]})
    for name,(lo,hi) in segments.items():
        selected=monthly.loc[monthly.holding_month.between(pd.Period(lo,'M'),pd.Period(hi,'M'))]
        expected=pd.period_range(lo,hi,freq='M')
        require(len(selected)==len(expected)*12,'segment_shape')
        a,b,c=summaries(selected)
        for frame,dest in [(a,perf),(b,active),(c,diff)]:
            frame.insert(0,'segment',name);dest.append(frame)
        ic,q,d=research_diagnostics(signals,panel,lo,hi)
        d['segment']=name;diags.append(d)
        ic.insert(0,'segment',name);q.insert(0,'segment',name);ic_all.append(ic);q_all.append(q)
        m=market.loc[market.holding_month.between(pd.Period(lo,'M'),pd.Period(hi,'M'))]
        market_s.append({'segment':name,'reference':'Mkt-RF+RF (no fees; not an ETF)',**performance(m.total_return.to_numpy(),m.RF.to_numpy(),m.nav.to_numpy(),float(m.nav_before.iloc[0]))})
        if name in inference_segments:
            ic_hac.append({'segment':name,**ic_mean_hac(ic.set_index('holding_month').rank_ic)})
            for (strategy,cost),group in selected.groupby(['strategy','cost_bps'],sort=True):
                f=factor_regression(group.set_index('holding_month').net_return,factors.loc[expected,FACTORS+['RF']])
                f['segment'],f['strategy'],f['cost_bps']=name,strategy,cost;reg.append(f)
    tables.update({'performance_summary.csv':pd.concat(perf),'active_returns.csv':pd.concat(active),'active_summary.csv':pd.concat(diff),
                   'rank_ic.csv':pd.concat(ic_all),'quintile_returns.csv':pd.concat(q_all),'factor_regressions.csv':pd.concat(reg),
                   'ic_hac.csv':pd.DataFrame(ic_hac),'market_reference.csv':market,'market_reference_summary.csv':pd.DataFrame(market_s)})
    return diags


def sensitivity_paths(panel, factors, calendar, signals, specs, segments, main):
    results,targets=[],[]
    for spec in specs:
        require(spec['execute'] is True,'fixed_sensitivities_required')
        s=signals.loc[calendar] if spec['lags']==[12,2] else momentum_window(panel,calendar,list(panel.columns),6)
        ranks=ranked_signals(s);ranks['weight']=np.where(ranks['rank']<=spec['top_n'],1/spec['top_n'],0.)
        wide=ranks.pivot(index='holding_month',columns='industry',values='weight').sort_index()
        rows,_,_=simulate(wide,panel.loc[calendar],factors.loc[calendar,'RF'],10)
        rows['strategy'],rows['cost_bps']=spec['id'],10;rows['risk_scale']=1.;results.append(rows)
        t=ranks[['holding_month','industry','weight']].copy();t['strategy']=spec['id'];targets.append(t)
    monthly=pd.concat(results).sort_values(['holding_month','strategy']).reset_index(drop=True)
    summary,active=[],[]
    for name,(lo,hi) in segments.items():
        mask=monthly.holding_month.between(pd.Period(lo,'M'),pd.Period(hi,'M'))
        for strategy,g in monthly.loc[mask].groupby('strategy'):
            m=performance(g.net_return.to_numpy(),g.RF.to_numpy(),g.nav.to_numpy(),float(g.nav_before.iloc[0]))
            summary.append({'segment':name,'strategy':strategy,'cost_bps':10,**m,
                            'mean_gross_traded_fraction':float(g.gross_traded_fraction.mean()),'annualized_gross_traded_fraction':float(12*g.gross_traded_fraction.mean()),'mean_cash_weight':float(g.cash_weight.mean())})
            for b in ['EW49','MOM5']:
                ref=main.loc[(main.strategy==b)&(main.cost_bps==10)&main.holding_month.isin(g.holding_month)]
                require(g.holding_month.tolist()==ref.holding_month.tolist(),'sensitivity_active_alignment')
                rc=performance(ref.net_return.to_numpy(),ref.RF.to_numpy(),ref.nav.to_numpy(),float(ref.nav_before.iloc[0]))['cagr']
                active.append({'segment':name,'strategy':strategy,'benchmark':b,'cost_bps':10,'annualized_mean_active_return':float(12*np.mean(g.net_return.to_numpy()-ref.net_return.to_numpy())),'cagr_difference':m['cagr']-rc})
    return {'sensitivity_monthly.csv':monthly,'sensitivity_targets.csv':pd.concat(targets),'sensitivity_summary.csv':pd.DataFrame(summary),'sensitivity_active_summary.csv':pd.DataFrame(active)}
