"""SYNTHETIC orchestration/boundary checks; no validation/OOS observations."""
import json
import shutil

import pandas as pd
import pytest
import yaml

from alphalab import cli, research


def config_copy(root,tmp_path):
    (tmp_path/'config').mkdir()
    config=yaml.safe_load((root/'config/research.yaml').read_text())
    config['phase']='DAY3'
    (tmp_path/'config/research.yaml').write_text(yaml.safe_dump(config))


@pytest.mark.parametrize('end',['2018-01','2023-12','2024-01','2025-12'])
def test_day3_boundary_denies_before_input_or_research(root,tmp_path,monkeypatch,capsys,end):
    config_copy(root,tmp_path)
    monkeypatch.setattr(research,'verify_day2_snapshot',lambda *_: pytest.fail('Read before gate'))
    monkeypatch.setattr(research,'load_research',lambda *_a,**_k: pytest.fail('Research before gate'))
    assert cli.main(['--root',str(tmp_path),'research','--stage','backtest','--end',end])==1
    assert 'DAY3_RESEARCH_LOCKED_AFTER_2017_12' in capsys.readouterr().out
    assert not (tmp_path/'outputs').exists()


def test_day3_pipeline_fixed_scope_costs_repeats_and_preserves_day2(root,tmp_path,monkeypatch,synthetic_tables):
    config_copy(root,tmp_path)
    shutil.copyfile(root/'uv.lock',tmp_path/'uv.lock')
    shutil.copytree(root/'src',tmp_path/'src',ignore=shutil.ignore_patterns('__pycache__'))
    (tmp_path/'outputs/day2').mkdir(parents=True)
    sentinel=tmp_path/'outputs/day2/run_manifest.json';sentinel.write_text('{"SYNTHETIC":"preserve"}')
    ind,ff3,mom=synthetic_tables
    calls=[]
    def load(_root,*,start,end):
        calls.append((start,end))
        assert start=='1998-01' and end=='2017-12'
        return ind.loc[start:end].reset_index().melt(id_vars='month',var_name='industry',value_name='return'),ff3.join(mom).loc[start:end].reset_index()
    monkeypatch.setattr(research,'load_research',load)
    monkeypatch.setattr(research,'verify_day2_snapshot',lambda *_:{'files':{},'products':{}})
    for iteration in range(2):
        result=research.run_backtest(tmp_path)
        assert result['monthly_rows']==2592 and result['scenarios']==12
        current={p.name:p.read_bytes() for p in (tmp_path/'outputs/day3').iterdir() if p.name!='run_execution.jsonl'}
        if iteration==0: first=current
        else: assert current==first
    assert calls==[('1998-01','2017-12')]*2
    assert sentinel.read_text()=='{"SYNTHETIC":"preserve"}'
    monthly=pd.read_csv(tmp_path/'outputs/day3/monthly_results.csv')
    assert set(monthly.cost_bps)=={0,10,20} and monthly.holding_month.min()=='2000-01' and monthly.holding_month.max()=='2017-12'
    assert monthly.groupby(['strategy','cost_bps']).size().eq(216).all()
    for _, group in monthly.groupby('strategy'):
        wide=group.pivot(index='holding_month',columns='cost_bps',values='nav')
        assert (wide[0]>=wide[10]).all() and (wide[10]>=wide[20]).all()
        assert group.groupby('holding_month').risk_scale.nunique().eq(1).all()
    manifest=json.loads(current['run_manifest.json'])
    assert manifest['base_warmup_range']==['1999-01','1999-12']
    assert manifest['holdout_status']=='LOCKED' and manifest['validation_performance_evaluated'] is False
    state=json.loads(current['terminal_state.json'])
    assert len(state['states'])==12 and len(state['signal_return_history'])==len(state['base_gross_history'])==12
