"""Golden test: the generalized engine must reproduce 26p17 Jeju 2020 figures.

Locked from the validated source pipeline (compute_rio_single.py) on the P09
spending map: in-region policy-expenditure production = 350.3085 백만원.
"""
from pathlib import Path

import pytest

from rio_mcp.engine.coefficients import load_coefficients
from rio_mcp.engine.effects import policy_expenditure_effects, compute_effects, summarize

FIX = Path(__file__).parent / "fixtures"
COEF = FIX / "induce_coefficients_jeju_medium.csv"
P09 = FIX / "spending_industry_mapping_p09.csv"


@pytest.fixture
def coef():
    return load_coefficients(COEF)


def test_legacy_columns_load(coef):
    # Jeju CSV uses _jeju/_outside; loader must expose generic names.
    assert "multiplier_production_in_region" in coef.columns
    assert len(coef) == 83


def test_p09_policy_expenditure_golden(coef):
    df = policy_expenditure_effects(coef, P09)
    s = summarize(df)
    assert round(s["production_in_region_mw"], 4) == 350.3085
    assert round(s["production_out_region_mw"], 4) == 176.7545
    assert round(s["value_added_in_region_mw"], 4) == 170.7741
    assert round(s["employment_in_region_persons"], 4) == 2.3885


def test_compute_effects_is_multiplier_application(coef):
    # 1000 백만원 into sector 80 must equal 1000 × its in-region production coef.
    import pandas as pd
    df = compute_effects(pd.DataFrame([{"sector_code": "80", "amount_mw": 1000.0}]), coef)
    expected = 1000.0 * coef.loc["80", "multiplier_production_in_region"]
    assert abs(df["production_in_region_mw"].iloc[0] - expected) < 1e-9
