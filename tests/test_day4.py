"""SYNTHETIC tests only: no performance/alpha evidence or real holdout reads."""
import json
import shutil
import subprocess
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
import yaml
from alphalab import cli, freeze, validation_run as run
from alphalab.evaluation import main_path, wide_history, targets_and_history, segment_reports, sensitivity_paths
from alphalab.inference import factor_regression, ic_mean_hac, ols_hac, FACTORS
from alphalab.metrics import summaries
from alphalab.signals import momentum_window
from alphalab.data import sha256
from alphalab.validation import ContractError


def synthetic_panel(start='1998-01',end='2025-12'):
    rng=np.random.default_rng(419)
    index=pd.period_range(start,end,freq='M',name='month');labels=[f'SYNTHETIC_{i:02}' for i in range(49)]
    return pd.DataFrame(rng.normal(.004,.065,(len(index),49)),index=index,columns=labels),pd.DataFrame(rng.normal(.002,.02,(len(index),5)),index=index,columns=FACTORS+['RF'])


def oracle(y,x):
    inv=np.linalg.inv(x.T@x);b=inv@x.T@y;z=x*(y-x@b)[:,None];meat=z.T@z
    for lag in range(1,7):
        cross=z[lag:].T@z[:-lag];meat+=(1-lag/7)*(cross+cross.T)
    se=np.sqrt(np.diag(inv@meat@inv))
    return b,se,b-1.96*se,b+1.96*se


def test_hac_independent_sandwich_rf_once_columns_and_bad_calendar():
    _,f=synthetic_panel('2000-01','2005-12');rng=np.random.default_rng(86)
    error=rng.normal(0,.01,len(f));error[1:]+=.4*error[:-1]
    net=pd.Series(.002+f[FACTORS].to_numpy()@np.array([.7,-.2,.1,.3])+f.RF+error,index=f.index)
    got=factor_regression(net,f[f.columns[::-1]])
    expected=oracle(net.to_numpy()-f.RF.to_numpy(),np.column_stack([np.ones(len(f)),f[FACTORS].to_numpy()]))
    for col,value in zip(['estimate','hac_se','ci_low','ci_high'],expected):np.testing.assert_allclose(got[col],value,rtol=1e-10,atol=1e-13)
    np.testing.assert_allclose(got.iloc[0][['alpha_annual_arithmetic','alpha_se_annual','alpha_ci_low_annual','alpha_ci_high_annual']].astype(float),12*np.array([e[0] for e in expected]))
    for bad in [f.iloc[::-1],f.iloc[:-1],pd.concat([f,f.iloc[-1:]]),f.drop(f.index[4]),f.assign(SMB=np.nan)]:
        with pytest.raises(ContractError):factor_regression(net,bad)
    with pytest.raises(ContractError,match='full_rank'):factor_regression(net,f.assign(SMB=f.HML))
    with pytest.raises(ContractError,match='intercept'):ols_hac(net.to_numpy(),np.zeros((len(net),1)),['alpha'])
    ic=pd.Series(np.sin(np.arange(72)*.37)*.4,index=f.index);got=ic_mean_hac(ic);expected=oracle(ic.to_numpy(),np.ones((72,1)))
    for col,value in zip(['mean','hac_se','ci_low','ci_high'],expected):assert got[col]==pytest.approx(value[0],abs=1e-13)
    ic.iloc[12]=np.nan;missing=ic_mean_hac(ic)
    assert missing['undefined_months']==1 and missing['months']==72 and missing['hac_se'] is None


def test_segment_nonunit_nav_initial_drawdown_and_active_same_segment():
    rows=[]
    for name,start,rets in [('MOM5',5.,[-.2,.25,.1]),('EW49',3.,[.01,.02,-.01])]:
        nav=start
        for month,r in zip(pd.period_range('2021-01',periods=3,freq='M'),rets):
            before=nav;nav*=1+r
            rows.append(dict(strategy=name,cost_bps=10,holding_month=month,nav_before=before,nav=nav,net_return=r,RF=.01,gross_traded_fraction=.2,cash_weight=0.,risky_weight=1.))
    s,a,d=summaries(pd.DataFrame(rows));m=s.set_index('strategy').loc['MOM5']
    assert m.cagr==pytest.approx(1.1**4-1) and m.max_drawdown==pytest.approx(.2)
    assert m.sharpe==pytest.approx(np.mean([-.21,.24,.09])/np.std([-.21,.24,.09],ddof=1)*np.sqrt(12))
    assert d.loc[d.strategy=='MOM5','annualized_mean_active_return'].iloc[0]==pytest.approx(12*np.mean([-.21,.23,.11]))


@pytest.mark.parametrize('boundary',['2018-01','2024-01'])
def test_continuation_history_and_no_future_dependency_synthetic(boundary):
    panel,factors=synthetic_panel();labels=list(panel.columns);t=pd.Period(boundary,'M');end=t+2
    full,state,signals=main_path(panel.loc[:end],factors.loc[:end],pd.period_range('2000-01',end,freq='M'),labels)
    early,prior,_=main_path(panel.loc[:t-1],factors.loc[:t-1],pd.period_range('2000-01',t-1,freq='M'),labels)
    restored_panel=pd.concat([wide_history(prior['signal_return_history'],'month'),panel.loc[t:end]])
    restored,rs,_=main_path(restored_panel,factors.loc[restored_panel.index],pd.period_range(t,end,freq='M'),labels,json.loads(json.dumps(prior)))
    for name in ['monthly_results.csv','target_weights.csv','drift_weights.csv','risk_estimates.csv']:
        expected=full[name].loc[full[name].holding_month>=t].reset_index(drop=True)
        pd.testing.assert_frame_equal(expected,restored[name].reset_index(drop=True))
        prefix=full[name].loc[full[name].holding_month<t].reset_index(drop=True)
        pd.testing.assert_frame_equal(prefix,early[name].reset_index(drop=True))
    assert state['states']==rs['states']
    changed=restored_panel.copy();changed.loc[t:]=.8
    _,_,w,risk=targets_and_history(changed,pd.period_range(t,t,freq='M'),labels,prior)
    expected=restored['target_weights.csv'].loc[restored['target_weights.csv'].holding_month==t]
    for name in w:
        np.testing.assert_allclose(w[name].loc[t],expected.loc[expected.strategy==name].set_index('industry').weight)
    altered=json.loads(json.dumps(prior));altered['base_gross_history'][-1]['MOM5']+=.9
    _,_,w2,_=targets_and_history(restored_panel,pd.period_range(t,t,freq='M'),labels,altered)
    assert not np.allclose(w['MOM5_VOL10'],w2['MOM5_VOL10'])
    np.testing.assert_allclose(w['MOM5'],w2['MOM5'])


def test_fixed_sensitivity_six_two_window_and_top10(root):
    panel,f=synthetic_panel('1998-01','2001-12');cal=pd.period_range('2000-01','2001-12',freq='M')
    signals=momentum_window(panel,cal,list(panel.columns),6)
    np.testing.assert_allclose(signals.iloc[0],np.prod(1+panel.loc['1999-07':'1999-11'].to_numpy(),axis=0)-1)
    tables,_,s=main_path(panel,f,cal,list(panel.columns))
    e=run.experiments(root)
    out=sensitivity_paths(panel,f,cal,s,e['sensitivities'],{'synthetic':['2000-01','2001-12']},tables['monthly_results.csv'])
    assert len(out['sensitivity_monthly.csv'])==48
    weights=out['sensitivity_targets.csv']
    assert weights.loc[weights.strategy=='MOM10_12_2'].groupby('holding_month').weight.apply(lambda x:(x>0).sum()).eq(10).all()
    assert weights.groupby(['holding_month','strategy']).weight.sum().eq(1).all()


def config_copy(root,tmp_path):
    shutil.copytree(root/'config',tmp_path/'config');return tmp_path


@pytest.mark.parametrize('end',['2024-01','2025-12'])
def test_day4_denied_before_any_input_read(root,tmp_path,monkeypatch,capsys,end):
    config_copy(root,tmp_path)
    monkeypatch.setattr(run,'verify_day2_snapshot',lambda *_:pytest.fail('snapshot read before gate'))
    monkeypatch.setattr(run,'load_research',lambda *_a,**_k:pytest.fail('research read before gate'))
    assert cli.main(['--root',str(tmp_path),'research','--stage','validation','--end',end])==1
    assert 'OOS_LOCKED' in capsys.readouterr().out


@pytest.mark.parametrize('command',[['oos'],['reproduce','--stage','oos'],['report','--stage','oos']])
def test_oos_all_entries_deny_without_authorization(root,tmp_path,monkeypatch,capsys,command):
    config_copy(root,tmp_path)
    monkeypatch.setattr(run,'read_product',lambda *_:pytest.fail('holdout read'))
    assert cli.main(['--root',str(tmp_path),*command])==1
    assert 'OOS_LOCKED_OR_FAILED' in capsys.readouterr().out


def synthetic_freeze(root,tmp_path,monkeypatch):
    # Every authorization produced by this fixture binds only a temporary synthetic repo.
    for p in freeze.protected_files(root):
        dest=tmp_path/p;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(root/p,dest)
    (tmp_path/'data').mkdir();(tmp_path/'data/manifest.json').write_text('{"SYNTHETIC":true}')
    for cmd in [['git','init','-q'],['git','add','.'],['git','-c','user.name=Synthetic QA','-c','user.email=synthetic@example.invalid','commit','-qm','SYNTHETIC fixture']]:subprocess.run(cmd,cwd=tmp_path,check=True,capture_output=True)
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=tmp_path,text=True).strip()
    monkeypatch.setattr(freeze,'verify_day2_snapshot',lambda *_:{'files':{},'products':{}})
    frozen={'hq_status':'PENDING','holdout_status':'LOCKED','implementation_commit':commit,'protected_hashes':freeze.hash_map(tmp_path,freeze.protected_files(tmp_path)),
            'input_hashes':{'data/manifest.json':sha256((tmp_path/'data/manifest.json').read_bytes())},'output_hashes':{},'evidence_hashes':{},'environment':freeze.environment()}
    path=tmp_path/'reports/research_freeze.json';path.parent.mkdir();path.write_text(json.dumps(frozen))
    auth=tmp_path/'SYNTHETIC_AUTHORIZATION.json';auth.write_text(json.dumps({'authority':'HQ','decision':'AUTHORIZE_DAY5_OOS','range':['2024-01','2025-12'],'freeze_sha256':sha256(path.read_bytes()),'implementation_commit':commit,'experiment_ids':run.experiments(tmp_path)['day5']['experiment_ids'],'fixture':'SYNTHETIC ONLY'}))
    return path,auth


def test_freeze_binding_evidence_only_descendant_and_tamper(root,tmp_path,monkeypatch):
    path,auth=synthetic_freeze(root,tmp_path,monkeypatch)
    freeze.check_authorization(tmp_path,auth)
    (tmp_path/'delivery.txt').write_text('SYNTHETIC evidence only')
    subprocess.run(['git','add','delivery.txt'],cwd=tmp_path,check=True)
    subprocess.run(['git','-c','user.name=QA','-c','user.email=qa@example.invalid','commit','-qm','synthetic delivery'],cwd=tmp_path,check=True)
    freeze.check_authorization(tmp_path,auth)
    for name in ['src/alphalab/metrics.py','config/research.yaml','uv.lock','data/manifest.json','reports/research_freeze.json']:
        target=tmp_path/name;before=target.read_bytes();target.write_bytes(before+b' ')
        with pytest.raises(ContractError):freeze.check_authorization(tmp_path,auth)
        target.write_bytes(before)
    content=json.loads(auth.read_text());content['range']=['2023-01','2025-12'];auth.write_text(json.dumps(content))
    with pytest.raises(ContractError,match='scope'):freeze.check_authorization(tmp_path,auth)
    path.unlink()
    with pytest.raises(ContractError,match='freeze_missing'):freeze.verify_freeze(tmp_path)


def test_default_reproduce_and_report_fail_on_missing_freeze_before_reads(root,tmp_path,monkeypatch,capsys):
    config_copy(root,tmp_path)
    monkeypatch.setattr(run,'run_validation',lambda *_:pytest.fail('calculation before freeze check'))
    for command in ['reproduce','report']:
        assert cli.main(['--root',str(tmp_path),command])==1
        assert 'freeze_missing' in capsys.readouterr().out


def test_synthetic_formal_pipeline_prefix_two_runs_and_shapes(root,tmp_path,monkeypatch):
    from alphalab import research
    for path in freeze.protected_files(root):
        dest=tmp_path/path;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(root/path,dest)
    (tmp_path/'data').mkdir();(tmp_path/'data/manifest.json').write_text('{"SYNTHETIC":true}')
    panel,f=synthetic_panel();labels=yaml.safe_load((tmp_path/'config/research.yaml').read_text())['data']['labels']
    panel.columns=sorted(labels)
    calls=[]
    def load(_root,*,start,end):
        calls.append((start,end));assert end<='2023-12'
        return panel.loc[start:end].reset_index().melt(id_vars='month',var_name='industry',value_name='return'),f.loc[start:end].reset_index()
    for module in [research,run]:
        monkeypatch.setattr(module,'load_research',load)
        monkeypatch.setattr(module,'verify_day2_snapshot',lambda *_:{'files':{},'products':{}})
    p=tmp_path/'config/research.yaml';config=yaml.safe_load(p.read_text());config['phase']='DAY3';p.write_text(yaml.safe_dump(config))
    research.run_backtest(tmp_path)
    prior={p.name:p.read_bytes() for p in (tmp_path/'outputs/day3').iterdir()}
    config['phase']='DAY4';p.write_text(yaml.safe_dump(config))
    run.run_validation(tmp_path)
    first={p.name:p.read_bytes() for p in (tmp_path/'outputs/day4').iterdir() if p.name!='run_execution.jsonl'}
    run.run_validation(tmp_path)
    assert first=={p.name:p.read_bytes() for p in (tmp_path/'outputs/day4').iterdir() if p.name!='run_execution.jsonl'}
    assert prior=={p.name:p.read_bytes() for p in (tmp_path/'outputs/day3').iterdir()}
    for name,n in [('monthly_results.csv',3456),('performance_summary.csv',48),('factor_regressions.csv',120),('factor_inputs_research_validation.csv',288),('sensitivity_monthly.csv',576),('sensitivity_summary.csv',8)]:
        assert len(pd.read_csv(tmp_path/'outputs/day4'/name))==n
    assert calls==[('1998-01','2017-12'),('1998-01','2023-12'),('1998-01','2023-12')]
