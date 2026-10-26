"""REAL integration: official files required; no synthetic replacement or skip."""
import json
import shutil

import pytest

from alphalab.access import load_config, load_research
from alphalab.data import FILES, acquire, build, parse_snapshot_for_qc, read_manifest, sha256, validate_processed, verify_raw
from alphalab.validation import ContractError, validate_tables

pytestmark = pytest.mark.real


def test_official_contract_and_units(root, config):
    frames, metadata = parse_snapshot_for_qc(root, config)
    result = validate_tables(frames["industries"], frames["ff3"], frames["mom"], config)
    assert result["status"] == "PASS"
    assert result["full"]["industries"]["rows"] == 16464
    assert sum(result["partitions"][p]["industries"]["rows"] for p in ["research", "validation", "holdout"]) == 15288
    assert all(v["scale_divisions"] == 1 for v in metadata.values())


def test_cached_rerun_is_identical_and_offline(root, config, monkeypatch):
    from alphalab import data
    before = (root / "data/manifest.json").read_bytes()
    monkeypatch.setattr(data, "_http", lambda *_: pytest.fail("cached run used network"))
    assert acquire(root)["mode"] == "verified_cached_snapshot"
    assert build(root, config)["status"] == "PASS"
    assert (root / "data/manifest.json").read_bytes() == before
    assert validate_processed(root, config)["status"] == "PASS"


def test_rebuild_from_retained_snapshot(root, tmp_path, config):
    (tmp_path / "data/raw").mkdir(parents=True)
    shutil.copyfile(root / "data/manifest.json", tmp_path / "data/manifest.json")
    for name in FILES.values():
        shutil.copyfile(root / "data/raw" / name, tmp_path / "data/raw" / name)
    assert build(tmp_path, config)["status"] == "PASS"
    manifest = read_manifest(root)
    for relative in manifest["products"]:
        assert sha256((tmp_path / relative).read_bytes()) == manifest["products"][relative]["sha256"]


def test_tampered_raw_refused(root, tmp_path):
    (tmp_path / "data/raw").mkdir(parents=True)
    shutil.copyfile(root / "data/manifest.json", tmp_path / "data/manifest.json")
    for name in FILES.values():
        shutil.copyfile(root / "data/raw" / name, tmp_path / "data/raw" / name)
    with (tmp_path / "data/raw" / FILES["mom"]).open("ab") as file:
        file.write(b"tamper")
    with pytest.raises(ContractError, match="raw_hash_mismatch"):
        verify_raw(tmp_path, read_manifest(tmp_path))


def test_real_research_view_is_limited(root):
    industries, factors = load_research(root)
    assert len(industries) == 312 * 49
    assert len(factors) == 312
    assert str(industries["month"].max()) == "2023-12"


def test_manual_restore_pinned_files_without_network(root, tmp_path, monkeypatch):
    from alphalab import data
    (tmp_path / "data").mkdir()
    shutil.copyfile(root / "data/manifest.json", tmp_path / "data/manifest.json")
    monkeypatch.setattr(data, "_http", lambda *_: pytest.fail("manual restoration used network"))
    assert acquire(tmp_path, root / "data/raw")["status"] == "PASS"
    verify_raw(tmp_path, read_manifest(tmp_path))


def test_changed_processed_file_is_refused(root, tmp_path, config):
    (tmp_path / "data/raw").mkdir(parents=True)
    shutil.copyfile(root / "data/manifest.json", tmp_path / "data/manifest.json")
    for name in FILES.values():
        shutil.copyfile(root / "data/raw" / name, tmp_path / "data/raw" / name)
    assert build(tmp_path, config)["status"] == "PASS"
    target = tmp_path / "data/processed/holdout/industry_returns.csv"
    with target.open("ab") as file:
        file.write(b"tamper")
    with pytest.raises(ContractError, match="existing_processed_content_mismatch"):
        build(tmp_path, config)
    with pytest.raises(ContractError, match="processed_hash_mismatch"):
        validate_processed(tmp_path, config)
