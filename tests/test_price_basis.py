"""Issue #17 1절 / #6: price_basis constant|nominal, employment-only deflation."""
import math

import pytest

from rio_mcp import server

JEJU = ("제주", 2020)
L52 = {"sector_code": "52", "amount_mw": 10_000, "vendor_in_region_share": 1.0}


def _pb(res):
    a = res["assumptions"][0]
    assert a["code"] == "price_basis"
    return a


# --- golden (#17 6절) ------------------------------------------------------ #
def test_golden_constant_default_unchanged():
    res = server.rio_compute_effects(*JEJU, spending=[L52])
    t = res["totals"]
    assert round(t["production_in_region_mw"], 1) == 12406.9
    assert round(t["value_added_in_region_mw"], 1) == 6729.6
    assert round(t["employment_in_region_persons"], 2) == 158.31
    assert round(t["employment_out_region_persons"], 2) == 27.19
    assert res["price_basis"] == "constant"
    a = _pb(res)
    assert a["price_basis"] == "constant" and a["table_year"] == 2020
    assert a["message"] == ("금액을 2020년(표 기준연도) 불변가격으로 간주함 — 현재가 금액이면 "
                            "취업유발이 물가 상승분만큼 과대 추정될 수 있음")
    assert res["warnings"] == []


@pytest.mark.parametrize("how", ["line", "top"])
def test_golden_nominal_deflator_117(how):
    """Rounding: persons to 2 decimals (engine 158.3063/1.17 = 135.3045 → 135.30;
    27.1929/1.17 = 23.2418 → 23.24)."""
    if how == "line":
        res = server.rio_compute_effects(*JEJU, spending=[{**L52, "deflator": 1.17}],
                                         price_basis="nominal")
    else:
        res = server.rio_compute_effects(*JEJU, spending=[L52], price_basis="nominal",
                                         deflator=1.17)
    t = res["totals"]
    assert round(t["production_in_region_mw"], 1) == 12406.9
    assert round(t["value_added_in_region_mw"], 1) == 6729.6
    assert round(t["employment_in_region_persons"], 2) == 135.30
    assert round(t["employment_out_region_persons"], 2) == 23.24
    assert _pb(res)["price_basis"] == "nominal" and "GDP 디플레이터" in _pb(res)["message"]
    assert res["warnings"] == []


def test_golden_nominal_without_deflator_is_none():
    res = server.rio_compute_effects(*JEJU, spending=[L52], price_basis="nominal")
    t = res["totals"]
    assert t["employment_in_region_persons"] is None
    assert t["employment_out_region_persons"] is None
    assert round(t["production_in_region_mw"], 1) == 12406.9  # unaffected
    assert any("디플레이터가 없는 줄이 1개" in w for w in res["warnings"])
    assert res["lines"][0]["employment_in_region_persons"] is None


# --- nominal behaviour ----------------------------------------------------- #
def test_partial_deflators_give_none_not_partial_sum():
    res = server.rio_compute_effects(*JEJU, price_basis="nominal", spending=[
        {**L52, "deflator": 1.17},
        {"sector_code": "80", "amount_mw": 100, "vendor_in_region_share": 1.0}])
    assert res["totals"]["employment_in_region_persons"] is None
    assert res["lines"][0]["employment_in_region_persons"] == pytest.approx(158.3063 / 1.17, abs=1e-3)
    assert res["lines"][1]["employment_in_region_persons"] is None


def test_line_deflator_overrides_top_level():
    a = server.rio_compute_effects(*JEJU, price_basis="nominal", deflator=2.0,
                                   spending=[{**L52, "deflator": 1.17}])
    b = server.rio_compute_effects(*JEJU, price_basis="nominal", deflator=1.17, spending=[L52])
    assert a["totals"] == b["totals"]


def test_korean_alias_deflator():
    res = server.rio_compute_effects(*JEJU, price_basis="nominal",
                                     spending=[{**L52, "디플레이터": 1.17}])
    assert round(res["totals"]["employment_in_region_persons"], 2) == 135.30


def test_zero_amount_and_n_lines_do_not_need_deflator():
    res = server.rio_compute_effects(*JEJU, price_basis="nominal", deflator=None, spending=[
        {"sector_code": "52", "amount_mw": 0, "vendor_in_region_share": 1.0},
        {"sector_code": "74", "amount_mw": 30, "effect_yn": "N"}])
    assert res["totals"]["employment_in_region_persons"] == 0.0


@pytest.mark.parametrize("bad", [0, -1.0, "NaN", float("inf"), "abc"])
def test_invalid_deflator_errors(bad):
    with pytest.raises(ValueError, match="deflator"):
        server.rio_compute_effects(*JEJU, spending=[{**L52, "deflator": bad}],
                                   price_basis="nominal")
    with pytest.raises(ValueError, match="deflator"):
        server.rio_compute_effects(*JEJU, spending=[L52], price_basis="nominal", deflator=bad)


def test_nan_deflator_is_missing_not_error():
    # a blank cell read from a CSV/DataFrame arrives as float NaN → "not given"
    res = server.rio_compute_effects(*JEJU, spending=[{**L52, "deflator": float("nan")}],
                                     price_basis="nominal")
    assert res["totals"]["employment_in_region_persons"] is None


def test_invalid_price_basis_errors():
    with pytest.raises(ValueError, match="price_basis"):
        server.rio_compute_effects(*JEJU, spending=[L52], price_basis="real")


def test_constant_with_deflator_warns_and_ignores():
    res = server.rio_compute_effects(*JEJU, spending=[L52], deflator=1.17)
    assert round(res["totals"]["employment_in_region_persons"], 2) == 158.31
    assert any("price_basis=constant라 deflator를 적용하지 않음" in w for w in res["warnings"])


# --- event ------------------------------------------------------------------ #
def test_event_constant_unchanged_and_reports_assumption():
    spec = {"policy_spending": [L52], "n_outsider": 1000}
    res = server.rio_compute_event(*JEJU, event_spec=spec)
    assert round(res["policy_expenditure"]["employment_in_region_persons"], 2) == 158.31
    assert _pb(res)["price_basis"] == "constant" and res["warnings"] == []


def test_event_nominal_channel_deflators():
    spec = {"policy_spending": [L52], "n_outsider": 1000,
            "policy_deflator": 1.17, "participant_deflator": 1.25}
    base = server.rio_compute_event(*JEJU, event_spec={"policy_spending": [L52], "n_outsider": 1000})
    res = server.rio_compute_event(*JEJU, event_spec=spec, price_basis="nominal")
    pol, part = res["policy_expenditure"], res["participant"]
    assert round(pol["employment_in_region_persons"], 2) == 135.30
    assert pol["production_in_region_mw"] == base["policy_expenditure"]["production_in_region_mw"]
    assert part["employment_in_region_persons"] == pytest.approx(
        base["participant"]["employment_in_region_persons"] / 1.25, abs=1e-3)
    assert res["combined"]["employment_in_region_persons"] == pytest.approx(
        pol["employment_in_region_persons"] + part["employment_in_region_persons"], abs=1e-3)


def test_event_nominal_missing_participant_deflator():
    spec = {"policy_spending": [L52], "n_outsider": 1000, "policy_deflator": 1.17}
    res = server.rio_compute_event(*JEJU, event_spec=spec, price_basis="nominal")
    assert res["policy_expenditure"]["employment_in_region_persons"] is not None
    assert res["participant"]["employment_in_region_persons"] is None
    assert res["combined"]["employment_in_region_persons"] is None
    assert res["combined"]["production_in_region_mw"] is not None
    assert any(w.startswith("[participant] price_basis=nominal") for w in res["warnings"])


def test_event_top_level_deflator_covers_all_channels():
    res = server.rio_compute_event(*JEJU, price_basis="nominal", deflator=1.17,
                                   event_spec={"policy_spending": [L52], "n_outsider": 1000})
    assert res["combined"]["employment_in_region_persons"] is not None
    assert not any("디플레이터가 없는" in w for w in res["warnings"])


def test_event_visitor_group_deflator_and_profile_year_warning():
    groups = [{"label": "내국인", "n": 500, "profile": "jeju_domestic_visitor", "deflator": 1.1},
              {"label": "외국인", "n": 100, "profile": "jeju_foreign_visitor"}]
    res = server.rio_compute_event(*JEJU, price_basis="nominal",
                                   event_spec={"event_type": "forum_mice", "visitor_groups": groups})
    by = res["participant_by_group"]
    assert by["내국인"]["employment_in_region_persons"] is not None
    assert by["외국인"]["employment_in_region_persons"] is None
    assert res["participant"]["employment_in_region_persons"] is None
    # survey-year profiles are named, never re-priced
    assert any("jeju_domestic_visitor" in w and "자동 환산하지 않음" in w for w in res["warnings"])
    base = server.rio_compute_event(*JEJU, event_spec={"event_type": "forum_mice",
                                                       "visitor_groups": groups})
    assert by["내국인"]["production_in_region_mw"] == base["participant_by_group"]["내국인"]["production_in_region_mw"]
    assert by["내국인"]["employment_in_region_persons"] == pytest.approx(
        base["participant_by_group"]["내국인"]["employment_in_region_persons"] / 1.1, abs=1e-3)


# --- report ----------------------------------------------------------------- #
def test_report_shows_assumptions():
    res = server.rio_compute_effects(*JEJU, spending=[{"sector_code": "52", "amount_mw": 100}])
    md = server.rio_render_report(res["totals"], preset="final", assumptions=res["assumptions"])
    assert "- 가정: 금액을 2020년(표 기준연도) 불변가격으로 간주함" in md
    assert "- 가정: 역내 조달 비율을 지정하지 않아 100%로 가정함" in md
    md2 = server.rio_render_report(res, preset="final")  # whole response
    assert md2 == md


def test_report_nominal_none_employment_is_na():
    res = server.rio_compute_effects(*JEJU, spending=[L52], price_basis="nominal")
    md = server.rio_render_report(res, preset="final")
    assert "| 취업유발효과 (명) | N/A" in md and "GDP 디플레이터" in md


def test_report_default_assumption_without_input():
    md = server.rio_render_report({"production_in_region_mw": 1.0, "production_out_region_mw": 1.0},
                                  table_year=2020)
    assert "- 가정: 금액을 2020년(표 기준연도) 불변가격으로 간주함" in md
