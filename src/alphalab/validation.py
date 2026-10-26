"""Structural and completeness QC. Reports contain counts, never return values."""
from __future__ import annotations

import numpy as np
import pandas as pd


class ContractError(ValueError):
    """A safe rule identifier; never include a financial value in its message."""


def require(condition: bool, rule: str) -> None:
    if not condition:
        raise ContractError(rule)


def inspect_table(frame: pd.DataFrame, columns: list[str], start: str, end: str,
                  *, industry: bool = False) -> dict:
    expected = pd.period_range(start, end, freq="M")
    dates_ok = isinstance(frame.index.dtype, pd.PeriodDtype) and frame.index.freqstr == "M"
    numeric = all(pd.api.types.is_numeric_dtype(t) for t in frame.dtypes)
    labels_ok = list(frame.columns) == columns and len(set(frame.columns)) == len(columns)
    rules = {
        "monthly_period_type": int(not dates_ok),
        "stable_labels_and_order": int(not labels_ok),
        "duplicate_months": int(frame.index.duplicated().sum()),
        "unsorted_months": int(not frame.index.is_monotonic_increasing),
        "missing_months": len(expected.difference(frame.index)) if dates_ok else len(expected),
        "unexpected_months": len(frame.index.difference(expected)) if dates_ok else len(frame),
        "numeric_dtype": int(not numeric),
        "missing_values": int(frame.isna().to_numpy().sum()),
        "nonfinite_nonmissing": 0,
        "industry_return_below_minus_100_percent": 0,
    }
    if numeric:
        a = frame.to_numpy(dtype=float)
        rules["nonfinite_nonmissing"] = int((~np.isfinite(a) & ~np.isnan(a)).sum())
        if industry:
            rules["industry_return_below_minus_100_percent"] = int((a < -1).sum())
    passed = not any(rules.values())
    return {"range": [start, end], "months": len(frame),
            "rows": len(frame) * len(columns) if industry else len(frame),
            "status": "PASS" if passed else "FAIL", "rule_failure_counts": rules}


def validate_tables(ind: pd.DataFrame, ff3: pd.DataFrame, mom: pd.DataFrame, config: dict) -> dict:
    labels = config["data"]["labels"]
    require(len(labels) == len(set(labels)) == 49, "config_49_unique_labels")
    tables = {"industries": ind, "ff3": ff3, "mom": mom}
    schemas = {"industries": labels, "ff3": ["Mkt-RF", "SMB", "HML", "RF"], "mom": ["Mom"]}
    start, end = config["data"]["start"], config["data"]["end"]
    full = {name: inspect_table(frame, schemas[name], start, end, industry=name == "industries")
            for name, frame in tables.items()}
    aligned = ind.index.equals(ff3.index) and ind.index.equals(mom.index)
    partitions = {}
    for part, (lo, hi) in config["partitions"].items():
        partitions[part] = {name: inspect_table(frame.loc[(frame.index >= lo) & (frame.index <= hi)],
                                               schemas[name], lo, hi, industry=name == "industries")
                            for name, frame in tables.items()}
    return {"status": "PASS" if aligned and all(x["status"] == "PASS" for x in full.values()) else "FAIL",
            "monthly_alignment": "PASS" if aligned else "FAIL", "full": full, "partitions": partitions}
