"""korea-rio-mcp MCP server (stdio).

Exposes the RIO engine, BOK base-table acquisition, and standardized
documentation as MCP tools, plus two prompts for the judgment-heavy steps
(budget→sector mapping, documentation tone) that are intentionally left to the
LLM layer rather than deterministic tools.
"""
from __future__ import annotations

from typing import Any

import pandas as pd
from mcp.server.fastmcp import FastMCP

from .engine import defaults
from .engine.coefficients import load_coefficients
from .engine.effects import (
    compute_effects,
    event_site_effects_standard,
    stay_spending_effects_standard,
    summarize,
)
from .store import cache
from .data_source import bok
from .docs.report import render_report

mcp = FastMCP("korea-rio-mcp")


def _load(region: str, table_year: int, classification: str) -> pd.DataFrame:
    return load_coefficients(cache.resolve_path(region, table_year, classification))


# --------------------------------------------------------------------------- #
# (1) Base table
# --------------------------------------------------------------------------- #
@mcp.tool()
def rio_list_coefficients() -> list[dict]:
    """List coefficient tables available (cached or bundled)."""
    return cache.list_available()


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
                        classification: str = "중분류(83부문)") -> dict:
    """Compute induced effects for sector-level spending.

    ``spending``: list of {sector_code, amount_mw, vendor_in_region_share?}.
    The in-region capture share (default 1.0) scales the spending base before
    the induced coefficients further split each effect in/out of region.
    Returns per-line effects and a totals summary (production/value-added/
    employment, each in-region/out-of-region).
    """
    coef = _load(region, table_year, classification)
    rows = []
    for s in spending:
        share = float(s.get("vendor_in_region_share", 1.0))
        rows.append({
            "sector_code": s["sector_code"],
            "sector_name": s.get("sector_name", ""),
            "amount_mw": float(s["amount_mw"]) * share,
        })
    df = compute_effects(pd.DataFrame(rows), coef)
    return {
        "region": region, "table_year": table_year,
        "lines": df.to_dict(orient="records"),
        "totals": summarize(df),
    }


@mcp.tool()
def rio_compute_event(region: str, table_year: int, event_spec: dict,
                      classification: str = "중분류(83부문)") -> dict:
    """Compute the combined effect of an economic event.

    ``event_spec`` keys:
      * ``policy_spending``: list of {sector_code, amount_mw, vendor_in_region_share?}
      * ``n_outsider``: outside-visitor count (drives visitor channels)
      * ``per_capita_won`` (opt), ``event_site_sector`` (opt) — on-site consumption
      * ``purpose_weight`` (opt), ``monthly_weight`` (opt) — ancillary stay
      * ``include_stay`` (opt, default True)

    Returns separate summaries for the policy-expenditure channel (reliable,
    homogeneous) and the participant channel (variable), kept apart per the
    26p17 methodology, plus a combined total.
    """
    coef = _load(region, table_year, classification)
    out: dict[str, Any] = {"region": region, "table_year": table_year}

    policy = event_spec.get("policy_spending") or []
    if policy:
        rows = [{"sector_code": s["sector_code"], "sector_name": s.get("sector_name", ""),
                 "amount_mw": float(s["amount_mw"]) * float(s.get("vendor_in_region_share", 1.0))}
                for s in policy]
        out["policy_expenditure"] = summarize(compute_effects(pd.DataFrame(rows), coef))

    participant_frames = []
    n_outsider = event_spec.get("n_outsider")
    if n_outsider:
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
        "52 도소매, 74 사업지원, 15 인쇄·미디어, 73 장비임대).\n"
        "2. effect_yn: Y if it generates real local production demand, N if it is "
        "a transfer/reserve/non-demand item.\n"
        "3. vendor_in_region_share (0–1): the share procured from in-region vendors.\n"
        "4. A one-line rationale and a confidence (상/중/하).\n\n"
        "Output a table with columns: line_id, 예산항목, 매핑_부문코드, 매핑_부문명, "
        "추정금액_백만원, 효과여부, vendor_in_region_share, 근거, 신뢰도. "
        "Then it can be fed to rio_compute_effects.\n\n"
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
