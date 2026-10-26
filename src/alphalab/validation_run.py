"""Fixed Day4 orchestration and pre-authorized-only future OOS continuation."""
from __future__ import annotations
import json
import time
from pathlib import Path
import numpy as np
import pandas as pd
from .access import load_config, load_research, HoldoutLocked, log_access
from .data import sha256, utc_now, read_product
from .research import FROZEN_DESIGN, verify_day2_snapshot, _csv, _git
from .freeze import environment, protected_files, hash_map, input_hashes, check_authorization, verify_freeze
from .evaluation import main_path, segment_reports, sensitivity_paths, wide_history
from .signals import return_panel
from .validation import require
from .metrics import summaries, performance


def experiments(root):
    e=json.loads((root/'config/experiments.json').read_text())
    require(e['hac']=={'maxlags':6,'kernel':'bartlett','use_correction':False,'use_t':False,'ci_multiplier':1.96,'explicit_intercept':True},'fixed_hac_required')
    require(e['segments']=={'research':['2000-01','2017-12'],'validation':['2018-01','2023-12'],'validation_2018_2020':['2018-01','2020-12'],'validation_2021_2023':['2021-01','2023-12']},'fixed_segments_required')
    expected=[f'{s}:{c}' for s in FROZEN_DESIGN['strategies'] for c in [0,10,20]]
    require(e['main_experiments']==[{'id':i,'strategy':i.split(':')[0],'cost_bps':int(i.split(':')[1])} for i in expected],'fixed_main_experiments')
    require(e['day5']=={'range':['2024-01','2025-12'],'experiment_ids':expected,'inference_label':'exploratory: 24 months; no stable alpha claims','sensitivities':False,'parameter_tuning':False},'fixed_day5_experiments')
    require(e['sensitivities']==[{'id':'MOM10_12_2','top_n':10,'lags':[12,2],'cost_bps':10,'execute':True},{'id':'MOM5_6_2','top_n':5,'lags':[6,2],'cost_bps':10,'execute':True}],'fixed_sensitivities')
    require(e['inference_segments']==['research','validation'],'fixed_inference_segments')
    return e


def compare_tables(old, new):
    require(list(old.columns)==list(new.columns) and len(old)==len(new),'prefix_table_shape')
    diffs={}
    for col in old:
        if pd.api.types.is_numeric_dtype(old[col]):
            a,b=old[col].to_numpy(float),new[col].to_numpy(float)
            require(np.array_equal(np.isnan(a),np.isnan(b)),'prefix_nan_changed')
            delta=float(np.max(np.abs(a-b),initial=0)) if not np.isnan(a).all() else 0.
            delta=float(np.nanmax(np.abs(a-b))) if np.isfinite(a).any() else 0.
            require(delta <= (1e-10 if col in ['nav','nav_before','cost_amount'] else 1e-12),'research_prefix_numeric_mismatch')
            diffs[col]=delta
        else: require(old[col].astype(str).tolist()==new[col].astype(str).tolist(),'prefix_keys_changed')
    return diffs


def prefix_check(root,tables):
    result={}
    for name in ['monthly_results.csv','target_weights.csv','drift_weights.csv','risk_estimates.csv','base_gross_returns.csv']:
        old=pd.read_csv(root/'outputs/day3'/name,float_precision='round_trip')
        new=tables[name].copy();new['holding_month']=new.holding_month.astype(str)
        new=new.loc[new.holding_month<='2017-12'].reset_index(drop=True)
        result[name]=compare_tables(old,new)
    return {'status':'PASS','absolute_tolerances':{'nav':1e-10,'returns_costs_weights':1e-12},'max_differences':result}


def save_run(root,day,tables,extra,snapshot,started,execution_extra=None):
    output=root/f'outputs/{day}'
    payloads={n:_csv(t) for n,t in tables.items()}
    payloads.update({n:(json.dumps(v,sort_keys=True,indent=2,allow_nan=False)+'\n').encode() for n,v in extra.items()})
    protected=hash_map(root,protected_files(root))
    impl=_git(root,'log','-1','--format=%H','--','src','tests','config','pyproject.toml','uv.lock')
    metadata={n:{'sha256':sha256(b),'bytes':len(b),**({'rows':len(tables[n])} if n in tables else {})} for n,b in payloads.items()}
    manifest={'stage':day.upper(),'implementation_commit':impl,'protected_hashes':protected,'environment':environment(),
              'input_hashes':input_hashes(root,snapshot),'outputs':metadata,'holdout_status':'LOCKED',
              'research_range':['1998-01','2023-12'] if day=='day4' else ['2024-01','2025-12'],
              'inference':'OLS explicit intercept; HAC6 Bartlett, correction=False, use_t=False, CI +/-1.96 SE',
              'initialization':'2000-01 all cash; all later boundaries continue state','terminal_liquidation':False}
    payloads['run_manifest.json']=(json.dumps(manifest,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
    for n,payload in payloads.items(): require(not (output/n).exists() or (output/n).read_bytes()==payload,'existing_'+day+'_output_mismatch_preserve_history')
    output.mkdir(parents=True,exist_ok=True)
    for n,payload in payloads.items():
        if not (output/n).exists(): (output/n).write_bytes(payload)
    event={'utc':utc_now(),'elapsed_seconds':time.perf_counter()-started,'HEAD':_git(root,'rev-parse','HEAD'),
           'worktree_dirty':bool(_git(root,'status','--porcelain=v1')),'run_manifest_sha256':sha256(payloads['run_manifest.json']),**(execution_extra or {})}
    with (output/'run_execution.jsonl').open('a') as f:f.write(json.dumps(event,sort_keys=True)+'\n')
    return {'status':'PASS','stage':day,'monthly_rows':len(tables['monthly_results.csv']),'run_manifest_sha256':event['run_manifest_sha256'],'OOS':'LOCKED' if day=='day4' else 'HQ_AUTHORIZED_EXECUTION'}


def run_validation(root: Path,end='2023-12'):
    started=time.perf_counter()
    # Guard before snapshot loading or any research arithmetic.
    if pd.Period(end,'M')>pd.Period('2023-12','M'):
        log_access(root,'research_denied','DENIED','1998-01',end)
        raise HoldoutLocked('OOS_LOCKED: DAY4_RESEARCH_END_2023_12')
    require(end=='2023-12','day4_fixed_end')
    config=load_config(root);require(config['phase']=='DAY4' and config['design']==FROZEN_DESIGN,'day4_frozen_config')
    e=experiments(root);snapshot=verify_day2_snapshot(root)
    industries,factors=load_research(root,start='1998-01',end='2023-12')
    panel=return_panel(industries,config['data']['labels']);factors=factors.set_index('month')
    require(panel.index.equals(pd.period_range('1998-01','2023-12',freq='M')),'day4_input_calendar')
    calendar=pd.period_range('2000-01','2023-12',freq='M')
    tables,terminal,signals=main_path(panel,factors,calendar,config['data']['labels'])
    prefix=prefix_check(root,tables)
    prior=json.loads((root/'outputs/day3/terminal_state.json').read_text())
    resumed_panel=pd.concat([wide_history(prior['signal_return_history'],'month'),panel.loc['2018-01':]])
    restored,_,_=main_path(resumed_panel,factors.loc[resumed_panel.index],pd.period_range('2018-01','2023-12',freq='M'),config['data']['labels'],prior)
    restore={}
    for name in ['monthly_results.csv','target_weights.csv','drift_weights.csv','risk_estimates.csv']:
        current=tables[name].loc[tables[name].holding_month>=pd.Period('2018-01','M')].reset_index(drop=True)
        restore[name]=compare_tables(restored[name].reset_index(drop=True),current)
    diag=segment_reports(tables,signals,panel,factors,e['segments'],e['inference_segments'])
    terminal['market_nav']=float(tables['market_reference.csv'].nav.iloc[-1])
    tables.update(sensitivity_paths(panel,factors,calendar,signals,e['sensitivities'],e['segments'],tables['monthly_results.csv']))
    tables['factor_inputs_research_validation.csv']=factors.loc[calendar,['Mkt-RF','SMB','HML','Mom','RF']].rename_axis('month').reset_index()
    tables['boundary_industry_inputs.csv']=industries.loc[industries.month.between(pd.Period('2017-01','M'),pd.Period('2018-03','M'))]
    tables['boundary_factor_inputs.csv']=factors.loc['2017-01':'2018-03'].reset_index()
    provenance={'units':'decimal monthly returns','source_processed_hashes':{p:v['sha256'] for p,v in snapshot['products'].items() if '/research/' in p or '/validation/' in p},
                'slices':{n:{'sha256':sha256(_csv(tables[n])),'range':['2000-01','2023-12'] if n.startswith('factor_inputs') else ['2017-01','2018-03']} for n in ['factor_inputs_research_validation.csv','boundary_industry_inputs.csv','boundary_factor_inputs.csv']}}
    return save_run(root,'day4',tables,{'terminal_state.json':terminal,'diagnostic_summary.json':diag,'prefix_regression.json':prefix,
                    'continuation_check.json':{'status':'PASS','from':'Day3 saved terminal state','max_differences':restore},'audit_input_provenance.json':provenance},snapshot,started)


def run_oos(root: Path, authorization: Path | None):
    started=time.perf_counter()
    begun=False
    try:
        frozen=check_authorization(root,authorization)
        config=load_config(root);e=experiments(root)
        snapshot=verify_day2_snapshot(root)
        prior=json.loads((root/'outputs/day4/terminal_state.json').read_text())
        require(prior['last_month']=='2023-12','oos_prior_month')
        # Dedicated read channel reached only after every authorization/hash check.
        log_access(root,'authorized_oos','BEGIN')
        begun=True
        industries=read_product(root,'holdout','industry_returns',snapshot)
        factors=read_product(root,'holdout','factors',snapshot)
        calendar=pd.period_range('2024-01','2025-12',freq='M')
        require(set(industries.month)==set(calendar) and factors.month.tolist()==list(calendar),'oos_partition_dates')
        panel=pd.concat([wide_history(prior['signal_return_history'],'month'),return_panel(industries,config['data']['labels'])])
        _,past_factors=load_research(root,start='2023-01',end='2023-12')
        factors=pd.concat([past_factors,factors]).set_index('month')
        tables,terminal,signals=main_path(panel,factors,calendar,config['data']['labels'],prior)
        diag=segment_reports(tables,signals,panel,factors,{'oos':['2024-01','2025-12']},['oos'],prior['market_nav'])
        terminal['market_nav']=float(tables['market_reference.csv'].nav.iloc[-1])
        tables['factor_inputs_oos.csv']=factors.loc[calendar].reset_index()
        # Future Day5 retrospective display only, after authorized continuation.
        past=pd.read_csv(root/'outputs/day4/monthly_results.csv',float_precision='round_trip')
        past['holding_month']=pd.PeriodIndex(past.holding_month,freq='M')
        combined=pd.concat([past,tables['monthly_results.csv']],ignore_index=True).sort_values(['holding_month','strategy','cost_bps'])
        full_summary,_,full_active=summaries(combined)
        full_summary.insert(0,'interpretation','retrospective full sample, not untouched evaluation')
        tables['retrospective_full_sample_summary.csv']=full_summary
        tables['retrospective_full_sample_active_summary.csv']=full_active
        past_market=pd.read_csv(root/'outputs/day4/market_reference.csv',float_precision='round_trip')
        market=pd.concat([past_market,tables['market_reference.csv']],ignore_index=True)
        tables['retrospective_market_summary.csv']=pd.DataFrame([{'interpretation':'retrospective no-fee market reference',**performance(market.total_return.to_numpy(),market.RF.to_numpy(),market.nav.to_numpy(),float(market.nav_before.iloc[0]))}])
        result=save_run(root,'day5',tables,{'terminal_state.json':terminal,'diagnostic_summary.json':diag},snapshot,started,
                        {'authorization_sha256':sha256(authorization.read_bytes()),'freeze_sha256':sha256((root/'reports/research_freeze.json').read_bytes()),'interpretation':e['day5']['inference_label']})
        log_access(root,'authorized_oos','PASS')
        return result
    except Exception:
        log_access(root,'authorized_oos' if begun else 'research_denied','FAIL' if begun else 'DENIED')
        # Never expose upstream rows/values even for unexpected third-party errors.
        raise HoldoutLocked('OOS_LOCKED_OR_FAILED: controlled authorization/integrity/computation failure') from None


def reproduce_or_report(root,stage,authorization=None,report=False):
    if stage=='oos': return run_oos(root,authorization)
    # Default never crosses 2023. Once frozen, fail before any calculation if changed.
    verify_freeze(root)
    if report:
        return {'status':'PASS','stage':'day4','range':['2000-01','2023-12'],'OOS':'LOCKED','report':'reports/day4_validation_audit.md'}
    return run_validation(root)
