"""Issue #17 (price-basis-independent parts): golden case, input assumptions,
unit warnings, mapping-column coverage, sector-code preservation."""
import pytest

from rio_mcp import server
from rio_mcp.engine.coefficients import load_coefficients, normalize_sector_code
from rio_mcp.engine.effects import UnmatchedSectorError
from rio_mcp.store import cache

JEJU = ("제주", 2020)
SHARE_MSG = "역내 조달 비율을 지정하지 않아 100%로 가정함"


def _input_assumptions(res):
    # price_basis is always reported (1절); these tests check the input ones.
    assert res["assumptions"][0]["code"] == "price_basis"
    return [a for a in res["assumptions"] if a["code"] != "price_basis"]


# --- 6절 golden case (constant / default call) ------------------------------ #
def test_golden_sector52_10000mw():
    """제주·2020·중분류, 부문 52, 10,000백만원, 역내조달 1.0.

    Expected values from the #17 request. Rounding: 백만원 figures to 1 decimal,
    persons to 2 decimals (engine returns 4 decimals: 12406.9413 / 6729.6348 /
    158.3063 / 27.1929)."""
    res = server.rio_compute_effects(*JEJU, spending=[
        {"sector_code": "52", "amount_mw": 10_000, "vendor_in_region_share": 1.0}])
    t = res["totals"]
    assert round(t["production_in_region_mw"], 1) == 12406.9
    assert round(t["value_added_in_region_mw"], 1) == 6729.6
    assert round(t["employment_in_region_persons"], 2) == 158.31
    assert round(t["employment_out_region_persons"], 2) == 27.19
    assert res["warnings"] == [] and _input_assumptions(res) == []


def test_golden_unmatched_and_strict():
    spending = [{"sector_code": "52", "amount_mw": 10_000, "vendor_in_region_share": 1.0},
                {"sector_code": "99", "amount_mw": 10, "vendor_in_region_share": 1.0}]
    res = server.rio_compute_effects(*JEJU, spending=spending)
    assert [u["sector_code"] for u in res["unmatched_sectors"]] == ["99"]
    assert round(res["totals"]["production_in_region_mw"], 1) == 12406.9  # unchanged
    with pytest.raises(UnmatchedSectorError):
        server.rio_compute_effects(*JEJU, spending=spending, strict=True)


# --- 2절 default vendor share ---------------------------------------------- #
def test_missing_vendor_share_warns_and_records_assumption():
    res = server.rio_compute_effects(*JEJU, spending=[
        {"line_id": "L1", "sector_code": "52", "amount_mw": 10_000},
        {"line_id": "L2", "sector_code": "80", "amount_mw": 50, "vendor_in_region_share": 0.5},
        {"line_id": "L3", "sector_code": "58", "amount_mw": 30},
    ])
    assert _input_assumptions(res) == [{"code": "default_vendor_share", "message": SHARE_MSG,
                                   "n_lines": 2, "line_ids": ["L1", "L3"]}]
    assert f"{SHARE_MSG} (2줄)" in res["warnings"]
    # numbers unchanged: missing share still means 1.0
    base = server.rio_compute_effects(*JEJU, spending=[
        {"sector_code": "52", "amount_mw": 10_000, "vendor_in_region_share": 1.0},
        {"sector_code": "80", "amount_mw": 50, "vendor_in_region_share": 0.5},
        {"sector_code": "58", "amount_mw": 30, "vendor_in_region_share": 1.0}])
    assert res["totals"] == base["totals"]


def test_effect_n_rows_not_counted_for_share_assumption():
    res = server.rio_compute_effects(*JEJU, spending=[
        {"sector_code": "52", "amount_mw": 100, "vendor_in_region_share": 1.0},
        {"sector_code": "74", "amount_mw": 30, "effect_yn": "N"}])
    assert _input_assumptions(res) == [] and res["warnings"] == []


def test_event_policy_channel_assumption():
    res = server.rio_compute_event(*JEJU, event_spec={
        "policy_spending": [{"sector_code": "52", "amount_mw": 100}], "n_outsider": 1000})
    assert _input_assumptions(res) == [{"code": "default_vendor_share", "message": SHARE_MSG,
                                   "n_lines": 1, "channel": "policy_expenditure"}]
    assert res["warnings"][0] == f"[policy_expenditure] {SHARE_MSG} (1줄)"


def test_event_without_policy_has_empty_assumptions():
    res = server.rio_compute_event(*JEJU, event_spec={"n_outsider": 1000})
    assert _input_assumptions(res) == [] and res["warnings"] == []


# --- 2절 unit warnings ------------------------------------------------------ #
@pytest.mark.parametrize("amt,flag", [
    (10_000_001, "10조 원 초과"), (10_000_000, None),
    (0.5, "1백만 원 미만"), (1.0, None), (0, None)])
def test_unit_warning_bounds(amt, flag):
    res = server.rio_compute_effects(*JEJU, spending=[
        {"line_id": "X", "sector_code": "52", "amount_mw": amt, "vendor_in_region_share": 1.0}])
    unit = [w for w in res["warnings"] if "금액 단위" in w]
    if flag:
        assert len(unit) == 1 and flag in unit[0] and "line_id X" in unit[0]
    else:
        assert unit == []


def test_unit_warning_in_event_and_crosscheck():
    row = {"line_id": "Y", "sector_code": "52", "amount_mw": 5e9, "effect_yn": "Y",
           "vendor_in_region_share": 1.0}
    ev = server.rio_compute_event(*JEJU, event_spec={"policy_spending": [row]})
    assert any("금액 단위" in w and w.startswith("[policy_expenditure]") for w in ev["warnings"])
    cc = server.rio_crosscheck_mapping(*JEJU, mapping=[row])
    assert [n["code"] for n in cc["notes"]] == ["amount_unit_suspect"]
    assert cc["ok"] is True  # notes do not affect ok


# --- 3절 required mapping columns (Korean names) ---------------------------- #
@pytest.mark.parametrize("amount_key", ["금액", "금액_백만원", "추정금액_백만원"])
def test_required_mapping_columns_korean(amount_key):
    """Request columns: line_id·예산항목·부문코드·금액·효과여부·역내조달비율."""
    rows = [
        {"line_id": "A1", "예산항목": "행사운영", "부문코드": "52", amount_key: 10_000,
         "효과여부": "Y", "역내조달비율": 1.0},
        {"line_id": "A2", "예산항목": "예비비", "부문코드": "74", amount_key: 300,
         "효과여부": "N", "역내조달비율": 1.0},
    ]
    cc = server.rio_crosscheck_mapping(*JEJU, mapping=rows, budget_total_mw=10_300)
    assert cc["ok"] is True and cc["notes"] == []
    assert cc["totals"]["amount_y_mw"] == 10_000 and cc["n_effect_n"] == 1
    res = server.rio_compute_effects(*JEJU, spending=rows)
    assert round(res["totals"]["production_in_region_mw"], 1) == 12406.9
    assert res["excluded_lines"][0]["line_id"] == "A2"
    assert res["lines"][0]["item"] == "행사운영"
    assert _input_assumptions(res) == []


def test_prompt_points_to_list_sectors():
    assert "rio_list_sectors" in server.map_budget_to_sectors("x")


# --- 5절 sector code preservation ------------------------------------------ #
@pytest.mark.parametrize("raw,exp", [
    ("80", "80"), (80, "80"), (8.0, "08"), ("8", "08"), (" 52 ", "52"), ("80.0", "80"),
    ("A", "A"), ("C01", "C01"), ("G", "G"), (None, None), ("", None), (float("nan"), None)])
def test_normalize_sector_code(raw, exp):
    assert normalize_sector_code(raw) == exp


def test_bundled_tables_codes_unchanged():
    for entry in cache.list_available():
        if "중분류" not in entry["file"]:
            continue
        coef = load_coefficients(entry["path"])
        codes = list(coef.index)
        assert codes == [f"{i:02d}" for i in range(1, len(codes) + 1)], entry["file"]
