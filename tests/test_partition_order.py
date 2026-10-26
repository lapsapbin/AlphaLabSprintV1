"""QA-D1-001: exclusively SYNTHETIC partition files and returns."""
import json
import shutil

import pandas as pd
import pytest
import yaml

from alphalab import access, data
from alphalab.validation import ContractError


@pytest.fixture
def synthetic_store(root, tmp_path, config, synthetic_tables):
    (tmp_path / "config").mkdir()
    shutil.copyfile(root / "config/research.yaml", tmp_path / "config/research.yaml")
    ind, ff3, mom = synthetic_tables
    manifest = {"schema_version": 1, "files": {}, "fixture": "SYNTHETIC", "products": {}}
    for partition, (lo, hi) in config["partitions"].items():
        long = ind.loc[lo:hi].reset_index().melt(id_vars="month", var_name="industry", value_name="return")
        long = long.sort_values(["month", "industry"]).reset_index(drop=True)
        factors = ff3.join(mom).loc[lo:hi].reset_index()
        for name, table in [("industry_returns", long), ("factors", factors)]:
            relative = f"data/processed/{partition}/{name}.csv"
            payload = data.csv_bytes(table)
            target = tmp_path / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
            manifest["products"][relative] = {"sha256": data.sha256(payload)}
    data.write_json(tmp_path / "data/manifest.json", manifest)
    return tmp_path


def test_yaml_reordering_keeps_research_identical_and_qc_correct(synthetic_store, monkeypatch):
    root = synthetic_store
    opened = []
    original = access.read_product
    def permitted_read(root, partition, name, manifest):
        assert partition != "holdout", "Research must not open holdout"
        opened.append(partition)
        return original(root, partition, name, manifest)
    monkeypatch.setattr(access, "read_product", permitted_read)
    before = access.load_research(root)
    before_qc = data.validate_processed(root, access.load_config(root))
    path = root / "config/research.yaml"
    config = yaml.safe_load(path.read_text())
    path.write_text(yaml.safe_dump(config, sort_keys=True))
    assert list(access.load_config(root)["partitions"]) != list(access.PARTITIONS)
    after = access.load_research(root)
    for old, new in zip(before, after, strict=True):
        pd.testing.assert_frame_equal(old, new)
        assert new["month"].is_monotonic_increasing
        assert new.index.equals(pd.RangeIndex(len(new)))
    assert opened == ["warmup", "warmup", "research", "research", "validation", "validation"] * 2
    assert data.validate_processed(root, access.load_config(root)) == before_qc
    assert before_qc["status"] == "PASS"


@pytest.mark.parametrize("name,mutation", [
    ("industry_returns", "reverse"), ("industry_returns", "duplicate"),
    ("factors", "reverse"), ("factors", "duplicate"),
])
def test_qc_does_not_hide_corrupt_file_order(synthetic_store, name, mutation):
    root = synthetic_store
    relative = f"data/processed/research/{name}.csv"
    frame = pd.read_csv(root / relative)
    frame = frame.iloc[::-1] if mutation == "reverse" else pd.concat([frame.iloc[[0]], frame], ignore_index=True)
    payload = data.csv_bytes(frame)
    (root / relative).write_bytes(payload)
    manifest = data.read_manifest(root)
    manifest["products"][relative]["sha256"] = data.sha256(payload)
    data.write_json(root / "data/manifest.json", manifest)
    with pytest.raises(ContractError, match="unsorted|duplicate"):
        data.validate_processed(root, access.load_config(root))
