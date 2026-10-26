"""SYNTHETIC end-to-end boundary/reproduction checks; no real result evidence."""
import json
import shutil

import pandas as pd
import pytest
import yaml

from alphalab import cli, research
from alphalab.validation import ContractError


def copy_config(root, tmp_path):
    (tmp_path / "config").mkdir()
    config = yaml.safe_load((root / "config/research.yaml").read_text())
    config["phase"] = "DAY2"
    (tmp_path / "config/research.yaml").write_text(yaml.safe_dump(config))


@pytest.mark.parametrize("end", ["2018-01", "2023-12", "2024-01", "2025-12"])
def test_research_command_rejects_later_dates_before_reading(root, tmp_path, monkeypatch, capsys, end):
    copy_config(root, tmp_path)
    monkeypatch.setattr(research, "verify_day2_snapshot", lambda *_: pytest.fail("input read before Day 2 range check"))
    monkeypatch.setattr(research, "load_research", lambda *_a, **_k: pytest.fail("research load before range check"))
    assert cli.main(["--root", str(tmp_path), "research", "--stage", "signals", "--end", end]) == 1
    assert "DAY2_RESEARCH_LOCKED_AFTER_2017_12" in capsys.readouterr().out
    assert not (tmp_path / "outputs").exists()


def test_pinned_manifest_change_stops_before_data_reads(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data/manifest.json").write_text('{"fixture":"SYNTHETIC_CHANGED"}')
    with pytest.raises(ContractError, match="accepted_day1_manifest_changed"):
        research.verify_day2_snapshot(tmp_path)


def test_pipeline_loads_only_authorized_history_and_repeats(root, tmp_path, monkeypatch, synthetic_tables):
    copy_config(root, tmp_path)
    shutil.copyfile(root / "uv.lock", tmp_path / "uv.lock")
    shutil.copytree(root / "src", tmp_path / "src", ignore=shutil.ignore_patterns("__pycache__"))
    ind, ff3, mom = synthetic_tables
    calls = []
    def load(_root, *, start, end):
        calls.append((start, end))
        assert start == "1998-01" and end == "2017-12"
        permitted = ind.loc[start:end].reset_index().melt(id_vars="month", var_name="industry", value_name="return")
        return permitted, ff3.join(mom).loc[start:end].reset_index()
    monkeypatch.setattr(research, "load_research", load)
    monkeypatch.setattr(research, "verify_day2_snapshot", lambda *_: {"files": {}, "products": {}, "fixture": "SYNTHETIC"})
    for _ in range(2):
        result = research.run_signals(tmp_path)
        assert result["signal_rows"] == 11172 and result["weight_rows"] == 22344
        assert result["research_summary"]["months"] == 216
        assert result["research_summary"]["rank_ic"]["undefined_months"] == 216
        assert result["research_summary"]["rank_ic"]["mean"] is None
        current = {p.name: p.read_bytes() for p in (tmp_path / "outputs/day2").iterdir() if p.name != "run_execution.jsonl"}
        if _ == 0:
            first = current
        else:
            assert current == first
    assert calls == [("1998-01", "2017-12")] * 2
    manifest = json.loads((tmp_path / "outputs/day2/run_manifest.json").read_text())
    assert manifest["outputs"]["momentum_12_2.csv"]["range"] == ["1999-01", "2017-12"]
    assert manifest["outputs"]["rank_ic_research.csv"]["rows"] == 216
