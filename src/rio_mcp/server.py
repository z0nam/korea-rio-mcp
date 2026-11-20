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


def _ignored_deflator_warning(channel: str | None = None) -> str:
    prefix = f"[{channel}] " if channel else ""
    return (f"{prefix}price_basis=constant라 deflator·price_year를 적용하지 않음 — 현재가 "
            "금액이면 price_basis='nominal'(기본)로 지정할 것")


def _explicit(own: list[float | None],
              fallbacks: list[tuple[float | None, str]]) -> list[tuple[float | None, str | None]]:
    """Per-line (deflator, source): the line's own value, else the first fallback set."""
    out = []
    for d in own:
        if d is not None:
            out.append((d, "line"))
            continue
        out.append(next(((v, s) for v, s in fallbacks if v is not None), (None, None)))
    return out


def _deflate(df: pd.DataFrame, explicit: list[tuple[float | None, str | None]],
             tracker: price.PriceTracker, coef: pd.DataFrame,
             channel: str | None = None) -> tuple[pd.DataFrame, list[float | None], list[str]]:
    """Deflate employment line by line (explicit value, else built-in sector value).

    Returns ``(df, deflators, sources)`` and records the sources in ``tracker``;
    a warning is added to ``tracker.warnings`` when lines are left without one.
    """
    codes = df["sector_code"].tolist() if "sector_code" in df.columns else [None] * len(df)
    amounts = df["amount_mw"].tolist() if "amount_mw" in df.columns else [0.0] * len(df)
    defl, src, used = price.resolve_deflators(codes, amounts, explicit, tracker.price_year,
                                              tracker.unavailable, coef.index)
    df, missing = price.deflate_employment(df, defl)
    tracker.add(src, used, channel)
    if missing:
        tracker.warnings.append(price.missing_builtin_warning(missing, tracker.unavailable, channel))
    return df, defl, src


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
                       "자동 환산하지 않음. 취업유발만 디플레이터(내장 부문별 또는 지정값)로 환산함")
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
_PRICE_DOC = """
    Price basis (#20): ``price_basis="nominal"`` (default) treats amounts as
    current prices of ``price_year`` and converts employment only: each line's
    employment uses amount ÷ deflator (table year = 1.0). Production and
    value-added are not changed — their coefficients are 원/원 ratios, so
    deflating, applying and re-inflating gives the same numbers. Deflator
    precedence per line: the line's ``deflator`` (alias 디플레이터) > channel/
    group deflator (rio_compute_event) > the top-level ``deflator`` > the
    bundled sector output deflator for ``price_year`` (ECOS 405Y007 etc.,
    2020 = 1.0, 2020–2025; 중분류 2020 tables only). Without ``price_year``, or
    with a year outside the bundled table (e.g. 2026 — never extrapolated),
    lines left without a deflator get employment None, and so do the totals (no
    partial sums), with a warning; for amounts in a year after the table's last
    one, pass the last year (2025) as ``price_year`` to approximate — the
    assumption then names that year. ≤ 0 or non-finite deflators raise an
    error. ``assumptions`` starts with ``builtin_deflator`` ("내장 부문별 산출
    디플레이터 적용(ECOS 405Y007 등, 2020=1.0, <price_year>년 값)", plus the
    proxy-grade sectors actually used: 산출측대리 / VA대리 / 총지수대리) when
    any built-in value was applied; one index applied to every line is flagged
    ``single_deflator`` (a simplifying assumption). The response's
    ``price_basis`` is {basis, method (builtin / line / group / channel / top /
    mixed / none / constant), price_year, sources: {source: n_lines}}.
    ``price_basis="constant"`` treats amounts as table-year prices and converts
    nothing — use it only to reproduce earlier analyses.
"""


def _doc(extra: str):
    """Append ``extra`` to a tool's docstring before @mcp.tool() reads it."""
    def deco(fn):
        fn.__doc__ = (fn.__doc__ or "") + extra
        return fn
    return deco


@mcp.tool()
@_doc(_PRICE_DOC)
def rio_compute_effects(region: str, table_year: int, spending: list[dict],
                        classification: str = "중분류(83부문)",
                        strict: bool = False,
                        price_basis: str = price.DEFAULT_PRICE_BASIS,
                        price_year: int | None = None,
                        deflator: float | None = None) -> dict:
    """Compute induced effects for sector-level spending.

    ``spending``: list of mapping-table rows {sector_code, amount_mw,
    vendor_in_region_share?, effect_yn?, line_id?, item?, sector_name?,
    deflator?, ...} — the output of the map_budget_to_sectors prompt can be
    passed as-is (Korean column names such as 매핑_부문코드/추정금액_백만원/
    효과여부/vendor_jeju_share are accepted as aliases). Rows with effect_yn
    "N" (also n/아니오) are left out and listed under ``excluded_lines``; rows
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
    pb = price.check_price_basis(price_basis)
    py = price.check_price_year(price_year)
    top = price.validate_deflator(deflator, where="deflator")
    coef = _load(region, table_year, classification)
    df_in, excluded = prepare_spending(spending)
    own = line_deflators(spending, None)
    assumptions, input_warnings = input_assumptions(spending)
    unmatched = _check(df_in, coef, strict)
    df = compute_effects(df_in, coef)
    tracker = price.PriceTracker(
        pb, py, price.builtin_unavailable_reason(py, table_year, classification))
    price_warnings: list[str] = []
    price_assumptions: list[dict] = []
    if pb == "nominal":
        df, _, _ = _deflate(df, _explicit(own, [(top, "top")]), tracker, coef)
        price_warnings += tracker.warnings
        if top is not None and _no_own_deflators(spending):
            a, w = price.single_deflator_assumption(top)
            price_assumptions.append(a)
            price_warnings.append(w)
    elif top is not None or py is not None or any(d is not None for d in own):
        price_warnings.append(_ignored_deflator_warning())
    first = tracker.builtin_assumption()
    return {
        "region": region, "table_year": table_year,
        "price_basis": tracker.basis(),
        "lines": df.to_dict(orient="records"),
        "totals": _totals(df, pb == "nominal"),
        "excluded_lines": excluded,
        "unmatched_sectors": unmatched,
        "assumptions": [*([first] if first else []), price.price_assumption(pb, table_year, py),
                        *price_assumptions, *assumptions],
        "warnings": input_warnings + price_warnings + unmatched_warnings(unmatched),
    }


@mcp.tool()
@_doc(_PRICE_DOC.replace("    Price basis (#20):",
                         "    Price basis (#20), per channel as in rio_compute_effects:", 1))
def rio_compute_event(region: str, table_year: int, event_spec: dict,
                      classification: str = "중분류(83부문)",
                      strict: bool = False,
                      price_basis: str = price.DEFAULT_PRICE_BASIS,
                      price_year: int | None = None,
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
        per_capita_won?, event_site_sector?, monthly_weight?, deflator?} —
        heterogeneous groups (e.g. domestic vs foreign attendees) each riding
        their own unit-cost profile (see rio_list_profiles). Takes precedence
        over ``n_outsider``.
      * ``n_outsider``: outside-visitor count (legacy single-track channel)
      * ``per_capita_won`` (opt), ``event_site_sector`` (opt) — on-site consumption
      * ``purpose_weight`` (opt), ``monthly_weight`` (opt) — ancillary stay
      * ``include_stay`` (opt, default True)
      * ``policy_deflator`` / ``participant_deflator`` (opt) — channel-wide
        deflators

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
    Deflator precedence — policy channel: line ``deflator`` >
    ``event_spec["policy_deflator"]`` > ``deflator`` > built-in sector value;
    participant channel: visitor group ``deflator`` >
    ``event_spec["participant_deflator"]`` > ``deflator`` > built-in value of
    each spending row's sector. A channel-wide or group deflator spans several
    sectors, so it is flagged as ``single_deflator``. Any line left without a
    deflator makes its channel's employment None, and so ``combined``.
    Visitor unit-cost profiles are never re-priced; under nominal, a profile
    whose meta gives a price/survey year different from table_year is named in
    ``warnings``.
    """
    pb = price.check_price_basis(price_basis)
    nominal = pb == "nominal"
    py = price.check_price_year(price_year)
    top = price.validate_deflator(deflator, where="deflator")
    policy_ch = price.validate_deflator(event_spec.get("policy_deflator"),
                                        where="event_spec.policy_deflator")
    part_ch = price.validate_deflator(event_spec.get("participant_deflator"),
                                      where="event_spec.participant_deflator")
    part_defl = part_ch if part_ch is not None else top
    coef = _load(region, table_year, classification)
    tracker = price.PriceTracker(
        pb, py, price.builtin_unavailable_reason(py, table_year, classification))
    out: dict[str, Any] = {"region": region, "table_year": table_year}
    unmatched: list[dict] = []
    assumptions: list[dict] = []
    input_warnings: list[str] = []
    price_warnings: list[str] = []
    price_assumptions: list[dict] = []
    any_deflator = any(d is not None for d in (top, policy_ch, part_ch)) or py is not None
    out["excluded_lines"] = []

    policy = event_spec.get("policy_spending") or []
    if policy:
        pol_df, out["excluded_lines"] = prepare_spending(policy)
        own = line_deflators(policy, None)
        any_deflator = any_deflator or any(d is not None for d in own)
        assumptions, input_warnings = input_assumptions(policy, channel="policy_expenditure")
        unmatched += _check(pol_df, coef, strict, channel="policy_expenditure")
        pol_eff = compute_effects(pol_df, coef)
        if nominal:
            pol_eff, _, _ = _deflate(pol_eff, _explicit(own, [(policy_ch, "channel"), (top, "top")]),
                                     tracker, coef, "policy_expenditure")
            policy_single = policy_ch if policy_ch is not None else top
            if policy_single is not None and _no_own_deflators(policy):
                a, w = price.single_deflator_assumption(policy_single, "policy_expenditure")
                price_assumptions.append(a)
                tracker.warnings.append(w)
        out["policy_expenditure"] = _totals(pol_eff, nominal)

    participant_frames = []
    visitor_groups = event_spec.get("visitor_groups")
    n_outsider = event_spec.get("n_outsider")
    group_own: dict[str, float | None] = {}
    used_profiles: list[str] = []
    if visitor_groups:
        event_type = event_spec.get("event_type", "festival")
        preset = defaults.EVENT_TYPE_PRESETS.get(event_type, {})
        resolved_by_label: dict[str, float | None] = {}
        for gi, g in enumerate(visitor_groups):
            gd = price.validate_deflator(g.get("deflator"), where=f"visitor_groups[{gi}]")
            label = str(g.get("label", "방문객"))
            resolved = gd if gd is not None else part_defl
            # Deflators are applied per label after the group frames are combined,
            # so groups sharing a label must resolve to the same deflator.
            if nominal and label in resolved_by_label and resolved_by_label[label] != resolved:
                raise ValueError(
                    f"visitor_groups[{gi}]: label {label!r} is shared with another group "
                    f"but its deflator differs ({resolved_by_label[label]!r} vs {resolved!r}); "
                    "give each group a unique label or the same deflator")
            resolved_by_label[label] = resolved
            group_own[label] = gd
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
            fallbacks = [(part_ch, "channel"), (top, "top")]
            if group_own and "그룹" in part_df.columns:
                own = [group_own.get(str(gl)) for gl in part_df["그룹"]]
            else:
                own = [None] * len(part_df)
            explicit = [((d, "group") if d is not None else e)
                        for d, e in zip(own, _explicit([None] * len(own), fallbacks))]
            part_df, defl, src = _deflate(part_df, explicit, tracker, coef, "participant")
            # A channel/group deflator covers participant spending across several
            # sectors, so any explicit value applied there is a single index.
            applied = sorted({d for d, s in zip(defl, src) if s in price.EXPLICIT_SOURCES})
            if applied:
                a, w = price.single_deflator_assumption(applied[0] if len(applied) == 1 else applied,
                                                        "participant")
                price_assumptions.append(a)
                tracker.warnings.append(w)
            tracker.warnings += _profile_year_warnings(used_profiles, table_year)
        if visitor_groups:
            out["participant_by_group"] = {
                str(label): _totals(sub, nominal) for label, sub in part_df.groupby("그룹")
            }
        out["participant"] = _totals(part_df, nominal)
    price_warnings += tracker.warnings
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
    out["price_basis"] = tracker.basis()
    out["unmatched_sectors"] = unmatched
    first = tracker.builtin_assumption()
    out["assumptions"] = [*([first] if first else []), price.price_assumption(pb, table_year, py),
                          *price_assumptions, *assumptions]
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
    without any, a "가격 기준 정보 없음" line is shown. Employment None (e.g.
    nominal without price_year or deflator) renders as N/A.
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
        "tools: nominal (default) = employment deflated with the built-in per-sector "
        "output deflators for price_year, per-line deflators, or a single index flagged "
        "as a simplifying assumption; constant = amounts taken as table-year prices, "
        "for reproducing earlier analyses). If employment is None, do not publish it.\n"
        "Use rio_render_report(preset='interim'|'final') to produce the table."
    )


def main() -> None:
    """Console entry point: run the MCP server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
