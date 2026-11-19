"""korea-rio-mcp MCP server (stdio).

Exposes the RIO engine, BOK base-table acquisition, and standardized
documentation as MCP tools, plus two prompts for the judgment-heavy steps
(budget→sector mapping, documentation tone) that are intentionally left to the
LLM layer rather than deterministic tools.
"""
from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version as _pkg_version
from typing import Any

import pandas as pd
try:  # mcp>=2: FastMCP was renamed MCPServer (same decorator/run API we use)
    from mcp.server.mcpserver import MCPServer as FastMCP
    _MCP2 = True
except ImportError:  # mcp<2
    from mcp.server.fastmcp import FastMCP
    _MCP2 = False

from .engine import defaults, profiles
from .engine.coefficients import load_coefficients, load_sectors
from .engine.mapping import (
    crosscheck_mapping,
    input_assumptions,
    line_deflators,
    prepare_spending,
)
from .engine import price
from .engine.effects import (
    UnmatchedSectorError,
    compute_effects,
    find_unmatched_sectors,
    event_site_effects_standard,
    stay_spending_effects_standard,
    summarize,
    unmatched_warnings,
    visitor_group_effects,
)
from .store import cache
from .data_source import bok
from .docs.report import render_report

try:
    _VERSION = _pkg_version("korea-rio-mcp")
except PackageNotFoundError:  # running from a source tree without install
    _VERSION = "0+unknown"
# mcp 2.x reports an empty serverInfo.version unless given one; 1.x FastMCP
# rejects the kwarg (it reports the mcp package version instead).
mcp = FastMCP("korea-rio-mcp", version=_VERSION) if _MCP2 else FastMCP("korea-rio-mcp")


def _load(region: str, table_year: int, classification: str) -> pd.DataFrame:
    return load_coefficients(cache.resolve_path(region, table_year, classification))


def _totals(df: pd.DataFrame, nominal: bool) -> dict:
    """summarize(); under nominal, employment is None if any line lacks it."""
    t = summarize(df)
    if nominal and not df.empty:
        amt = df["amount_mw"].astype(float) != 0 if "amount_mw" in df.columns else True
        for col in price.EMPLOYMENT_COLS:
            if col in df.columns and (df[col].isna() & amt).any():
                return price.null_employment(t)
    return t


def _missing_deflator_warning(n: int, channel: str | None = None) -> str:
    prefix = f"[{channel}] " if channel else ""
    return (f"{prefix}price_basis=nominal인데 디플레이터가 없는 줄이 {n}개 있어 취업유발을 "
            "산출하지 않음(None) — 줄별 deflator 또는 최상위 deflator를 지정할 것 "
            "(기본 디플레이터는 임의 적용하지 않음)")


def _ignored_deflator_warning(channel: str | None = None) -> str:
    prefix = f"[{channel}] " if channel else ""
    return (f"{prefix}price_basis=constant라 deflator를 적용하지 않음 — 현재가 금액이면 "
            "price_basis='nominal'로 지정할 것")


def _no_own_deflators(spending: list[dict]) -> bool:
    """True when no counted line carries its own deflator."""
    own = line_deflators(spending, None)
    return bool(own) and all(d is None for d in own)


def _profile_year_warnings(names: list[str], table_year: int) -> list[str]:
    out = []
    for name in dict.fromkeys(names):
        try:
            meta = profiles.resolve(name)["meta"]
        except FileNotFoundError:
            continue
        year = meta.get("price_year") or meta.get("survey_year")
        if year and int(year) != int(table_year):
            out.append(f"[participant] 방문객 단가 프로파일 {name}은 {year}년 가격 — 단가는 "
                       "자동 환산하지 않음. 취업유발 환산은 participant 디플레이터로만 함")
    return out


def _check(df: pd.DataFrame, coef: pd.DataFrame, strict: bool,
           channel: str | None = None) -> list[dict]:
    """Collect sector codes missing from ``coef``; raise if ``strict``."""
    unmatched = find_unmatched_sectors(df, coef)
    if channel is not None:
        unmatched = [{"channel": channel, **u} for u in unmatched]
    if strict and unmatched:
        raise UnmatchedSectorError(unmatched)
    return unmatched


# --------------------------------------------------------------------------- #
# (1) Base table
# --------------------------------------------------------------------------- #
@mcp.tool()
def rio_list_coefficients() -> list[dict]:
    """List coefficient tables available (cached or bundled)."""
    return cache.list_available()


@mcp.tool()
def rio_list_sectors(region: str, table_year: int,
                     classification: str = "중분류(83부문)") -> list[dict]:
    """List the sector codes and names of one coefficient table.

    Use it to check ``sector_code`` values before rio_compute_effects /
    rio_compute_event: a code that is not in this list contributes zero effect
    (reported under ``unmatched_sectors``/``warnings``, or an error with
    ``strict=True``).
    """
    return load_sectors(cache.resolve_path(region, table_year, classification))


@mcp.tool()
def rio_crosscheck_mapping(region: str, table_year: int, mapping: list[dict],
                           classification: str = "중분류(83부문)",
                           budget_total_mw: float | None = None) -> dict:
    """Check a budget→sector mapping table before computing (no effects computed).

    ``mapping``: rows as produced by the map_budget_to_sectors prompt
    {line_id, item, detail?, sector_code, sector_name?, amount_mw, effect_yn,
    vendor_in_region_share, rationale?, confidence?}; Korean column names
    (매핑_부문코드, 추정금액_백만원, 효과여부, vendor_jeju_share, 예산항목 …)
    are accepted as aliases.

    Returns line counts, amount totals (all / effect Y / effect N / Y after
    in-region share) and the N share by amount and count; ``unmatched_sectors``
    (Y rows whose code is not in the table — see rio_list_sectors);
    ``issues`` (missing code on a Y row, missing/invalid/negative amount,
    invalid effect_yn, share outside 0–1, duplicate line_id, and — when
    ``budget_total_mw`` is given — a gap between the budget and the mapped
    total); ``notes`` (informational: Y rows without a share get 1.0, rows
    without effect_yn count as Y). ``ok`` is true when there are no issues
    and no unmatched sectors; notes do not affect it.
    """
    coef = _load(region, table_year, classification)
    return {"region": region, "table_year": table_year,
            **crosscheck_mapping(mapping, coef, budget_total_mw=budget_total_mw)}


@mcp.tool()
def rio_list_profiles() -> list[dict]:
    """List bundled stay-spending consumption profiles (visitor-type unit-cost
    tables: e.g. jeju_domestic_leisure for festivals, jeju_domestic_visitor /
    jeju_foreign_visitor for MICE/forum attendees). Each entry names its data
    source; details in data/reference/profiles/<name>/SOURCE.md."""
    return profiles.list_profiles()


@mcp.tool()
def rio_check_base_table_update(cached_year: int | None = 2020) -> dict:
    """Check whether BOK has published a newer regional IO base year.

    Polls the BOK publication list; falls back to known years offline. Returns
    the latest published year, whether it is newer than ``cached_year``, and the
    manual-download URL (downloads are not automated).
    """
    return bok.check_update(cached_year=cached_year)


@mcp.tool()
def rio_load_base_table(xlsx_path: str, region: str, table_year: int,
                        classification: str = "중분류(83부문)") -> dict:
    """Extract induced coefficients from a BOK workbook and cache them.

    The region/year must have a layout registered in engine/regions.py
    (currently 제주 2020 중분류). Add others there with their subtotal rows.
    """
    return bok.load_base_table(xlsx_path, region, table_year, classification)


# --------------------------------------------------------------------------- #
# (2) Effect computation
# --------------------------------------------------------------------------- #
@mcp.tool()
def rio_compute_effects(region: str, table_year: int, spending: list[dict],
                        classification: str = "중분류(83부문)",
                        strict: bool = False,
                        price_basis: str = "constant",
                        deflator: float | None = None) -> dict:
    """Compute induced effects for sector-level spending.

    ``spending``: list of mapping-table rows {sector_code, amount_mw,
    vendor_in_region_share?, effect_yn?, line_id?, item?, sector_name?, ...}
    — the output of the map_budget_to_sectors prompt can be passed as-is
    (Korean column names such as 매핑_부문코드/추정금액_백만원/효과여부/
    vendor_jeju_share are accepted as aliases). Rows with effect_yn "N"
    (also n/아니오) are left out and listed under ``excluded_lines``; rows
    without effect_yn count as Y. The in-region capture share (default 1.0)
    scales the spending base before the induced coefficients further split
    each effect in/out of region. Check a mapping first with
    rio_crosscheck_mapping.
    Returns per-line effects and a totals summary (production/value-added/
    employment, each in-region/out-of-region), plus ``unmatched_sectors``
    (lines whose sector_code is not in the table, with their amount — their
    effect is counted as 0) and matching ``warnings``. A null sector_code or a
    zero amount is treated as an intended zero and not reported. With
    ``strict=True`` an unmatched code raises an error instead. Valid codes:
    rio_list_sectors.
    Input checks: ``assumptions`` (a list of {code, message, ...}) records
    defaults applied — ``default_vendor_share`` with ``n_lines`` when rows
    omit vendor_in_region_share ("역내 조달 비율을 지정하지 않아 100%로 가정함");
    ``warnings`` repeats it with the line count and flags single lines whose
    amount is > 10조 원 (10,000,000 백만원) or 0 < amount < 1 백만원 as a
    possible unit error (amount_mw is in 백만 원).
    Price basis: ``price_basis="constant"`` (default) treats amounts as
    prices of the table's base year (assumption always reported in
    ``assumptions`` as code ``price_basis``). ``price_basis="nominal"``
    treats them as current prices and converts employment only: each line's
    employment uses amount ÷ deflator (base year = 1.0; recommended: each
    line's sector output deflator rebased to table_year — a single index such
    as the GDP deflator for all lines is flagged as a simplifying assumption). Production and value-added are not
    changed — their coefficients are 원/원 ratios, so deflating, applying and
    re-inflating gives the same numbers. The deflator comes from the line's
    ``deflator`` key, else the top-level ``deflator`` argument; ≤ 0 or
    non-finite raises an error. If any line lacks one, employment is None in
    the lines concerned and in the totals (no partial sums), with a warning.
    """
    pb = price.check_price_basis(price_basis)
    default_defl = price.validate_deflator(deflator, where="deflator")
    coef = _load(region, table_year, classification)
    df_in, excluded = prepare_spending(spending)
    deflators = line_deflators(spending, default_defl)
    assumptions, input_warnings = input_assumptions(spending)
    unmatched = _check(df_in, coef, strict)
    df = compute_effects(df_in, coef)
    price_warnings = []
    price_assumptions = []
    if pb == "nominal":
        df, missing = price.deflate_employment(df, deflators)
        if missing:
            price_warnings.append(_missing_deflator_warning(missing))
        if default_defl is not None and _no_own_deflators(spending):
            a, w = price.single_deflator_assumption(default_defl)
            price_assumptions.append(a)
            price_warnings.append(w)
    elif any(d is not None for d in deflators):
        price_warnings.append(_ignored_deflator_warning())
    return {
        "region": region, "table_year": table_year,
        "price_basis": pb,
        "lines": df.to_dict(orient="records"),
        "totals": _totals(df, pb == "nominal"),
        "excluded_lines": excluded,
        "unmatched_sectors": unmatched,
        "assumptions": [price.price_assumption(pb, table_year), *price_assumptions, *assumptions],
        "warnings": input_warnings + price_warnings + unmatched_warnings(unmatched),
    }


@mcp.tool()
def rio_compute_event(region: str, table_year: int, event_spec: dict,
                      classification: str = "중분류(83부문)",
                      strict: bool = False,
                      price_basis: str = "constant",
                      deflator: float | None = None) -> dict:
    """Compute the combined effect of an economic event.

    ``event_spec`` keys:
      * ``policy_spending``: list of mapping-table rows, same rules as
        rio_compute_effects (aliases accepted, effect_yn "N" rows excluded and
        listed under ``excluded_lines``)
      * ``event_type`` (opt, default "festival"): preset for participant
        parameters — "festival" (26p17) or "forum_mice" (MICE/국제행사:
        purpose_weight 1.0, on-site channel off by default to avoid double
        counting organizer-paid catering).
      * ``visitor_groups`` (opt): list of {label, n, profile?, purpose_weight?,
        per_capita_won?, event_site_sector?, monthly_weight?} — heterogeneous
        groups (e.g. domestic vs foreign attendees) each riding their own
        unit-cost profile (see rio_list_profiles). Takes precedence over
        ``n_outsider``.
      * ``n_outsider``: outside-visitor count (legacy single-track channel)
      * ``per_capita_won`` (opt), ``event_site_sector`` (opt) — on-site consumption
      * ``purpose_weight`` (opt), ``monthly_weight`` (opt) — ancillary stay
      * ``include_stay`` (opt, default True)

    Returns separate summaries for the policy-expenditure channel (reliable,
    homogeneous) and the participant channel (variable), kept apart per the
    26p17 methodology, plus a combined total (and per-group summaries when
    visitor_groups is used). ``unmatched_sectors`` (each tagged with its
    ``channel``: policy_expenditure / participant) and ``warnings`` list
    non-zero amounts whose sector_code is not in the table (counted as 0);
    intended zeros (null code, e.g. a profile's air/sea items, or amount 0)
    are not reported. ``strict=True`` raises on any unmatched code instead.
    Input checks: ``assumptions`` (a list of {code, message, ...}) records
    defaults applied — ``default_vendor_share`` with ``n_lines`` when policy_spending rows
    omit vendor_in_region_share ("역내 조달 비율을 지정하지 않아 100%로 가정함");
    ``warnings`` repeats it with the line count and flags single lines whose
    amount is > 10조 원 (10,000,000 백만원) or 0 < amount < 1 백만원 as a
    possible unit error (amount_mw is in 백만 원). Policy-channel entries carry
    ``channel``.
    Price basis: same ``price_basis``/``deflator`` rules as
    rio_compute_effects (employment only; production/value-added unchanged).
    Deflator precedence — policy channel: line ``deflator`` >
    ``event_spec["policy_deflator"]`` > ``deflator``; participant channel:
    visitor group ``deflator`` > ``event_spec["participant_deflator"]`` >
    ``deflator``. A channel (or group) without one gets employment None, and
    so does ``combined``. A channel-wide deflator with no per-line values (and
    any participant-channel deflator, since visitor spending spans several
    sectors) is flagged as ``single_deflator`` — a simplifying assumption.
    Visitor unit-cost profiles are never re-priced; under
    nominal, a profile whose meta gives a price/survey year different from
    table_year is named in ``warnings``.
    """
    pb = price.check_price_basis(price_basis)
    nominal = pb == "nominal"
    default_defl = price.validate_deflator(deflator, where="deflator")
    policy_defl = price.validate_deflator(event_spec.get("policy_deflator"),
                                          where="event_spec.policy_deflator")
    part_defl = price.validate_deflator(event_spec.get("participant_deflator"),
                                        where="event_spec.participant_deflator")
    policy_defl = policy_defl if policy_defl is not None else default_defl
    part_defl = part_defl if part_defl is not None else default_defl
    coef = _load(region, table_year, classification)
    out: dict[str, Any] = {"region": region, "table_year": table_year, "price_basis": pb}
    unmatched: list[dict] = []
    assumptions: list[dict] = []
    input_warnings: list[str] = []
    price_warnings: list[str] = []
    price_assumptions: list[dict] = []
    any_deflator = policy_defl is not None or part_defl is not None
    out["excluded_lines"] = []

    policy = event_spec.get("policy_spending") or []
    if policy:
        pol_df, out["excluded_lines"] = prepare_spending(policy)
        pol_deflators = line_deflators(policy, policy_defl)
        any_deflator = any_deflator or any(d is not None for d in pol_deflators)
        assumptions, input_warnings = input_assumptions(policy, channel="policy_expenditure")
        unmatched += _check(pol_df, coef, strict, channel="policy_expenditure")
        pol_eff = compute_effects(pol_df, coef)
        if nominal:
            pol_eff, missing = price.deflate_employment(pol_eff, pol_deflators)
            if missing:
                price_warnings.append(_missing_deflator_warning(missing, "policy_expenditure"))
            if policy_defl is not None and _no_own_deflators(policy):
                a, w = price.single_deflator_assumption(policy_defl, "policy_expenditure")
                price_assumptions.append(a)
                price_warnings.append(w)
        out["policy_expenditure"] = _totals(pol_eff, nominal)

    participant_frames = []
    visitor_groups = event_spec.get("visitor_groups")
    n_outsider = event_spec.get("n_outsider")
    group_defl: dict[str, float | None] = {}
    used_profiles: list[str] = []
    if visitor_groups:
        event_type = event_spec.get("event_type", "festival")
        preset = defaults.EVENT_TYPE_PRESETS.get(event_type, {})
        for gi, g in enumerate(visitor_groups):
            gd = price.validate_deflator(g.get("deflator"), where=f"visitor_groups[{gi}]")
            label = str(g.get("label", "방문객"))
            resolved = gd if gd is not None else part_defl
            # Deflators are applied per label after the group frames are combined,
            # so groups sharing a label must resolve to the same deflator.
            if nominal and label in group_defl and group_defl[label] != resolved:
                raise ValueError(
                    f"visitor_groups[{gi}]: label {label!r} is shared with another group "
                    f"but its deflator differs ({group_defl[label]!r} vs {resolved!r}); "
                    "give each group a unique label or the same deflator")
            group_defl[label] = resolved
            any_deflator = any_deflator or gd is not None
            if g.get("include_stay", True) and not (g.get("unit_cost_path") and g.get("industry_map_path")):
                used_profiles.append(g.get("profile", preset.get("profile")) or profiles.DEFAULT_PROFILE)
        part_df = visitor_group_effects(coef, visitor_groups, event_type=event_type)
        participant_frames.append(part_df)
    elif n_outsider:
        ese = event_site_effects_standard(
            coef, n_outsider=float(n_outsider),
            per_capita_won=int(event_spec.get("per_capita_won", defaults.DEFAULT_PER_CAPITA_WON)),
            sector_code=str(event_spec.get("event_site_sector", defaults.DEFAULT_EVENT_SITE_SECTOR)),
        )
        participant_frames.append(ese)
        if event_spec.get("include_stay", True):
            spe = stay_spending_effects_standard(
                coef, n_outsider=float(n_outsider),
                purpose_weight=float(event_spec.get("purpose_weight", defaults.DEFAULT_PURPOSE_WEIGHT)),
                monthly_weight=event_spec.get("monthly_weight"),
            )
            participant_frames.append(spe)
            used_profiles.append(profiles.DEFAULT_PROFILE)
    if participant_frames:
        part_df = pd.concat(participant_frames, ignore_index=True)
        unmatched += _check(part_df, coef, strict, channel="participant")
        if nominal:
            if group_defl and "그룹" in part_df.columns:
                part_deflators = [group_defl.get(str(gl), part_defl) for gl in part_df["그룹"]]
            else:
                part_deflators = [part_defl] * len(part_df)
            part_df, missing = price.deflate_employment(part_df, part_deflators)
            if missing:
                price_warnings.append(_missing_deflator_warning(missing, "participant"))
            # Participant spending spans several sectors under one channel/group
            # deflator, so any deflator applied there is a single index.
            applied = sorted({d for d in part_deflators if d is not None})
            if applied:
                a, w = price.single_deflator_assumption(applied[0] if len(applied) == 1 else applied,
                                                        "participant")
                price_assumptions.append(a)
                price_warnings.append(w)
            price_warnings += _profile_year_warnings(used_profiles, table_year)
        if visitor_groups:
            out["participant_by_group"] = {
                str(label): _totals(sub, nominal) for label, sub in part_df.groupby("그룹")
            }
        out["participant"] = _totals(part_df, nominal)
    if not nominal and any_deflator:
        price_warnings.append(_ignored_deflator_warning())

    # combined
    keys = ["production_in_region_mw", "value_added_in_region_mw", "employment_in_region_persons",
            "production_out_region_mw", "value_added_out_region_mw", "employment_out_region_persons"]
    combined = {}
    for k in keys:
        vals = [out[part].get(k) for part in ("policy_expenditure", "participant") if part in out]
        # None (e.g. employment with no regional source) propagates as N/A
        combined[k] = None if any(v is None for v in vals) else round(sum(vals), 4)
    out["combined"] = combined
    out["unmatched_sectors"] = unmatched
    out["assumptions"] = [price.price_assumption(pb, table_year), *price_assumptions, *assumptions]
    out["warnings"] = input_warnings + price_warnings + unmatched_warnings(unmatched)
    return out


# --------------------------------------------------------------------------- #
# (3) Documentation
# --------------------------------------------------------------------------- #
@mcp.tool()
def rio_render_report(results: dict, preset: str = "interim",
                      title: str | None = None, input_budget_mw: float | None = None,
                      assumptions: list[dict] | None = None,
                      table_year: int | None = None) -> str:
    """Render a standardized markdown effect table.

    ``preset='interim'`` shows production-induction only; ``preset='final'``
    shows production + value-added + employment together. ``results`` is the
    six-key totals dict from rio_compute_effects/rio_compute_event, or the
    whole response (then its ``assumptions`` are used). Assumption messages
    (price basis, default in-region share …) are printed under the table —
    pass ``assumptions`` from the compute response when giving only totals;
    without any, the default price-basis assumption for ``table_year`` is
    shown. Employment None (e.g. nominal without deflator) renders as N/A.
    """
    return render_report(results, preset=preset, title=title, input_budget_mw=input_budget_mw,
                         assumptions=assumptions, table_year=table_year)


# --------------------------------------------------------------------------- #
# Prompts — judgment-heavy steps kept in the LLM layer
# --------------------------------------------------------------------------- #
@mcp.prompt()
def map_budget_to_sectors(budget_items: str = "") -> str:
    """Guide mapping raw budget line items to BOK medium-classification sectors."""
    return (
        "You are mapping budget line items to Bank of Korea medium-classification "
        "(83-sector) input-output codes for a regional economic-impact analysis.\n\n"
        "For each line item, decide:\n"
        "1. The single best sector code (e.g. 80 스포츠·오락, 58 음식점·숙박, "
        "52 도소매, 74 사업지원, 15 인쇄·미디어, 73 장비임대). Confirm every code "
        "against rio_list_sectors(region, table_year) — do not guess codes.\n"
        "2. effect_yn: Y if it generates real local production demand, N if it is "
        "a transfer/reserve/non-demand item.\n"
        "3. vendor_in_region_share (0–1): the share procured from in-region vendors. "
        "Always fill it; if omitted the tools assume 1.0 (100%) and warn.\n"
        "4. A one-line rationale and a confidence (상/중/하).\n\n"
        "Output the table as a list of rows with exactly these keys: line_id, item "
        "(예산항목), detail (세부내역), sector_code, sector_name, amount_mw "
        "(추정금액, 백만원), effect_yn (Y/N), vendor_in_region_share (0–1), "
        "rationale (근거), confidence (상/중/하). Keep effect_yn N rows in the "
        "table — the tools exclude them from the totals and report them.\n\n"
        "Next: pass the rows to rio_crosscheck_mapping (with budget_total_mw if "
        "the budget total is known) and fix every issue and unmatched sector; then "
        "pass the same rows unchanged as ``spending`` to rio_compute_effects (or "
        "``policy_spending`` in rio_compute_event).\n\n"
        f"Budget items:\n{budget_items}"
    )


@mcp.prompt()
def documentation_standard() -> str:
    """The 26p17 reporting standard for effect tables."""
    return (
        "Reporting standard for RIO effect tables:\n"
        "- Interim report (중간보고): show 생산유발효과 (production induction) only; "
        "put 부가가치유발·취업유발 in an appendix.\n"
        "- Final report (최종보고) total-effect table: show all three indicators "
        "(생산유발 백만원, 부가가치유발 백만원, 취업유발 명) together.\n"
        "- Always split 도내/도외 (in-region / out-of-region) and report 도내비중.\n"
        "- Keep the reliable policy-expenditure channel separate from the variable "
        "participant channel; do not use a single blended efficiency multiplier as "
        "the headline policy metric.\n"
        "- State the price basis under the table (the assumptions list from the compute "
        "tools: constant = amounts taken as table-year prices; nominal = employment "
        "deflated with per-sector output deflators, or a single index flagged as a "
        "simplifying assumption). If employment is None, do not publish it.\n"
        "Use rio_render_report(preset='interim'|'final') to produce the table."
    )


def main() -> None:
    """Console entry point: run the MCP server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
