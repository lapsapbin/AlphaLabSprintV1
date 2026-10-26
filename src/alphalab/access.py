"""Auditable process controls, not a security sandbox. No Day 5 unlock action."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import yaml

from .data import read_manifest, read_product, utc_now
from .validation import ContractError, require

PARTITIONS = {
    "warmup": ["1998-01", "1999-12"], "research": ["2000-01", "2017-12"],
    "validation": ["2018-01", "2023-12"], "holdout": ["2024-01", "2025-12"],
}


class HoldoutLocked(PermissionError):
    pass


def load_config(root: Path) -> dict:
    config = yaml.safe_load((root / "config/research.yaml").read_text())
    # Explicit stage allowlist; later phases require their own HQ authorization.
    require(config["phase"] in {"DAY1", "DAY2", "DAY3", "DAY4"}, "day1_through_day4_phase_required")
    require(config["access"] == {
        "holdout_status": "LOCKED", "research_max_month": "2023-12",
        "holdout_start": "2024-01", "holdout_end": "2025-12",
        "full_file_channel": "structural_qc_only",
    }, "day1_locked_policy_required")
    require(config["partitions"] == PARTITIONS, "frozen_partitions_required")
    require(config["data"]["start"] == "1998-01" and config["data"]["end"] == "2025-12", "frozen_coverage_required")
    return config


def log_access(root: Path, channel: str, status: str, start: str = "2024-01", end: str = "2025-12") -> None:
    require(channel in {"structural_qc", "research_denied", "authorized_oos"}, "access_channel")
    require(status in {"BEGIN", "PASS", "FAIL", "DENIED"}, "access_status")
    path = root / "reports/oos_access.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"timestamp_utc": utc_now(), "channel": channel,
                                 "status": status, "range": [start, end]}, sort_keys=True) + "\n")


def load_research(root: Path, start: str = "1998-01", end: str = "2023-12") -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return decimal data only from permitted partitions; check before file reads."""
    config = load_config(root)
    try:
        lo, hi = pd.Period(start, freq="M"), pd.Period(end, freq="M")
    except ValueError:
        raise ContractError("invalid_requested_month") from None
    if hi > pd.Period(config["access"]["research_max_month"], freq="M") or lo >= pd.Period("2024-01", freq="M"):
        log_access(root, "research_denied", "DENIED", str(lo), str(hi))
        raise HoldoutLocked("OOS_LOCKED: research/preview cannot access dates after 2023-12")
    require(pd.Period("1998-01", freq="M") <= lo <= hi, "requested_range_outside_contract")
    manifest = read_manifest(root)
    industry_parts, factor_parts = [], []
    for partition, (part_start, part_end) in sorted(config["partitions"].items(), key=lambda item: item[1][0]):
        if partition == "holdout" or pd.Period(part_end, freq="M") < lo or pd.Period(part_start, freq="M") > hi:
            continue
        for name, destination in [("industry_returns", industry_parts), ("factors", factor_parts)]:
            table = read_product(root, partition, name, manifest)
            # Physical partition boundary is checked before any research calculations.
            require(table["month"].between(pd.Period(part_start, "M"), pd.Period(part_end, "M")).all(), "partition_date_boundary")
            destination.append(table.loc[table["month"].between(lo, hi)].copy())
    industries = pd.concat(industry_parts, ignore_index=True).sort_values(["month", "industry"], kind="stable").reset_index(drop=True)
    factors = pd.concat(factor_parts, ignore_index=True).sort_values("month", kind="stable").reset_index(drop=True)
    return industries, factors
