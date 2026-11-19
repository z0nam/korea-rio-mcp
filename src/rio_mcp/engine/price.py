"""Price basis of spending amounts vs. the coefficient table's base year (#6, #17).

Coefficients come from a base-year table (e.g. 2020). Production and
value-added coefficients are 원/원 ratios, so deflating the spending to
base-year prices, applying them, and re-inflating the result gives the same
current-price numbers — they need no adjustment. Employment coefficients are
명/10억원 *in base-year prices*: current-price amounts overstate jobs by the
price rise. So:

* ``price_basis="constant"`` (default) — amounts are taken as base-year prices;
  nothing is converted and an assumption is always reported.
* ``price_basis="nominal"`` — amounts are current prices; employment only is
  computed on ``amount / deflator`` (deflator: base year = 1.0; recommended the
  line's sector output deflator, rebased to the table year — the standard
  practice abroad; a single index such as the GDP deflator applied to every
  line is reported as a simplifying assumption). A line without a deflator makes the
  employment result None (no partial totals) — no default deflator is assumed.
"""
from __future__ import annotations

import math
from typing import Any

import pandas as pd

PRICE_BASES = ("constant", "nominal")
EMPLOYMENT_COLS = ("employment_in_region_persons", "employment_out_region_persons")

NOMINAL_MESSAGE = (
    "취업유발만 줄별 디플레이터로 표 기준연도 가격 환산. 권장: 해당 부문의 산출 디플레이터"
    "(해외 표준 관행). GDP 디플레이터 등 단일 지수를 전 줄에 쓰면 단순화 가정으로 명기"
)
SINGLE_DEFLATOR_MESSAGE = "단일 디플레이터 적용 — 단순화 가정"


def single_deflator_assumption(deflator: float | list[float],
                               channel: str | None = None) -> tuple[dict, str]:
    """Assumption + warning when one deflator covers every line (no per-line values).

    ``deflator`` may be a list when participant groups each carry one index.
    """
    a = {"code": "single_deflator", "message": SINGLE_DEFLATOR_MESSAGE, "deflator": deflator}
    if channel:
        a["channel"] = channel
    prefix = f"[{channel}] " if channel else ""
    shown = (", ".join(f"{d:g}" for d in deflator) if isinstance(deflator, list)
             else f"{deflator:g}")
    w = (f"{prefix}{SINGLE_DEFLATOR_MESSAGE}: 줄별(부문별) 디플레이터 없이 {shown}를 여러 부문에 "
         "일괄 적용함 — 부문별 산출 디플레이터를 줄별 deflator로 넣는 것을 권장")
    return a, w


def constant_message(table_year: int | None) -> str:
    year = f"{table_year}년" if table_year else "표 기준연도"
    return (f"금액을 {year}(표 기준연도) 불변가격으로 간주함 — 현재가 금액이면 "
            "취업유발이 물가 상승분만큼 과대 추정될 수 있음")


def check_price_basis(price_basis: str) -> str:
    pb = str(price_basis).strip().lower()
    if pb not in PRICE_BASES:
        raise ValueError(f"price_basis must be one of {PRICE_BASES}, got {price_basis!r}")
    return pb


def price_assumption(price_basis: str, table_year: int | None) -> dict:
    """The ``assumptions`` entry describing the price basis (always reported)."""
    msg = constant_message(table_year) if price_basis == "constant" else NOMINAL_MESSAGE
    return {"code": "price_basis", "price_basis": price_basis,
            "table_year": table_year, "message": msg}


def _blank(v: Any) -> bool:
    if v is None:
        return True
    if isinstance(v, float) and math.isnan(v):
        return True
    return isinstance(v, str) and v.strip() in ("", "nan", "None")


def validate_deflator(v: Any, where: str = "deflator") -> float | None:
    """None if blank; float > 0 and finite otherwise; ValueError if invalid."""
    if _blank(v):
        return None
    try:
        d = float(v)
    except (TypeError, ValueError):
        raise ValueError(f"{where}: deflator must be a number, got {v!r}") from None
    if not math.isfinite(d) or d <= 0:
        raise ValueError(f"{where}: deflator must be a finite number > 0 "
                         f"(base year = 1.0), got {v!r}")
    return d


def deflate_employment(df: pd.DataFrame, deflators: list[float | None]) -> tuple[pd.DataFrame, int]:
    """Divide each line's employment by its deflator.

    ``deflators`` is aligned with ``df`` rows. Lines with a non-zero amount and
    no deflator get employment None; returns ``(df, n_missing)``. Callers must
    report totals employment as None when ``n_missing`` > 0.
    """
    if len(deflators) != len(df):
        raise ValueError("deflators must align with the computed lines")
    df = df.copy()
    missing = 0
    for col in EMPLOYMENT_COLS:
        if col in df.columns:
            df[col] = df[col].astype(object)
    for pos, d in enumerate(deflators):
        amt = float(df["amount_mw"].iloc[pos]) if "amount_mw" in df.columns else 0.0
        if d is None:
            if amt != 0:
                missing += 1
                for col in EMPLOYMENT_COLS:
                    if col in df.columns:
                        df.iat[pos, df.columns.get_loc(col)] = None
            continue
        for col in EMPLOYMENT_COLS:
            if col in df.columns:
                v = df.iat[pos, df.columns.get_loc(col)]
                if v is not None and not (isinstance(v, float) and math.isnan(v)):
                    df.iat[pos, df.columns.get_loc(col)] = float(v) / d
    if missing == 0:
        for col in EMPLOYMENT_COLS:
            if col in df.columns:
                df[col] = df[col].astype(float)
    return df, missing


def null_employment(totals: dict) -> dict:
    """Totals with employment set to None (not computed)."""
    return {**totals, **{c: None for c in EMPLOYMENT_COLS if c in totals}}
