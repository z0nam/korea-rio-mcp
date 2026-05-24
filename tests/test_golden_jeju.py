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


# --- multiregional 2020 중분류 (all 17 regions) --------------------------- #
from rio_mcp.store import cache  # noqa: E402


def test_bundled_jeju_reproduces_golden():
    # The bundled 제주 table (built from the multiregional KOSIS workbook) must
    # reproduce the same P09 figure as the legacy fixture.
    jeju = load_coefficients(cache.resolve_path("제주", 2020, "중분류(83부문)"))
    s = summarize(policy_expenditure_effects(jeju, P09))
    assert round(s["production_in_region_mw"], 4) == 350.3085
    assert round(s["employment_in_region_persons"], 4) == 2.3885


def test_other_region_full_three_indicators():
    # 강원: all three indicators available from the regional 2020 중분류 source
    # (production + value-added + regional 취업유발계수).
    gw = load_coefficients(cache.resolve_path("강원", 2020, "중분류(83부문)"))
    s = summarize(policy_expenditure_effects(gw, P09))
    assert s["production_in_region_mw"] > 0
    assert s["value_added_in_region_mw"] > 0
    assert s["employment_in_region_persons"] > 0


def test_jeju_employment_from_regional_table_matches_legacy():
    # The bundled 제주 employment now comes from the regional 취업유발계수표;
    # it must match the legacy fixture's employment figure.
    jeju = load_coefficients(cache.resolve_path("제주", 2020, "중분류(83부문)"))
    s = summarize(policy_expenditure_effects(jeju, P09))
    assert round(s["employment_in_region_persons"], 4) == 2.3885


def test_seventeen_regions_available():
    files = {c["file"] for c in cache.list_available()}
    for region in ["서울", "경기", "부산", "강원", "제주", "세종"]:
        assert f"induce_coef_{region}_2020_중분류.csv" in files


def test_report_handles_na_employment():
    from rio_mcp.docs.report import render_report
    results = {"production_in_region_mw": 100.0, "production_out_region_mw": 50.0,
               "value_added_in_region_mw": 40.0, "value_added_out_region_mw": 20.0,
               "employment_in_region_persons": None, "employment_out_region_persons": None}
    md = render_report(results, preset="final")
    assert "N/A" in md
