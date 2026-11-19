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
from .engine.mapping import crosscheck_mapping, input_assumptions, prepare_spending
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
                        strict: bool = False) -> dict:
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
    """
    coef = _load(region, table_year, classification)
    df_in, excluded = prepare_spending(spending)
    assumptions, input_warnings = input_assumptions(spending)
    unmatched = _check(df_in, coef, strict)
    df = compute_effects(df_in, coef)
    return {
        "region": region, "table_year": table_year,
        "lines": df.to_dict(orient="records"),
        "totals": summarize(df),
        "excluded_lines": excluded,
        "unmatched_sectors": unmatched,
        "assumptions": assumptions,
        "warnings": input_warnings + unmatched_warnings(unmatched),
    }


@mcp.tool()
def rio_compute_event(region: str, table_year: int, event_spec: dict,
                      classification: str = "중분류(83부문)",
                      strict: bool = False) -> dict:
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
    """
    coef = _load(region, table_year, classification)
    out: dict[str, Any] = {"region": region, "table_year": table_year}
    unmatched: list[dict] = []
    assumptions: list[dict] = []
    input_warnings: list[str] = []
    out["excluded_lines"] = []

    policy = event_spec.get("policy_spending") or []
    if policy:
        pol_df, out["excluded_lines"] = prepare_spending(policy)
        assumptions, input_warnings = input_assumptions(policy, channel="policy_expenditure")
        unmatched += _check(pol_df, coef, strict, channel="policy_expenditure")
        out["policy_expenditure"] = summarize(compute_effects(pol_df, coef))

    participant_frames = []
    visitor_groups = event_spec.get("visitor_groups")
    n_outsider = event_spec.get("n_outsider")
    if visitor_groups:
        part_df = visitor_group_effects(coef, visitor_groups,
                                        event_type=event_spec.get("event_type", "festival"))
        participant_frames.append(part_df)
        out["participant_by_group"] = {
            str(label): summarize(sub) for label, sub in part_df.groupby("그룹")
        }
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
    if participant_frames:
        part_df = pd.concat(participant_frames, ignore_index=True)
        unmatched += _check(part_df, coef, strict, channel="participant")
        out["participant"] = summarize(part_df)

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
    out["assumptions"] = assumptions
    out["warnings"] = input_warnings + unmatched_warnings(unmatched)
    return out


# --------------------------------------------------------------------------- #
# (3) Documentation
# --------------------------------------------------------------------------- #
@mcp.tool()
def rio_render_report(results: dict, preset: str = "interim",
                      title: str | None = None, input_budget_mw: float | None = None) -> str:
    """Render a standardized markdown effect table.

    ``preset='interim'`` shows production-induction only; ``preset='final'``
    shows production + value-added + employment together. ``results`` is the
    six-key totals dict from rio_compute_effects/rio_compute_event.
    """
    return render_report(results, preset=preset, title=title, input_budget_mw=input_budget_mw)


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
        "Use rio_render_report(preset='interim'|'final') to produce the table."
    )


def main() -> None:
    """Console entry point: run the MCP server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
