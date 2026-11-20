"""Render RIO results into standardized markdown tables.

Two presets, matching the 26p17 reporting standard:

* ``interim`` — production-induction only (중간보고)
* ``final``   — production + value-added + employment together (최종보고 총괄효과)

Input is the six-key summary dict produced by ``engine.effects.summarize``:
production / value_added / employment, each ``_in_region`` / ``_out_region``.
"""
from __future__ import annotations


def _row(label: str, in_v, out_v, unit: str, dec: int = 1) -> str:
    if in_v is None or out_v is None:
        return f"| {label} | N/A | N/A | N/A | N/A |"
    total = in_v + out_v
    share = (in_v / total * 100) if total else 0.0
    fmt = lambda v: f"{v:,.{dec}f}"
    return f"| {label} | {fmt(in_v)} | {fmt(out_v)} | {fmt(total)} | {share:.1f}% |"


def missing_price_message(table_year: int | None = None) -> str:
    year = f"{table_year}년 표, " if table_year else ""
    return (f"가격 기준 정보 없음({year}계산 응답의 assumptions를 넘기지 않음) — 취업유발의 "
            "가격연도·디플레이터를 확인해 명기할 것")


def render_report(results: dict, preset: str = "interim",
                  title: str | None = None, input_budget_mw: float | None = None,
                  assumptions: list[dict] | None = None,
                  table_year: int | None = None) -> str:
    """Render a markdown effect table. ``preset`` in {'interim','final'}.

    ``results`` is the six-key totals dict, or a whole rio_compute_effects /
    rio_compute_event response (its ``totals`` / ``combined`` and
    ``assumptions`` are then used). Assumption messages are listed under the
    table in order — with the built-in deflators the first one is
    "내장 부문별 산출 디플레이터 적용(…, <price_year>년 값)". Without any, a line
    saying the price basis is unknown is shown (the compute tools default to
    nominal + built-in deflators since #20, so constant is no longer assumed).
    """
    if preset not in ("interim", "final"):
        raise ValueError("preset must be 'interim' or 'final'")
    if "production_in_region_mw" not in results:
        if assumptions is None:
            assumptions = results.get("assumptions")
        table_year = table_year or results.get("table_year")
        results = results.get("totals") or results.get("combined") or {}
    if not assumptions:
        assumptions = [{"code": "price_basis_unknown", "message": missing_price_message(table_year)}]

    lines: list[str] = []
    if title:
        lines += [f"### {title}", ""]

    lines += ["| 지표 | 도내 | 도외 | 합계 | 도내비중 |",
              "|---|---:|---:|---:|---:|"]
    lines.append(_row("생산유발효과 (백만원)",
                      results["production_in_region_mw"],
                      results["production_out_region_mw"], "백만원"))
    if preset == "final":
        lines.append(_row("부가가치유발효과 (백만원)",
                          results["value_added_in_region_mw"],
                          results["value_added_out_region_mw"], "백만원"))
        lines.append(_row("취업유발효과 (명)",
                          results["employment_in_region_persons"],
                          results["employment_out_region_persons"], "명", dec=1))

    if input_budget_mw:
        eff = (results["production_in_region_mw"] + results["production_out_region_mw"]) / input_budget_mw
        lines += ["", f"- 투입예산: {input_budget_mw:,.1f} 백만원 / 생산유발 효율: {eff:.2f}배"]

    if preset == "interim":
        lines += ["", "- 부가가치유발·취업유발 효과는 부록에 별도 수록. "
                      "최종보고 총괄효과 표에서는 세 지표를 함께 제시."]
    lines += [""] + [f"- 가정: {a['message']}" for a in assumptions if a.get("message")]
    return "\n".join(lines)
