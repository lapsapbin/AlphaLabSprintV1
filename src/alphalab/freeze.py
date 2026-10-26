"""Public audit binding, not authentication/security isolation. No authorization issuer."""
from __future__ import annotations
import importlib.metadata
import json
import platform
import subprocess
from pathlib import Path
from .access import HoldoutLocked, load_config
from .data import sha256, utc_now, write_json
from .research import _git, verify_day2_snapshot
from .validation import require


def protected_files(root):
    files=['AGENTS.md','PROJECT_SPEC.md','SIX_DAY_PLAN.md','.python-version','pyproject.toml','uv.lock']
    files += [str(p.relative_to(root)) for folder in ['src','tests','config'] for p in (root/folder).rglob('*')
              if p.is_file() and '__pycache__' not in p.parts and p.suffix in {'.py','.csv','.yaml','.json'}]
    return sorted(files)


def environment():
    return {'python':platform.python_version(),'platform':platform.platform(),
            'dependencies':{p:importlib.metadata.version(p) for p in ['numpy','pandas','PyYAML','pytest','statsmodels','scipy']}}


def hash_map(root, files):
    return {p:sha256((root/p).read_bytes()) for p in sorted(files)}


def input_hashes(root, snapshot):
    return {'data/manifest.json':sha256((root/'data/manifest.json').read_bytes()),
            **{'data/raw/'+v['filename']:v['sha256'] for v in snapshot['files'].values()},
            **{p:v['sha256'] for p,v in snapshot['products'].items()}}


def verify_freeze(root: Path, external_sha: str | None = None):
    path=root/'reports/research_freeze.json'
    require(path.is_file(),'freeze_missing')
    payload=path.read_bytes()
    if external_sha is not None: require(sha256(payload)==external_sha,'freeze_external_sha_mismatch')
    frozen=json.loads(payload)
    require(frozen['hq_status']=='PENDING' and frozen['holdout_status']=='LOCKED','freeze_candidate_status')
    require(set(frozen['protected_hashes'])==set(protected_files(root)),'freeze_inventory_changed')
    require(hash_map(root,frozen['protected_hashes'])==frozen['protected_hashes'],'freeze_protected_hash_mismatch')
    commit=frozen['implementation_commit']
    require(isinstance(commit,str) and len(commit)==40,'freeze_implementation_commit')
    require(_git(root,'merge-base','--is-ancestor',commit,'HEAD') is not None,'freeze_implementation_ancestry')
    for path,digest in frozen['protected_hashes'].items():
        result=subprocess.run(['git','show',f'{commit}:{path}'],cwd=root,capture_output=True)
        require(result.returncode==0 and sha256(result.stdout)==digest,'freeze_commit_file_mismatch')
    snapshot=verify_day2_snapshot(root)
    require(input_hashes(root,snapshot)==frozen['input_hashes'],'freeze_input_hash_mismatch')
    for mapping in ['output_hashes','evidence_hashes']:
        require(hash_map(root,frozen[mapping])==frozen[mapping],'freeze_'+mapping+'_mismatch')
    require(environment()==frozen['environment'],'freeze_environment_changed')
    return frozen


def check_authorization(root: Path, authorization: Path | None):
    # Do not even read the data manifest before the external authorization checks.
    if authorization is None or not authorization.is_file(): raise HoldoutLocked('OOS_LOCKED: HQ_DAY5_AUTHORIZATION_REQUIRED')
    a=json.loads(authorization.read_text())
    require(a.get('authority')=='HQ' and a.get('decision')=='AUTHORIZE_DAY5_OOS' and a.get('range')==['2024-01','2025-12'],'oos_authorization_scope')
    require(isinstance(a.get('freeze_sha256'),str) and len(a['freeze_sha256'])==64,'oos_authorization_freeze_sha')
    frozen=verify_freeze(root,a['freeze_sha256'])
    experiments=json.loads((root/'config/experiments.json').read_text())
    require(a.get('implementation_commit')==frozen['implementation_commit'],'oos_authorization_commit')
    require(a.get('experiment_ids')==experiments['day5']['experiment_ids'],'oos_authorization_experiments')
    return frozen


def create_freeze(root: Path, evidence: list[str], unresolved: list[str]):
    """Called only after formal runs/QA; never creates an HQ authorization."""
    require(not (root/'reports/research_freeze.json').exists(),'freeze_already_exists_preserve_history')
    load_config(root)
    manifest=json.loads((root/'outputs/day4/run_manifest.json').read_text())
    protected=hash_map(root,protected_files(root))
    require(protected==manifest['protected_hashes'],'freeze_code_changed_since_run')
    snapshot=verify_day2_snapshot(root)
    outputs={f'outputs/day4/{p}':v['sha256'] for p,v in manifest['outputs'].items()}
    outputs['outputs/day4/run_manifest.json']=sha256((root/'outputs/day4/run_manifest.json').read_bytes())
    f={'generated_at_utc':utc_now(),'hq_status':'PENDING','holdout_status':'LOCKED',
       'implementation_commit':manifest['implementation_commit'],'protected_hashes':protected,
       'input_hashes':input_hashes(root,snapshot),'environment':environment(),'output_hashes':outputs,
       'terminal_state_sha256':outputs['outputs/day4/terminal_state.json'],
       'evidence_hashes':hash_map(root,evidence),'unresolved_issues':unresolved,
       'worktree_dirty_at_freeze':bool(_git(root,'status','--porcelain=v1'))}
    write_json(root/'reports/research_freeze.json',f)
    return sha256((root/'reports/research_freeze.json').read_bytes())
