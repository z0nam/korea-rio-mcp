"""Issue #8: mapping tables — aliases, effect_yn filter, crosscheck tool."""
import pandas as pd
import pytest

from rio_mcp import server
from rio_mcp.engine.mapping import normalize_effect_yn, prepare_spending
from rio_mcp.engine.effects import summarize, policy_expenditure_effects
from rio_mcp.engine.coefficients import load_coefficients

from pathlib import Path

JEJU = ("제주", 2020)
P09 = Path(__file__).parent / "fixtures" / "spending_industry_mapping_p09.csv"

# N rows a mapper keeps in the table (transfer / reserve) — must never be summed.
N_ROWS_KO = [
    {"line_id": "L03", "예산항목": "예비비", "매핑_부문코드": "74", "매핑_부문명": "사업지원",
     "추정금액_백만원": 30.0, "효과여부": "N", "vendor_jeju_share": 1.0},
    {"line_id": "L04", "예산항목": "시상금", "매핑_부문코드": None, "매핑_부문명": None,
     "추정금액_백만원": 20.0, "효과여부": "아니오", "vendor_jeju_share": None},
]


def _p09_rows_ko():
    df = pd.read_csv(P09, dtype={"매핑_부문코드": str})
    return df.where(df.notna(), None).to_dict(orient="records")


def _to_new_keys(rows_ko):
    m = {"line_id": "line_id", "예산항목": "item", "세부내역": "detail",
         "매핑_부문코드": "sector_code", "매핑_부문명": "sector_name",
         "추정금액_백만원": "amount_mw", "효과여부": "effect_yn",
         "vendor_jeju_share": "vendor_in_region_share", "근거및매핑이유": "rationale",
         "신뢰도": "confidence"}
    return [{m[k]: v for k, v in r.items() if k in m} for r in rows_ko]


@pytest.mark.parametrize("v,exp", [("Y", "Y"), (" y ", "Y"), ("예", "Y"), ("n", "N"),
                                   ("N ", "N"), ("아니오", "N"), (None, None), ("", None)])
def test_normalize_effect_yn(v, exp):
    assert normalize_effect_yn(v) == exp


def test_normalize_effect_yn_rejects_other():
    with pytest.raises(ValueError):
        normalize_effect_yn("maybe")


def test_golden_unchanged_via_csv_engine():
    coef = load_coefficients(Path(__file__).parent / "fixtures" / "induce_coefficients_jeju_medium.csv")
    s = summarize(policy_expenditure_effects(coef, P09))
    assert round(s["production_in_region_mw"], 4) == 350.3085


@pytest.mark.parametrize("fmt", ["old_korean_columns", "new_prompt_keys"])
def test_tool_matches_golden_and_drops_n_rows(fmt):
    """Same mapping, before (Korean columns) and after (canonical keys) the
    prompt change: P09 golden holds and the N rows are excluded, not summed."""
    rows = _p09_rows_ko() + N_ROWS_KO
    if fmt == "new_prompt_keys":
        rows = _to_new_keys(rows)
    res = server.rio_compute_effects(*JEJU, spending=rows)
    assert round(res["totals"]["production_in_region_mw"], 4) == 350.3085
    assert round(res["totals"]["employment_in_region_persons"], 4) == 2.3885
    assert [x["line_id"] for x in res["excluded_lines"]] == ["L03", "L04"]
    assert res["unmatched_sectors"] == [] and len(res["lines"]) == 2


def test_event_policy_spending_drops_n_rows():
    res = server.rio_compute_event(*JEJU, event_spec={
        "policy_spending": _to_new_keys(_p09_rows_ko() + N_ROWS_KO)})
    assert round(res["policy_expenditure"]["production_in_region_mw"], 4) == 350.3085
    assert len(res["excluded_lines"]) == 2


def test_legacy_spending_without_effect_yn_still_counts():
    res = server.rio_compute_effects(*JEJU, spending=[{"sector_code": "80", "amount_mw": 10.0}])
    assert res["excluded_lines"] == [] and res["totals"]["production_in_region_mw"] > 0


def test_canonical_key_wins_over_alias():
    df, _ = prepare_spending([{"sector_code": "80", "매핑_부문코드": "58", "amount_mw": 1.0}])
    assert df["sector_code"].tolist() == ["80"]


def test_bad_effect_yn_errors():
    with pytest.raises(ValueError, match="effect_yn"):
        server.rio_compute_effects(*JEJU, spending=[
            {"sector_code": "80", "amount_mw": 1.0, "effect_yn": "?"}])


def test_crosscheck_clean_p09():
    res = server.rio_crosscheck_mapping(*JEJU, mapping=_p09_rows_ko(), budget_total_mw=271.4)
    assert res["ok"] is True
    assert res["issues"] == [] and res["notes"] == []
    assert res["totals"]["amount_y_mw"] == pytest.approx(271.4)
    assert res["budget_gap_mw"] == pytest.approx(0.0)


def test_crosscheck_flags_problems():
    rows = _to_new_keys(_p09_rows_ko()) + [
        {"line_id": "L01", "item": "중복", "sector_code": "80", "amount_mw": 1.0, "effect_yn": "Y",
         "vendor_in_region_share": 0.5},
        {"line_id": "L05", "sector_code": None, "amount_mw": 5.0, "effect_yn": "Y",
         "vendor_in_region_share": 1.0},
        {"line_id": "L06", "sector_code": "999", "amount_mw": 7.0, "effect_yn": "y",
         "vendor_in_region_share": 1.5},
        {"line_id": "L07", "sector_code": "80", "amount_mw": 4.0, "effect_yn": "Y"},
        {"line_id": "L08", "sector_code": "80", "amount_mw": 4.0, "effect_yn": "몰라"},
        {"line_id": "L09", "sector_code": "80", "amount_mw": None, "effect_yn": "Y"},
        {"line_id": "L10", "sector_code": "74", "amount_mw": 9.0, "effect_yn": "N"},
    ]
    res = server.rio_crosscheck_mapping(*JEJU, mapping=rows, budget_total_mw=500.0)
    codes = {(i["line_id"], i["code"]) for i in res["issues"]}
    assert ("L01", "duplicate_line_id") in codes
    assert ("L05", "missing_sector_code") in codes
    assert ("L06", "share_out_of_range") in codes
    assert ("L08", "invalid_effect_yn") in codes
    assert ("L09", "missing_amount") in codes
    assert (None, "budget_mismatch") in codes
    assert [u["sector_code"] for u in res["unmatched_sectors"]] == ["999"]
    assert res["unmatched_sectors"][0]["line_id"] == "L06"
    # missing share is a note, not an issue
    assert [(n["line_id"], n["code"]) for n in res["notes"]] == [("L07", "missing_share")]
    assert not any(i["code"] == "missing_share" for i in res["issues"])
    assert res["n_effect_n"] == 1 and res["totals"]["amount_n_mw"] == 9.0
    assert res["ok"] is False


def test_crosscheck_missing_share_alone_keeps_ok():
    res = server.rio_crosscheck_mapping(*JEJU, mapping=[
        {"line_id": "A", "sector_code": "80", "amount_mw": 1.0, "effect_yn": "Y"}])
    assert res["ok"] is True and res["notes"][0]["code"] == "missing_share"
