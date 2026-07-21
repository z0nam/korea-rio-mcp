"""Profile-based stay spending + visitor groups (forum/MICE track).

Golden stay-spending values locked from the pre-profile engine (flat reference
CSV layout) so the profile refactor provably changes nothing for the festival
path.
"""
from pathlib import Path

import pytest

from rio_mcp.engine import profiles
from rio_mcp.engine.coefficients import load_coefficients
from rio_mcp.engine.effects import (
    stay_spending_effects_standard,
    visitor_group_effects,
    summarize,
)
from rio_mcp.store import cache


@pytest.fixture(scope="module")
def coef():
    return load_coefficients(cache.resolve_path("제주", 2020, "중분류(83부문)"))


def test_leisure_profile_reproduces_prerefactor_golden(coef):
    # n=10,000, all defaults — locked before the flat CSVs moved into
    # profiles/jeju_domestic_leisure/.
    s = summarize(stay_spending_effects_standard(coef, 10_000))
    assert round(s["production_in_region_mw"], 4) == 4591.9935
    assert round(s["value_added_in_region_mw"], 4) == 1930.8332
    assert round(s["employment_in_region_persons"], 4) == 44.0064


def test_explicit_profile_equals_default(coef):
    a = summarize(stay_spending_effects_standard(coef, 5_000))
    b = summarize(stay_spending_effects_standard(coef, 5_000, profile="jeju_domestic_leisure"))
    assert a == b


def test_bundled_profiles_present():
    names = {p["name"] for p in profiles.list_profiles()}
    assert {"jeju_domestic_leisure", "jeju_domestic_visitor", "jeju_foreign_visitor",
            "jeju_domestic_business", "jeju_foreign_business",
            "jeju_domestic_mice_kto2016", "jeju_foreign_mice_kto2016"} <= names


def test_unknown_profile_raises():
    with pytest.raises(FileNotFoundError):
        profiles.resolve("no_such_profile")


def test_annual_column_profile_computes(coef):
    # jeju_foreign_visitor uses a single "annual" period column via its
    # meta default_weight — no monthly_weight needed from the caller.
    df = stay_spending_effects_standard(coef, 691, purpose_weight=1.0,
                                        profile="jeju_foreign_visitor")
    s = summarize(df)
    assert s["production_in_region_mw"] > 0
    # airfare rows (국제/국내) must be fully out-of-region (amount 0)
    air = df[df["stay_item"].str.contains("항공")]
    assert len(air) == 2
    assert (air["amount_mw"] == 0.0).all()


def test_visitor_groups_split_and_sum(coef):
    groups = [
        {"label": "내국인", "n": 5371, "profile": "jeju_domestic_visitor"},
        {"label": "외국인", "n": 691, "profile": "jeju_foreign_visitor"},
    ]
    df = visitor_group_effects(coef, groups, event_type="forum_mice")
    # forum_mice: on-site channel off by default → stay rows only
    assert "소비항목" not in df.columns or df["소비항목"].isna().all()
    by_group = {g: summarize(sub) for g, sub in df.groupby("그룹")}
    assert set(by_group) == {"내국인", "외국인"}
    total = summarize(df)
    parts = sum(by_group[g]["production_in_region_mw"] for g in by_group)
    # summarize() rounds to 4 decimals, so allow rounding slack
    assert abs(total["production_in_region_mw"] - parts) < 1e-3


def test_forum_mice_purpose_weight_default_is_one(coef):
    df1 = visitor_group_effects(coef, [{"label": "내국인", "n": 1000,
                                        "profile": "jeju_domestic_visitor"}],
                                event_type="forum_mice")
    df2 = stay_spending_effects_standard(coef, 1000, purpose_weight=1.0,
                                         profile="jeju_domestic_visitor",
                                         group_label="내국인")
    assert abs(df1["amount_mw"].sum() - df2["amount_mw"].sum()) < 1e-9


def test_visitor_groups_site_channel_opt_in(coef):
    # Supplying per_capita_won turns the on-site channel on even for forum_mice.
    df = visitor_group_effects(coef, [{"label": "내국인", "n": 1000,
                                       "profile": "jeju_domestic_visitor",
                                       "per_capita_won": 50_000}],
                               event_type="forum_mice")
    assert (df["sector_code"] == "58").any()  # site row in 음식점·숙박
    assert "stay_item" in df.columns  # stay rows still present
