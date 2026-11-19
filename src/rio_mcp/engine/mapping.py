"""Budget→sector mapping tables: key normalization, effect filter, cross-check.

A mapping table row is one budget line mapped to a sector. Canonical keys
(also the output columns of the ``map_budget_to_sectors`` prompt)::

    line_id, item, detail, sector_code, sector_name, amount_mw,
    effect_yn, vendor_in_region_share, rationale, confidence

The Korean column names of the 26p17 spending-map CSV are accepted as aliases
(:data:`ALIASES`); when a row carries both, the canonical key wins.
``effect_yn`` "N" rows (transfers, reserves, non-demand items) are excluded
from computation; a row without ``effect_yn`` counts as "Y" so plain
``{sector_code, amount_mw}`` spending lines keep working.
"""
from __future__ import annotations

import math
from collections import Counter
from typing import Any

import pandas as pd

from .effects import _norm_code, find_unmatched_sectors

CANONICAL_KEYS = (
    "line_id", "item", "detail", "sector_code", "sector_name", "amount_mw",
    "effect_yn", "vendor_in_region_share", "rationale", "confidence",
)

ALIASES = {
    "매핑_부문코드": "sector_code",
    "부문코드": "sector_code",
    "매핑_부문명": "sector_name",
    "부문명": "sector_name",
    "추정금액_백만원": "amount_mw",
    "효과여부": "effect_yn",
    "vendor_jeju_share": "vendor_in_region_share",
    "역내조달비율": "vendor_in_region_share",
    "예산항목": "item",
    "세부내역": "detail",
    "근거및매핑이유": "rationale",
    "근거": "rationale",
    "신뢰도": "confidence",
}

_YES = {"y", "yes", "예", "o"}
_NO = {"n", "no", "아니오", "아니요", "x"}

# Gap (백만원) between budget_total_mw and the mapped total tolerated as rounding.
BUDGET_TOLERANCE_MW = 0.01


def _blank(v: Any) -> bool:
    if v is None:
        return True
    if isinstance(v, float) and math.isnan(v):
        return True
    return isinstance(v, str) and v.strip() in ("", "nan", "None")


def normalize_effect_yn(v: Any) -> str | None:
    """Map an effect flag to "Y"/"N"; None if blank; ValueError otherwise.

    Accepts surrounding whitespace, either case, and 예/아니오.
    """
    if _blank(v):
        return None
    s = str(v).strip().lower()
    if s in _YES:
        return "Y"
    if s in _NO:
        return "N"
    raise ValueError(f"effect_yn must be Y/N (or 예/아니오), got {v!r}")


def canonicalize(row: dict) -> dict:
    """Rename alias keys to canonical ones (canonical key wins on conflict)."""
    out: dict = {}
    for k, v in row.items():
        key = ALIASES.get(str(k).strip(), k)
        if key in out and key != k:
            continue  # canonical already set
        out[key] = v
    return out


def prepare_spending(spending: list[dict]) -> tuple[pd.DataFrame, list[dict]]:
    """Turn spending/mapping rows into the engine's input frame.

    Returns ``(df, excluded)``: ``df`` has ``sector_code``, ``sector_name``,
    ``amount_mw`` (already × vendor_in_region_share, default 1.0) plus
    ``line_id``/``item`` when any row carries them; ``excluded`` lists the
    effect_yn = N rows (line_id, item, sector_code, amount_mw as given).
    Raises ValueError on a missing sector_code/amount key or a bad effect_yn.
    """
    rows, excluded = [], []
    for i, raw in enumerate(spending):
        r = canonicalize(raw)
        where = f"spending[{i}]" + (f" (line_id {r['line_id']})" if not _blank(r.get("line_id")) else "")
        try:
            flag = normalize_effect_yn(r.get("effect_yn"))
        except ValueError as e:
            raise ValueError(f"{where}: {e}") from None
        if flag == "N":
            amt = r.get("amount_mw")
            excluded.append({k: r.get(k) for k in ("line_id", "item", "sector_code")
                             if not _blank(r.get(k))}
                            | {"amount_mw": None if _blank(amt) else float(amt)})
            continue
        for key in ("sector_code", "amount_mw"):
            if key not in r:
                raise ValueError(f"{where}: missing {key!r} (or its Korean alias)")
        share = r.get("vendor_in_region_share")
        share = 1.0 if _blank(share) else float(share)
        rows.append({
            "line_id": r.get("line_id"), "item": r.get("item"),
            "sector_code": r["sector_code"],
            "sector_name": "" if _blank(r.get("sector_name")) else r["sector_name"],
            "amount_mw": float(r["amount_mw"]) * share,
        })
    cols = ["sector_code", "sector_name", "amount_mw"]
    for opt in ("item", "line_id"):
        if any(not _blank(x[opt]) for x in rows):
            cols.insert(0, opt)
    df = pd.DataFrame(rows, columns=["line_id", "item", "sector_code", "sector_name",
                                     "amount_mw"])[cols]
    return df, excluded


def crosscheck_mapping(mapping: list[dict], coef: pd.DataFrame,
                       budget_total_mw: float | None = None) -> dict:
    """Check a mapping table without computing effects.

    ``issues`` (each: row, line_id, code, message) make ``ok`` false:
    missing_sector_code (Y row), missing_amount / invalid_amount /
    negative_amount, invalid_effect_yn, share_out_of_range / invalid_share,
    duplicate_line_id, budget_mismatch (|budget_total_mw − mapped total| >
    :data:`BUDGET_TOLERANCE_MW`). ``unmatched_sectors`` (Y rows whose code is
    not in ``coef``) also make ``ok`` false. ``notes`` are informational:
    missing_share (1.0 applied), missing_effect_yn (Y assumed).
    """
    issues, notes = [], []
    y_rows = []  # for unmatched check
    tot = {"all": 0.0, "Y": 0.0, "N": 0.0, "Y_in_region": 0.0}
    cnt = Counter()

    def add(bucket, i, r, code, msg):
        bucket.append({"row": i, "line_id": None if _blank(r.get("line_id")) else r.get("line_id"),
                       "code": code, "message": msg})

    ids = [r.get("line_id") for r in map(canonicalize, mapping) if not _blank(r.get("line_id"))]
    dup = {k for k, c in Counter(map(str, ids)).items() if c > 1}

    for i, raw in enumerate(mapping):
        r = canonicalize(raw)
        if not _blank(r.get("line_id")) and str(r["line_id"]) in dup:
            add(issues, i, r, "duplicate_line_id", f"line_id {r['line_id']!r} appears more than once")

        try:
            flag = normalize_effect_yn(r.get("effect_yn"))
        except ValueError as e:
            add(issues, i, r, "invalid_effect_yn", str(e))
            continue
        if flag is None:
            flag = "Y"
            add(notes, i, r, "missing_effect_yn", "effect_yn missing — treated as Y")
        cnt[flag] += 1

        amt_raw = r.get("amount_mw")
        if _blank(amt_raw):
            add(issues, i, r, "missing_amount", "amount_mw missing")
            continue
        try:
            amt = float(amt_raw)
        except (TypeError, ValueError):
            add(issues, i, r, "invalid_amount", f"amount_mw not numeric: {amt_raw!r}")
            continue
        if amt < 0:
            add(issues, i, r, "negative_amount", f"amount_mw negative: {amt:g}")
        tot["all"] += amt
        tot[flag] += amt
        if flag == "N":
            continue

        if _norm_code(r.get("sector_code")) is None and amt != 0:
            add(issues, i, r, "missing_sector_code", "effect_yn Y but sector_code missing")
        share_raw = r.get("vendor_in_region_share")
        share = 1.0
        if _blank(share_raw):
            add(notes, i, r, "missing_share", "vendor_in_region_share missing — 1.0 applied")
        else:
            try:
                share = float(share_raw)
            except (TypeError, ValueError):
                add(issues, i, r, "invalid_share", f"vendor_in_region_share not numeric: {share_raw!r}")
                share = 1.0
            else:
                if not 0.0 <= share <= 1.0:
                    add(issues, i, r, "share_out_of_range",
                        f"vendor_in_region_share {share:g} outside 0–1")
        tot["Y_in_region"] += amt * share
        y_rows.append({"line_id": r.get("line_id"), "sector_code": r.get("sector_code"),
                       "sector_name": r.get("sector_name", ""), "amount_mw": amt})

    unmatched = []
    if y_rows:
        df = pd.DataFrame(y_rows)
        unmatched = find_unmatched_sectors(df, coef)

    n_lines = cnt["Y"] + cnt["N"]
    out: dict[str, Any] = {
        "n_lines": len(mapping),
        "n_effect_y": cnt["Y"], "n_effect_n": cnt["N"],
        "totals": {
            "amount_total_mw": round(tot["all"], 6),
            "amount_y_mw": round(tot["Y"], 6),
            "amount_n_mw": round(tot["N"], 6),
            "amount_y_in_region_mw": round(tot["Y_in_region"], 6),
            "n_share_by_amount": round(tot["N"] / tot["all"], 6) if tot["all"] else None,
            "n_share_by_count": round(cnt["N"] / n_lines, 6) if n_lines else None,
        },
    }
    if budget_total_mw is not None:
        gap = float(budget_total_mw) - tot["all"]
        out["budget_total_mw"] = float(budget_total_mw)
        out["budget_gap_mw"] = round(gap, 6)
        if abs(gap) > BUDGET_TOLERANCE_MW:
            issues.append({"row": None, "line_id": None, "code": "budget_mismatch",
                           "message": f"mapped total {tot['all']:g} ≠ budget_total_mw "
                                      f"{float(budget_total_mw):g} (gap {gap:g}백만원 — "
                                      "missing or extra lines?)"})
    out.update({"unmatched_sectors": unmatched, "issues": issues, "notes": notes,
                "ok": not issues and not unmatched})
    return out
