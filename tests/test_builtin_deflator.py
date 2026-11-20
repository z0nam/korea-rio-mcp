"""#20 step 2: built-in per-sector deflators as the default (nominal + price_year)."""
import pytest

from rio_mcp import server
from rio_mcp.engine import deflators, price

JEJU = ("제주", 2020)
L52 = {"sector_code": "52", "amount_mw": 10_000, "vendor_in_region_share": 1.0}
EMP = ("employment_in_region_persons", "employment_out_region_persons")
OTHER = ("production_in_region_mw", "value_added_in_region_mw",
         "production_out_region_mw", "value_added_out_region_mw")


def _const(spending):
    return server.rio_compute_effects(*JEJU, spending=spending, price_basis="constant")


def _codes(res):
    return [a["code"] for a in res["assumptions"]]


# --- loader ------------------------------------------------------------------ #
def test_loader_covers_83_sectors_2020_2025():
    table = deflators.load_table()
    assert deflators.years() == (2020, 2021, 2022, 2023, 2024, 2025)
    assert len(table) == 83 * 6
    assert all(v == (1.0, v[1]) for (c, y), v in table.items() if y == 2020)


def test_loader_lookup_normalizes_code():
    assert deflators.lookup("52", 2025) == (1.23138, "VA대리")
    assert deflators.lookup(52, 2025) == deflators.lookup("52", 2025)
    assert deflators.lookup(8, 2021) == deflators.lookup("08", 2021)
    assert deflators.lookup("52", 2026) is None
    assert deflators.lookup(None, 2025) is None


# --- default: built-in value applied ---------------------------------------- #
def test_builtin_applied_by_default():
    base = _const([L52])
    res = server.rio_compute_effects(*JEJU, spending=[L52], price_year=2025)
    t, b = res["totals"], base["totals"]
    assert round(b["employment_in_region_persons"], 2) == 158.31
    for k in EMP:
        assert t[k] == pytest.approx(b[k] / 1.231380, abs=1e-4)
    for k in OTHER:
        assert t[k] == b[k]  # production / value-added unchanged
    assert res["price_basis"] == {"basis": "nominal", "method": "builtin", "price_year": 2025,
                                  "sources": {"builtin": 1}}
    first = res["assumptions"][0]
    assert first["code"] == "builtin_deflator" and first["price_year"] == 2025
    assert first["message"].startswith(
        "내장 부문별 산출 디플레이터 적용(ECOS 405Y007 등, 2020=1.0, 2025년 값)")
    assert res["assumptions"][1]["code"] == "price_basis"
    assert res["assumptions"][1]["price_year"] == 2025
    assert not any("디플레이터가 없는" in w for w in res["warnings"])


def test_price_year_2020_is_identity():
    res = server.rio_compute_effects(*JEJU, spending=[L52], price_year=2020)
    assert res["totals"] == _const([L52])["totals"]


def test_string_price_year_accepted():
    a = server.rio_compute_effects(*JEJU, spending=[L52], price_year="2025")
    b = server.rio_compute_effects(*JEJU, spending=[L52], price_year=2025)
    assert a["totals"] == b["totals"]


@pytest.mark.parametrize("bad", ["abc", 2025.5, True, float("inf")])
def test_invalid_price_year_errors(bad):
    with pytest.raises(ValueError, match="price_year"):
        server.rio_compute_effects(*JEJU, spending=[L52], price_year=bad)


# --- precedence ------------------------------------------------------------- #
def test_line_deflator_overrides_builtin():
    base = _const([L52])["totals"]
    res = server.rio_compute_effects(*JEJU, spending=[{**L52, "deflator": 1.1}], price_year=2025)
    assert res["totals"]["employment_in_region_persons"] == pytest.approx(
        base["employment_in_region_persons"] / 1.1, abs=1e-4)
    assert res["price_basis"]["method"] == "line"
    assert "builtin_deflator" not in _codes(res)


def test_top_level_deflator_overrides_builtin():
    base = _const([L52])["totals"]
    res = server.rio_compute_effects(*JEJU, spending=[L52], price_year=2025, deflator=1.1)
    assert res["totals"]["employment_in_region_persons"] == pytest.approx(
        base["employment_in_region_persons"] / 1.1, abs=1e-4)
    assert res["price_basis"]["method"] == "top"
    assert "single_deflator" in _codes(res)


def test_mixed_line_and_builtin():
    rows = [{**L52, "deflator": 1.1},
            {"sector_code": "58", "amount_mw": 500, "vendor_in_region_share": 1.0}]
    base = _const(rows)["lines"]
    res = server.rio_compute_effects(*JEJU, spending=rows, price_year=2024)
    lines = res["lines"]
    assert lines[0]["employment_in_region_persons"] == pytest.approx(
        base[0]["employment_in_region_persons"] / 1.1, abs=1e-6)
    d58 = deflators.lookup("58", 2024)[0]
    assert lines[1]["employment_in_region_persons"] == pytest.approx(
        base[1]["employment_in_region_persons"] / d58, abs=1e-6)
    assert res["price_basis"]["method"] == "mixed"
    assert res["price_basis"]["sources"] == {"line": 1, "builtin": 1}
    assert res["assumptions"][0]["n_lines"] == 1
    assert "single_deflator" not in _codes(res)


# --- missing / out-of-range price_year --------------------------------------- #
def test_missing_price_year_gives_none_and_warning():
    res = server.rio_compute_effects(*JEJU, spending=[L52])
    t = res["totals"]
    assert t["employment_in_region_persons"] is None and t["employment_out_region_persons"] is None
    assert t["production_in_region_mw"] == _const([L52])["totals"]["production_in_region_mw"]
    assert res["lines"][0]["employment_in_region_persons"] is None
    assert res["price_basis"]["method"] == "none"
    assert res["price_basis"]["sources"] == {"missing": 1}
    (w,) = [w for w in res["warnings"] if "디플레이터가 없는 줄" in w]
    assert w.startswith("price_year(금액의 가격연도)를 지정하지 않음")
    assert "최신 연도(2025)를 price_year로 지정해 근사할 수 있으며, 그 경우 가정에 표시됨" in w
    assert "builtin_deflator" not in _codes(res)


@pytest.mark.parametrize("year", [2026, 2019])
def test_out_of_range_price_year_gives_none_and_warning(year):
    res = server.rio_compute_effects(*JEJU, spending=[L52], price_year=year)
    assert res["totals"]["employment_in_region_persons"] is None
    (w,) = [w for w in res["warnings"] if "디플레이터가 없는 줄" in w]
    assert f"price_year={year}" in w and "범위(2020–2025) 밖" in w and "외삽하지 않음" in w
    assert "최신 연도(2025)를 price_year로 지정해 근사할 수 있으며" in w


def test_partial_builtin_gives_none_not_partial_sum():
    rows = [{**L52, "deflator": 1.1}, {"sector_code": "58", "amount_mw": 500}]
    res = server.rio_compute_effects(*JEJU, spending=rows, price_year=2026)
    assert res["lines"][0]["employment_in_region_persons"] is not None
    assert res["lines"][1]["employment_in_region_persons"] is None
    assert res["totals"]["employment_in_region_persons"] is None


def test_explicit_deflators_need_no_price_year():
    res = server.rio_compute_effects(*JEJU, spending=[{**L52, "deflator": 1.1}])
    assert res["totals"]["employment_in_region_persons"] is not None
    assert not any("디플레이터가 없는" in w for w in res["warnings"])


def test_unmatched_and_zero_lines_do_not_null_employment():
    rows = [L52, {"sector_code": "99", "amount_mw": 10}, {"sector_code": "58", "amount_mw": 0}]
    res = server.rio_compute_effects(*JEJU, spending=rows, price_year=2025)
    assert res["totals"]["employment_in_region_persons"] is not None
    assert res["price_basis"]["sources"] == {"builtin": 1}
    assert res["unmatched_sectors"]


def test_builtin_unavailable_for_other_tables():
    r = price.builtin_unavailable_reason
    assert r(2025, 2020, "중분류(83부문)") is None
    assert "중분류(83부문) 전용" in r(2025, 2020, "대분류(33부문)")
    assert "2015년 표" in r(2025, 2015, "중분류(83부문)")


# --- constant reproduction ---------------------------------------------------- #
def test_constant_reproduces_and_ignores_price_year():
    plain = _const([L52])
    res = server.rio_compute_effects(*JEJU, spending=[L52], price_basis="constant",
                                     price_year=2025)
    assert res["totals"] == plain["totals"]
    assert round(res["totals"]["employment_in_region_persons"], 2) == 158.31
    assert res["price_basis"] == {"basis": "constant", "method": "constant", "price_year": 2025}
    assert "builtin_deflator" not in _codes(res)
    assert any("price_basis=constant라 deflator·price_year를 적용하지 않음" in w
               for w in res["warnings"])


# --- event: channels mixed --------------------------------------------------- #
def test_event_channels_builtin_and_explicit():
    spec = {"policy_spending": [L52, {"sector_code": "58", "amount_mw": 200,
                                      "vendor_in_region_share": 1.0, "deflator": 1.05}],
            "n_outsider": 1000}
    base = server.rio_compute_event(*JEJU, event_spec=spec, price_basis="constant")
    res = server.rio_compute_event(*JEJU, event_spec=spec, price_year=2023)
    # policy: line 52 built-in, line 58 own deflator
    d52 = deflators.lookup("52", 2023)[0]
    exp_pol = (_const([L52])["totals"]["employment_in_region_persons"] / d52
               + _const([{"sector_code": "58", "amount_mw": 200}])["totals"]
               ["employment_in_region_persons"] / 1.05)
    assert res["policy_expenditure"]["employment_in_region_persons"] == pytest.approx(exp_pol, abs=1e-3)
    # participant: each spending row deflated by its own sector's built-in value
    assert res["participant"]["employment_in_region_persons"] < base["participant"]["employment_in_region_persons"]
    for k in OTHER:
        assert res["combined"][k] == base["combined"][k]
    assert res["combined"]["employment_in_region_persons"] == pytest.approx(
        res["policy_expenditure"]["employment_in_region_persons"]
        + res["participant"]["employment_in_region_persons"], abs=1e-3)
    pb = res["price_basis"]
    assert pb["method"] == "mixed" and pb["price_year"] == 2023
    assert pb["by_channel"]["policy_expenditure"] == {"builtin": 1, "line": 1}
    assert set(pb["by_channel"]["participant"]) == {"builtin"}
    assert res["assumptions"][0]["code"] == "builtin_deflator"
    assert "single_deflator" not in _codes(res)  # built-in values are per sector


def test_event_participant_builtin_matches_per_row_division():
    spec = {"n_outsider": 1000}
    base = server.rio_compute_event(*JEJU, event_spec=spec, price_basis="constant")
    res = server.rio_compute_event(*JEJU, event_spec=spec, price_year=2025)
    # rebuild the expected value from the constant participant rows
    from rio_mcp.engine import defaults
    from rio_mcp.engine.effects import (event_site_effects_standard,
                                        stay_spending_effects_standard)
    import pandas as pd
    coef = server._load(*JEJU, "중분류(83부문)")
    rows = pd.concat([
        event_site_effects_standard(coef, 1000.0, per_capita_won=defaults.DEFAULT_PER_CAPITA_WON,
                                    sector_code=defaults.DEFAULT_EVENT_SITE_SECTOR),
        stay_spending_effects_standard(coef, 1000.0, purpose_weight=defaults.DEFAULT_PURPOSE_WEIGHT),
    ], ignore_index=True)
    exp = sum(r["employment_in_region_persons"] / deflators.lookup(r["sector_code"], 2025)[0]
              for _, r in rows.iterrows() if r["amount_mw"] and r["sector_code"])
    assert res["participant"]["employment_in_region_persons"] == pytest.approx(exp, abs=1e-3)
    assert base["participant"]["employment_in_region_persons"] > exp


def test_event_channel_deflator_overrides_builtin_and_is_single():
    spec = {"policy_spending": [L52], "n_outsider": 1000, "participant_deflator": 1.2}
    base = server.rio_compute_event(*JEJU, event_spec=spec, price_basis="constant")
    res = server.rio_compute_event(*JEJU, event_spec=spec, price_year=2025)
    assert res["participant"]["employment_in_region_persons"] == pytest.approx(
        base["participant"]["employment_in_region_persons"] / 1.2, abs=1e-3)
    assert res["price_basis"]["by_channel"] == {"policy_expenditure": {"builtin": 1},
                                                "participant": {"channel": 9}}
    single = [a for a in res["assumptions"] if a["code"] == "single_deflator"]
    assert [a["channel"] for a in single] == ["participant"]


def test_event_missing_price_year_nulls_combined():
    res = server.rio_compute_event(*JEJU, event_spec={"policy_spending": [L52], "n_outsider": 1000})
    assert res["policy_expenditure"]["employment_in_region_persons"] is None
    assert res["participant"]["employment_in_region_persons"] is None
    assert res["combined"]["employment_in_region_persons"] is None
    assert res["combined"]["production_in_region_mw"] is not None
    assert any(w.startswith("[policy_expenditure] price_year") for w in res["warnings"])
    assert any(w.startswith("[participant] price_year") for w in res["warnings"])


# --- proxy grades shown ------------------------------------------------------ #
def test_proxy_grades_listed_when_used():
    rows = [{"sector_code": c, "amount_mw": 100, "vendor_in_region_share": 1.0}
            for c in ("01", "83", "50", "52")]
    res = server.rio_compute_effects(*JEJU, spending=rows, price_year=2025)
    first = res["assumptions"][0]
    assert first["code"] == "builtin_deflator" and first["n_lines"] == 4
    assert first["proxy_sectors"] == [{"sector_code": "50", "grade": "산출측대리"},
                                      {"sector_code": "52", "grade": "VA대리"},
                                      {"sector_code": "83", "grade": "총지수대리"}]
    assert first["message"].endswith(
        "— 대리 지수 사용 부문: 50 산출측대리, 52 VA대리, 83 총지수대리")


def test_no_proxy_suffix_for_output_index_sectors():
    res = server.rio_compute_effects(*JEJU, price_year=2025, spending=[
        {"sector_code": "58", "amount_mw": 100, "vendor_in_region_share": 1.0}])
    first = res["assumptions"][0]
    assert first["proxy_sectors"] == []
    assert first["message"] == "내장 부문별 산출 디플레이터 적용(ECOS 405Y007 등, 2020=1.0, 2025년 값)"


def test_report_first_assumption_is_builtin():
    res = server.rio_compute_effects(*JEJU, spending=[L52], price_year=2025)
    md = server.rio_render_report(res, preset="final")
    lines = [ln for ln in md.splitlines() if ln.startswith("- 가정:")]
    assert lines[0].startswith("- 가정: 내장 부문별 산출 디플레이터 적용(ECOS 405Y007 등, 2020=1.0, 2025년 값)")
    assert "| 취업유발효과 (명) | 128.6" in md
