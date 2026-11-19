"""RIO impact computation (region-agnostic).

Ported from 26p17 ``compute_rio_single.py``. Three effect channels:

* :func:`policy_expenditure_effects` — (1) direct policy/budget spending
* :func:`event_site_effects_standard` — (2a) outside-visitor on-site consumption
* :func:`stay_spending_effects_standard` — (2b) outside-visitor ancillary stay

All produce the six generic effect columns via :func:`compute_effects`:
production / value-added / employment, each split in-region / out-of-region.
Coefficient column names are the generic ``_in_region`` / ``_out_region`` form
(see :mod:`rio_mcp.engine.coefficients`).
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from . import defaults, profiles
from .coefficients import normalize_sector_code

_EFFECT_OUT = [
    "production_in_region_mw", "value_added_in_region_mw", "employment_in_region_persons",
    "production_out_region_mw", "value_added_out_region_mw", "employment_out_region_persons",
]


class UnmatchedSectorError(ValueError):
    """Raised by ``strict`` computations when a sector code is not in the table."""

    def __init__(self, unmatched: list[dict]):
        self.unmatched = unmatched
        codes = ", ".join(f"{u['sector_code']}({u['amount_mw']:g}백만원)" for u in unmatched)
        super().__init__(
            f"Sector code(s) not in coefficient table: {codes}. "
            "Check codes with rio_list_sectors."
        )


def _norm_code(sc_raw) -> str | None:
    """Normalize a sector code to the table's form; None if blank."""
    return normalize_sector_code(sc_raw)


def find_unmatched_sectors(df_amount: pd.DataFrame, coef: pd.DataFrame) -> list[dict]:
    """Return spending lines whose sector code is absent from ``coef``.

    Intended zeros are *not* reported: ``sector_code`` None/blank (e.g. the
    air/sea items of a stay profile, deliberately routed out of region) and
    lines whose amount is 0. Each entry: ``sector_code`` (as given),
    ``sector_name``, ``amount_mw``, plus ``line_id``/``item``/``그룹``/
    ``stay_item`` when present.
    """
    out = []
    if df_amount.empty or "sector_code" not in df_amount.columns:
        return out
    for _, r in df_amount.iterrows():
        sc = _norm_code(r["sector_code"])
        amt = float(r["amount_mw"])
        if sc is None or amt == 0 or sc in coef.index:
            continue
        entry = {"sector_code": str(r["sector_code"]).strip(),
                 "sector_name": r.get("sector_name", "") if pd.notna(r.get("sector_name", "")) else "",
                 "amount_mw": round(amt, 6)}
        for extra in ("line_id", "item", "그룹", "stay_item"):
            if extra in r and pd.notna(r[extra]):
                entry[extra] = r[extra]
        out.append(entry)
    return out


def unmatched_warnings(unmatched: list[dict]) -> list[str]:
    """Human-readable warnings for :func:`find_unmatched_sectors` output."""
    return [
        f"부문코드 {u['sector_code']!r}가 계수표에 없어 금액 {u['amount_mw']:g}백만원의 효과를 0으로 처리함"
        + (f" (그룹 {u['그룹']})" if u.get("그룹") else "")
        for u in unmatched
    ]


def compute_effects(df_amount: pd.DataFrame, coef: pd.DataFrame,
                    strict: bool = False) -> pd.DataFrame:
    """Multiply ``amount_mw`` (백만원) by per-sector induced coefficients.

    ``df_amount`` needs ``sector_code`` and ``amount_mw`` columns. Employment
    uses ``amount_mw / 1000`` because its coefficient is in 명/10억원.
    sector_code None / absent from coef / amount 0 → zero effect. Codes absent
    from ``coef`` (with a non-zero amount) can be listed with
    :func:`find_unmatched_sectors`; with ``strict=True`` they raise
    :class:`UnmatchedSectorError` instead.
    """
    if strict:
        unmatched = find_unmatched_sectors(df_amount, coef)
        if unmatched:
            raise UnmatchedSectorError(unmatched)
    rows = []
    for _, r in df_amount.iterrows():
        sc = _norm_code(r["sector_code"])
        amt = float(r["amount_mw"])
        if sc is None or sc not in coef.index or amt == 0:
            rows.append({**r.to_dict(), **{c: 0.0 for c in _EFFECT_OUT}})
            continue
        m = coef.loc[sc]
        rows.append({**r.to_dict(),
                     "production_in_region_mw": amt * m["multiplier_production_in_region"],
                     "value_added_in_region_mw": amt * m["multiplier_value_added_in_region"],
                     "employment_in_region_persons": amt / 1000 * m["multiplier_employment_in_region"],
                     "production_out_region_mw": amt * m["multiplier_production_out_region"],
                     "value_added_out_region_mw": amt * m["multiplier_value_added_out_region"],
                     "employment_out_region_persons": amt / 1000 * m["multiplier_employment_out_region"]})
    return pd.DataFrame(rows)


def policy_expenditure_effects(coef: pd.DataFrame, spend_map_path: str | Path) -> pd.DataFrame:
    """(1) Policy/budget expenditure effect.

    Spending-map CSV columns (Korean, as in 26p17): 매핑_부문코드, 추정금액_백만원,
    효과여부 (Y/N), vendor_jeju_share (in-region capture share). Only 효과여부=Y
    rows count (normalized like the MCP tools: y/예 accepted, blank excluded);
    in-region amount = 추정금액 × capture share.
    """
    from .mapping import normalize_effect_yn

    sm = pd.read_csv(spend_map_path, dtype={"매핑_부문코드": str})
    sm = sm[sm["효과여부"].map(normalize_effect_yn) == "Y"].copy()
    sm["sector_code"] = sm["매핑_부문코드"].map(normalize_sector_code)
    capture = sm["vendor_jeju_share"] if "vendor_jeju_share" in sm.columns else sm.get("vendor_in_region_share", 1.0)
    sm["amount_mw"] = sm["추정금액_백만원"].astype(float) * pd.to_numeric(capture).astype(float)
    df = sm[["line_id", "예산항목", "세부내역", "sector_code", "매핑_부문명",
             "amount_mw"]].rename(columns={"매핑_부문명": "sector_name"})
    return compute_effects(df, coef)


def event_site_effects_standard(coef: pd.DataFrame, n_outsider: float,
                                per_capita_won: int = defaults.DEFAULT_PER_CAPITA_WON,
                                sector_code: str = defaults.DEFAULT_EVENT_SITE_SECTOR,
                                sector_name: str = "행사현장 소비",
                                group_label: str = "외지인",
                                item_label: str = "행사현장 종합") -> pd.DataFrame:
    """(2a) On-site outside-visitor consumption — standard-value mapping.

    Total spend = n_outsider × per_capita_won, assigned to a single sector
    chosen by event character (80 performance/experience, 52 sales/expo,
    58 food). Used when no satisfaction survey measured spending.
    """
    total_spend_mw = n_outsider * per_capita_won / 1_000_000
    df = pd.DataFrame([{
        "그룹": group_label, "소비항목": item_label,
        "sector_code": sector_code, "sector_name": sector_name,
        "n_persons": int(round(n_outsider)), "per_capita_won": int(per_capita_won),
        "amount_mw": total_spend_mw,
    }])
    return compute_effects(df, coef)


def stay_spending_effects_standard(coef: pd.DataFrame, n_outsider: float,
                                   purpose_weight: float = defaults.DEFAULT_PURPOSE_WEIGHT,
                                   monthly_weight: dict | None = None,
                                   apply_overlap_subtraction: bool = False,
                                   festival_match_per_item: dict | None = None,
                                   unit_cost_path: str | Path | None = None,
                                   industry_map_path: str | Path | None = None,
                                   profile: str | None = None,
                                   group_label: str | None = None) -> pd.DataFrame:
    """(2b) Outside-visitor ancillary-stay effect (Approach A: survey unit costs).

    n_outsider × purpose_weight = induced visitors; their stay spending uses a
    unit-cost table (period-weighted) mapped to sectors. Items with sector
    code 0 (air/sea transport) leak fully out-of-region → amount 0.

    The unit-cost table comes from ``profile`` (a bundled directory under
    ``data/reference/profiles/``, default ``jeju_domestic_leisure`` = 26p17
    festival standard); explicit ``unit_cost_path``/``industry_map_path``
    override it. ``monthly_weight`` keys must match the table's period columns
    (e.g. ``{"annual": 1.0}`` for single-column tables); when omitted, the
    profile's ``default_weight`` applies. Pass ``apply_overlap_subtraction=True``
    with ``festival_match_per_item`` to net out on-site overlap.
    """
    if apply_overlap_subtraction and festival_match_per_item is None:
        raise ValueError("apply_overlap_subtraction=True requires festival_match_per_item dict")

    if unit_cost_path is None or industry_map_path is None:
        prof = profiles.resolve(profile or profiles.DEFAULT_PROFILE)
        unit_cost_path = unit_cost_path or prof["unit_cost_path"]
        industry_map_path = industry_map_path or prof["industry_map_path"]
        if monthly_weight is None:
            monthly_weight = prof["meta"].get("default_weight")
    if monthly_weight is None:
        monthly_weight = dict(defaults.DEFAULT_MONTHLY_WEIGHT)

    unit = pd.read_csv(unit_cost_path)
    smap = pd.read_csv(industry_map_path, dtype={"매핑_부문코드": str})

    months = list(monthly_weight.keys())
    weights = [monthly_weight[m] for m in months]
    if abs(sum(weights) - 1.0) > 1e-6:
        raise ValueError(f"monthly_weight must sum to 1.0, got {sum(weights)}")
    unit["weighted_avg_won"] = sum(unit[m] * w for m, w in zip(months, weights))
    unit["weighted_avg_won"] = unit["weighted_avg_won"].round(0).astype(int)

    n_eff = n_outsider * purpose_weight
    label_cols = {"그룹": group_label} if group_label is not None else {}
    rows = []
    for _, r in unit.iterrows():
        item = r["item"]
        kto = float(r["weighted_avg_won"])
        smap_row = smap[smap["stay_item"] == item].iloc[0]
        sector_code_raw = str(smap_row["매핑_부문코드"]).strip()

        if sector_code_raw == "0":
            rows.append({**label_cols, "stay_item": item, "kto_unit_won": int(kto),
                         "festival_overlap_won": 0, "stay_unit_won": 0,
                         "sector_code": None, "sector_name": "(out-of-region — air/sea)",
                         "n_eff_persons": int(round(n_eff)), "amount_mw": 0.0})
            continue

        if apply_overlap_subtraction:
            festival_unit = float(festival_match_per_item.get(item, 0))
            stay_unit = max(0.0, kto - festival_unit)
        else:
            festival_unit, stay_unit = 0.0, kto

        rows.append({**label_cols, "stay_item": item, "kto_unit_won": int(kto),
                     "festival_overlap_won": int(festival_unit),
                     "stay_unit_won": int(round(stay_unit)),
                     "sector_code": normalize_sector_code(sector_code_raw),
                     "sector_name": smap_row["매핑_부문명"],
                     "n_eff_persons": int(round(n_eff)),
                     "amount_mw": n_eff * stay_unit / 1_000_000})

    return compute_effects(pd.DataFrame(rows), coef)


def visitor_group_effects(coef: pd.DataFrame, groups: list[dict],
                          event_type: str = "festival") -> pd.DataFrame:
    """(2) Participant channel for heterogeneous visitor groups.

    Runs on-site (2a) and ancillary-stay (2b) effects per group and returns a
    single frame with a 그룹 label column, so e.g. domestic and foreign
    attendees each ride their own unit-cost profile and are summed afterwards.

    Each group dict requires ``label`` and ``n``; optional keys ``profile``,
    ``purpose_weight``, ``per_capita_won``, ``event_site_sector``,
    ``monthly_weight``, ``unit_cost_path``, ``industry_map_path``,
    ``include_site``, ``include_stay`` override the ``event_type`` preset
    (:data:`defaults.EVENT_TYPE_PRESETS`). A preset ``per_capita_won`` of None
    (forum_mice) skips the on-site channel unless the group sets a value —
    on-site catering at MICE events is usually already in the organizer budget.
    """
    if event_type not in defaults.EVENT_TYPE_PRESETS:
        raise ValueError(f"Unknown event_type {event_type!r}; "
                         f"available: {sorted(defaults.EVENT_TYPE_PRESETS)}")
    preset = defaults.EVENT_TYPE_PRESETS[event_type]
    frames = []
    for g in groups:
        label = g.get("label", "방문객")
        n = float(g["n"])
        per_capita = g.get("per_capita_won", preset.get("per_capita_won"))
        if g.get("include_site", True) and per_capita:
            frames.append(event_site_effects_standard(
                coef, n, per_capita_won=int(per_capita),
                sector_code=str(g.get("event_site_sector",
                                      preset.get("event_site_sector",
                                                 defaults.DEFAULT_EVENT_SITE_SECTOR))),
                group_label=label))
        if g.get("include_stay", True):
            frames.append(stay_spending_effects_standard(
                coef, n,
                purpose_weight=float(g.get("purpose_weight",
                                           preset.get("purpose_weight",
                                                      defaults.DEFAULT_PURPOSE_WEIGHT))),
                monthly_weight=g.get("monthly_weight"),
                unit_cost_path=g.get("unit_cost_path"),
                industry_map_path=g.get("industry_map_path"),
                profile=g.get("profile", preset.get("profile")),
                group_label=label))
    if not frames:
        return pd.DataFrame(columns=["그룹", *_EFFECT_OUT])
    return pd.concat(frames, ignore_index=True)


def summarize(df: pd.DataFrame) -> dict:
    """Aggregate the six effect columns of a compute_effects result.

    Uses ``min_count=1`` so a column that is entirely NaN (e.g. employment when
    the region's coefficient table has no employment data) summarizes to NaN —
    "not available" — rather than a misleading 0.0.
    """
    out = {}
    if df.empty:
        # No spending lines (e.g. every row excluded as effect_yn N) → zero effect.
        return {col: 0.0 for col in _EFFECT_OUT}
    for col in _EFFECT_OUT:
        if col not in df.columns:
            continue
        total = df[col].sum(min_count=1)
        out[col] = None if pd.isna(total) else round(float(total), 4)
    return out
