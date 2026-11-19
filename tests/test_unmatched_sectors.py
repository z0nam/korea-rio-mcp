"""Issue #7: sector codes missing from the coefficient table must be surfaced.

Intended zeros (null sector_code — a stay profile's air/sea items — or a zero
amount) are not warnings; a non-zero amount on an unknown code is.
"""
import pandas as pd
import pytest

from rio_mcp import server
from rio_mcp.engine.coefficients import load_coefficients
from rio_mcp.engine.effects import (
    UnmatchedSectorError,
    compute_effects,
    find_unmatched_sectors,
    stay_spending_effects_standard,
)
from rio_mcp.store import cache

JEJU = ("제주", 2020, "중분류(83부문)")


def _unmatched_warnings(res):
    # #17 added input-check warnings (default vendor share, unit); count only #7's.
    return [w for w in res["warnings"] if "계수표에 없어" in w]


@pytest.fixture(scope="module")
def coef():
    return load_coefficients(cache.resolve_path(*JEJU))


def test_find_unmatched_distinguishes_intended_zero(coef):
    df = pd.DataFrame([
        {"sector_code": "80", "sector_name": "스포츠", "amount_mw": 100.0},
        {"sector_code": "99", "sector_name": "오타", "amount_mw": 50.0},
        {"sector_code": None, "sector_name": "(air/sea)", "amount_mw": 0.0},
        {"sector_code": "98", "sector_name": "금액0", "amount_mw": 0.0},
        {"sector_code": 8.0, "sector_name": "float코드", "amount_mw": 10.0},
    ])
    u = find_unmatched_sectors(df, coef)
    assert [x["sector_code"] for x in u] == ["99"]
    assert u[0]["amount_mw"] == 50.0


def test_stay_profile_air_sea_not_reported(coef):
    df = stay_spending_effects_standard(coef, 10_000)
    assert df["sector_code"].isna().any()  # air/sea routed out of region
    assert find_unmatched_sectors(df, coef) == []


def test_compute_effects_strict_raises(coef):
    df = pd.DataFrame([{"sector_code": "99", "amount_mw": 50.0}])
    assert compute_effects(df, coef)["production_in_region_mw"].iloc[0] == 0.0
    with pytest.raises(UnmatchedSectorError) as ei:
        compute_effects(df, coef, strict=True)
    assert ei.value.unmatched[0]["sector_code"] == "99"


def test_tool_compute_effects_reports_unmatched():
    res = server.rio_compute_effects(*JEJU[:2], spending=[
        {"sector_code": "80", "amount_mw": 100.0},
        {"sector_code": "99", "amount_mw": 50.0, "vendor_in_region_share": 0.5},
    ])
    assert res["unmatched_sectors"] == [
        {"sector_code": "99", "sector_name": "", "amount_mw": 25.0}]
    uw = _unmatched_warnings(res)
    assert len(uw) == 1 and "99" in uw[0]
    assert res["totals"]["production_in_region_mw"] > 0


def test_tool_compute_effects_clean_has_empty_lists():
    res = server.rio_compute_effects(*JEJU[:2], spending=[
        {"sector_code": "80", "amount_mw": 1.0, "vendor_in_region_share": 1.0}])
    assert res["unmatched_sectors"] == [] and res["warnings"] == []


def test_tool_compute_effects_strict():
    with pytest.raises(UnmatchedSectorError):
        server.rio_compute_effects(*JEJU[:2], spending=[{"sector_code": "99", "amount_mw": 1.0}],
                                   strict=True)


def test_tool_compute_event_tags_channel():
    res = server.rio_compute_event(*JEJU[:2], event_spec={
        "policy_spending": [{"sector_code": "77", "amount_mw": 10.0},
                            {"sector_code": "999", "amount_mw": 5.0}],
        "n_outsider": 1000,
        "event_site_sector": "00",
    })
    by_channel = {(u["channel"], u["sector_code"]) for u in res["unmatched_sectors"]}
    assert by_channel == {("policy_expenditure", "999"), ("participant", "00")}
    assert len(_unmatched_warnings(res)) == 2


def test_tool_compute_event_default_stay_is_clean():
    res = server.rio_compute_event(*JEJU[:2], event_spec={"n_outsider": 1000})
    assert res["unmatched_sectors"] == []


def test_tool_compute_event_strict():
    with pytest.raises(UnmatchedSectorError):
        server.rio_compute_event(*JEJU[:2], event_spec={
            "policy_spending": [{"sector_code": "999", "amount_mw": 5.0}]}, strict=True)


def test_rio_list_sectors():
    sectors = server.rio_list_sectors(*JEJU)
    assert len(sectors) == 83
    codes = [s["sector_code"] for s in sectors]
    assert codes[0] == "01" and "80" in codes
    assert all(s["sector_name"] for s in sectors)
