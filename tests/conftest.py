"""All generated financial values in this file are SYNTHETIC unit fixtures."""
from pathlib import Path

import pandas as pd
import pytest

from alphalab.access import load_config


@pytest.fixture
def root():
    return Path(__file__).resolve().parents[1]


@pytest.fixture
def config(root):
    return load_config(root)


@pytest.fixture
def synthetic_tables(config):
    dates = pd.period_range("1998-01", "2025-12", freq="M", name="month")
    return (
        pd.DataFrame(0.015, index=dates, columns=config["data"]["labels"]),
        pd.DataFrame(0.002, index=dates, columns=["Mkt-RF", "SMB", "HML", "RF"]),
        pd.DataFrame(-0.005, index=dates, columns=["Mom"]),
    )
