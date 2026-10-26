"""SYNTHETIC access tests plus no-read assertions for the locked partition."""
import json
import shutil

import pandas as pd
import pytest
import yaml

from alphalab import access, cli
from alphalab.validation import ContractError


def isolated_config(root, tmp_path):
    (tmp_path / "config").mkdir()
    shutil.copyfile(root / "config/research.yaml", tmp_path / "config/research.yaml")
    return tmp_path


@pytest.mark.parametrize("start,end", [("2024-01", "2024-01"), ("2025-01", "2025-12"), ("1998-01", "2025-12")])
def test_deny_before_any_data_read(root, tmp_path, monkeypatch, start, end):
    isolated_config(root, tmp_path)
    monkeypatch.setattr(access, "read_manifest", lambda *_: pytest.fail("data read before permission check"))
    with pytest.raises(access.HoldoutLocked):
        access.load_research(tmp_path, start, end)
    event = json.loads((tmp_path / "reports/oos_access.jsonl").read_text())
    assert event["status"] == "DENIED"


def test_default_view_never_opens_holdout(root, tmp_path, monkeypatch):
    isolated_config(root, tmp_path)
    opened = []
    monkeypatch.setattr(access, "read_manifest", lambda *_: {})
    def read(_root, partition, name, _manifest):
        assert partition != "holdout"
        opened.append(partition)
        lo, hi = access.PARTITIONS[partition]
        return pd.DataFrame({"month": pd.period_range(lo, hi, freq="M"), "industry": "SYNTHETIC", "SYNTHETIC_VALUE": 0.015})
    monkeypatch.setattr(access, "read_product", read)
    ind, factors = access.load_research(tmp_path)
    assert str(ind["month"].max()) == str(factors["month"].max()) == "2023-12"
    assert set(opened) == {"warmup", "research", "validation"}


def test_config_cannot_unlock_day1(root, tmp_path):
    isolated_config(root, tmp_path)
    path = tmp_path / "config/research.yaml"
    value = yaml.safe_load(path.read_text())
    value["access"]["holdout_status"] = "UNLOCKED"
    path.write_text(yaml.safe_dump(value))
    with pytest.raises(ContractError, match="day1_locked_policy_required"):
        access.load_config(tmp_path)


def test_cli_qc_never_echoes_upstream_values(root, tmp_path, monkeypatch, capsys):
    isolated_config(root, tmp_path)
    def broken(*_):
        raise ValueError("SYNTHETIC secret locked return 0.87654321")
    monkeypatch.setattr(cli, "validate_processed", broken)
    assert cli.main(["--root", str(tmp_path), "validate"]) == 1
    output = capsys.readouterr().out + (tmp_path / "reports/day1_qc.json").read_text()
    assert "0.87654321" not in output and "secret" not in output


def test_cli_denied(root, tmp_path, capsys):
    isolated_config(root, tmp_path)
    assert cli.main(["--root", str(tmp_path), "preview", "--end", "2025-12"]) == 1
    assert "OOS_LOCKED" in capsys.readouterr().out


@pytest.mark.parametrize("phase,allowed", [("DAY1", True), ("DAY2", True), ("DAY3", True), ("DAY4", True), ("DAY5", False), ("ANY", False)])
def test_explicit_phase_allowlist(root, tmp_path, phase, allowed):
    isolated_config(root, tmp_path)
    path = tmp_path / "config/research.yaml"
    value = yaml.safe_load(path.read_text())
    value["phase"] = phase
    path.write_text(yaml.safe_dump(value))
    if allowed:
        assert access.load_config(tmp_path)["phase"] == phase
    else:
        with pytest.raises(ContractError, match="day1_through_day4_phase_required"):
            access.load_config(tmp_path)
