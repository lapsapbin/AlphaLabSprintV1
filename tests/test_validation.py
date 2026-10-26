"""SYNTHETIC contract rejection tests."""
import json

import numpy as np
import pytest

from alphalab.validation import validate_tables


def test_complete_synthetic_contract(synthetic_tables, config):
    assert validate_tables(*synthetic_tables, config)["status"] == "PASS"


@pytest.mark.parametrize("mutation,rule", [
    ("duplicate", "duplicate_months"), ("missing", "missing_months"),
    ("labels", "stable_labels_and_order"), ("unsorted", "unsorted_months"),
    ("nan", "missing_values"), ("inf", "nonfinite_nonmissing"),
    ("loss", "industry_return_below_minus_100_percent"), ("string", "numeric_dtype"),
])
def test_reject_contract_errors(synthetic_tables, config, mutation, rule):
    import pandas as pd
    ind, ff3, mom = synthetic_tables
    if mutation == "duplicate": ind = pd.concat([ind, ind.iloc[[-1]]])
    if mutation == "missing": ind = ind.drop(ind.index[-1])
    if mutation == "labels": ind = ind.rename(columns={ind.columns[0]: "ChangedLabel"})
    if mutation == "unsorted": ind = ind.iloc[::-1]
    if mutation == "nan": ind.iloc[-1, 0] = np.nan
    if mutation == "inf": ind.iloc[-1, 0] = np.inf
    if mutation == "loss": ind.iloc[-1, 0] = -1.23456789
    if mutation == "string": ind[ind.columns[0]] = "SYNTHETIC_BAD_NUMBER"
    report = validate_tables(ind, ff3, mom, config)
    assert report["status"] == "FAIL"
    assert report["full"]["industries"]["rule_failure_counts"][rule] > 0
    encoded = json.dumps(report)
    assert "-1.23456789" not in encoded and "SYNTHETIC_BAD_NUMBER" not in encoded


def test_factor_alignment(synthetic_tables, config):
    ind, ff3, mom = synthetic_tables
    report = validate_tables(ind, ff3, mom.iloc[:-1], config)
    assert report["status"] == "FAIL"
    assert report["monthly_alignment"] == "FAIL"


def test_oos_qc_has_only_counts_dates_and_status(synthetic_tables, config):
    ind, ff3, mom = synthetic_tables
    ind.loc["2024-01", :] = 0.87654321
    ff3.loc["2025-12", :] = -0.65432109
    mom.loc["2024-05", :] = -0.43210987
    encoded = json.dumps(validate_tables(ind, ff3, mom, config))
    assert all(token not in encoded for token in ["0.87654321", "-0.65432109", "-0.43210987"])
    assert all(token not in encoded for token in ["mean", "quantile", "correlation", "max_return"])
