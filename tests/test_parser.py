"""SYNTHETIC parser and hostile-input tests; never feasibility evidence."""
import io
import zipfile

import pandas as pd
import pytest

from alphalab.data import MEMBERS, csv_bytes, parse_monthly, zip_text
from alphalab.validation import ContractError


def test_select_vw_monthly_sentinels_and_single_scale(root):
    frame, meta = parse_monthly((root / "tests/fixtures/synthetic_multi_table.csv").read_text(), "industries")
    assert list(frame.columns) == ["Alpha", "Beta", "Gamma", "Delta"]
    assert frame.loc["1998-01", "Alpha"] == 0.015
    assert frame.loc["1998-01", ["Beta", "Gamma"]].isna().all()
    assert frame.loc["1998-01", "Delta"] == -0.425
    assert frame.loc["1998-02", "Delta"] == 1.25  # real extremes are not clipped
    reread = pd.read_csv(io.BytesIO(csv_bytes(frame.reset_index())))
    assert reread.loc[0, "Alpha"] == 0.015
    assert meta["scale_divisions"] == 1
    assert not any(line.startswith(("199801,", "199802,", "1998,")) for line in meta["description"])


@pytest.mark.parametrize("kind,header", [("ff3", "Mkt-RF,SMB,HML,RF"), ("mom", "Mom")])
def test_factor_monthly_not_annual(kind, header):
    cells = ",".join(["1.50"] * len(header.split(",")))
    body = f"SYNTHETIC\n,{header}\n199801,{cells}\n199802,{cells}\n\nAnnual Factors\n,{header}\n1998,{cells}\n"
    frame, _ = parse_monthly(body, kind)
    assert len(frame) == 2
    assert (frame.to_numpy() == 0.015).all()


@pytest.mark.parametrize("body,rule", [
    (",Mom\n199801,1.5\n199801,2\n", "duplicate_months"),
    (",Mom\n199802,1.5\n199801,2\n", "unsorted_months"),
    (",Mom\n199813,1.5\n", "invalid_month_or_numeric_encoding"),
    (",Mom\n199801,1.5\n199802,SECRET_BAD_VALUE\n", "invalid_month_or_numeric_encoding"),
    (",Mom\n199801,1.5\n,MomChanged\n199802,2\n", "unexpected_row_in_monthly_block"),
    (",Mom\n199801,1.5\n\n,Mom\n199802,2\n", "exactly_one_matching_monthly_block"),
])
def test_reject_bad_blocks_without_echoing_values(body, rule):
    with pytest.raises(ContractError, match=rule):
        parse_monthly("SYNTHETIC\n" + body, "mom")


@pytest.mark.parametrize("member", ["wrong.csv", "../F-F_Momentum_Factor.csv"])
def test_zip_member_rejected(member):
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr(member, "SYNTHETIC\n,Mom\n199801,1.5\n")
    with pytest.raises(ContractError, match="unexpected_csv_member"):
        zip_text(payload.getvalue(), "mom")


def test_html_is_not_csv():
    with pytest.raises(ContractError, match="expected_zip_not_html"):
        zip_text(b"<html>upstream error</html>", "mom")
