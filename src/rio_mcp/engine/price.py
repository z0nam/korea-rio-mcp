"""Price basis of spending amounts vs. the coefficient table's base year (#6, #17).

Coefficients come from a base-year table (e.g. 2020). Production and
value-added coefficients are 원/원 ratios, so deflating the spending to
base-year prices, applying them, and re-inflating the result gives the same
current-price numbers — they need no adjustment. Employment coefficients are
명/10억원 *in base-year prices*: current-price amounts overstate jobs by the
price rise. So:

* ``price_basis="nominal"`` (default) — amounts are current prices of
  ``price_year``; employment only is computed on ``amount / deflator``
  (deflator: base year = 1.0). A line's deflator is, in order: its own
  ``deflator``, a channel/group deflator, the top-level ``deflator``, else the
  bundled sector output deflator for ``price_year`` (:mod:`.deflators`). A
  single index applied to every line is reported as a simplifying assumption.
  A line left without any deflator (no ``price_year``, or a year outside the
  bundled table — never extrapolated) makes the employment result None (no
  partial totals).
* ``price_basis="constant"`` — amounts are taken as base-year prices; nothing
  is converted. Kept to reproduce earlier analyses exactly.
"""
from __future__ import annotations

import math
from collections import Counter
from typing import Any

import pandas as pd

from . import deflators as builtin
from .coefficients import normalize_sector_code

PRICE_BASES = ("constant", "nominal")
DEFAULT_PRICE_BASIS = "nominal"
# Sources of a line's deflator, in precedence order (see resolve_deflators).
EXPLICIT_SOURCES = ("line", "group", "channel", "top")
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


def price_assumption(price_basis: str, table_year: int | None,
                     price_year: int | None = None) -> dict:
    """The ``assumptions`` entry describing the price basis (always reported)."""
    msg = constant_message(table_year) if price_basis == "constant" else NOMINAL_MESSAGE
    a = {"code": "price_basis", "price_basis": price_basis,
         "table_year": table_year, "message": msg}
    if price_basis == "nominal":
        a["price_year"] = price_year
    return a


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


# --------------------------------------------------------------------------- #
# Built-in sector deflators (#20)
# --------------------------------------------------------------------------- #
def check_price_year(v: Any) -> int | None:
    """None if blank; the year as int otherwise; ValueError if not an integer year."""
    if _blank(v):
        return None
    if isinstance(v, bool):
        raise ValueError(f"price_year must be an integer year, got {v!r}")
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise ValueError(f"price_year must be an integer year, got {v!r}") from None
    if not math.isfinite(f) or f != int(f):
        raise ValueError(f"price_year must be an integer year, got {v!r}")
    return int(f)


def builtin_unavailable_reason(price_year: int | None, table_year: int,
                               classification: str) -> str | None:
    """Why the bundled deflators cannot be used here, or None if they can."""
    if str(classification).strip() != builtin.CLASSIFICATION:
        return f"내장 디플레이터는 {builtin.CLASSIFICATION} 전용이라 {classification} 표에는 쓸 수 없음"
    if int(table_year) != builtin.BASE_YEAR:
        return (f"내장 디플레이터는 {builtin.BASE_YEAR}=1.0 기준이라 {table_year}년 표에는 "
                "쓸 수 없음")
    yrs = builtin.years()
    if price_year is None:
        return "price_year(금액의 가격연도)를 지정하지 않음"
    if price_year not in yrs:
        return (f"price_year={price_year}이(가) 내장 디플레이터 범위({yrs[0]}–{yrs[-1]}) 밖이라 "
                "적용하지 않음(외삽하지 않음)")
    return None


def resolve_deflators(codes: list, amounts: list[float],
                      explicit: list[tuple[float | None, str | None]],
                      price_year: int | None, unavailable: str | None,
                      coef_index) -> tuple[list[float | None], list[str], list[tuple[str, str]]]:
    """Per-line deflators: an explicit one if given, else the built-in sector value.

    ``explicit[i]`` is ``(value, source)`` with source in :data:`EXPLICIT_SOURCES`,
    or ``(None, None)``. Returns ``(deflators, sources, used)``: ``sources[i]`` is
    the explicit source, ``"builtin"``, ``"n/a"`` (no effect to deflate — zero
    amount, blank code, or a code absent from the coefficient table, whose effect
    is already 0 and reported as unmatched), or ``"missing"``. ``used`` lists the
    ``(sector_code, grade)`` of lines that took a built-in value.
    """
    defl, src, used = [], [], []
    for code, amt, (val, source) in zip(codes, amounts, explicit):
        sc = normalize_sector_code(code)
        no_effect = float(amt) == 0 or sc is None or sc not in coef_index
        if val is not None:
            defl.append(val)
            src.append("n/a" if no_effect else source)
            continue
        if no_effect:
            defl.append(1.0)
            src.append("n/a")
            continue
        hit = None if unavailable else builtin.lookup(sc, price_year)
        if hit is None:
            defl.append(None)
            src.append("missing")
            continue
        defl.append(hit[0])
        src.append("builtin")
        used.append((sc, hit[1]))
    return defl, src, used


def missing_builtin_warning(n: int, reason: str | None, channel: str | None = None) -> str:
    prefix = f"[{channel}] " if channel else ""
    yrs = builtin.years()
    why = f"{reason}: " if reason else ""
    return (f"{prefix}{why}디플레이터가 없는 줄 {n}개의 취업유발을 산출하지 않음(None, 부분 합계도 "
            "내지 않음) — 금액의 가격연도를 price_year로 주거나 줄별 deflator를 지정할 것. "
            f"내장표({yrs[0]}–{yrs[-1]})에 없는 최신 연도 금액은 최신 연도({yrs[-1]})를 "
            "price_year로 지정해 근사할 수 있으며, 그 경우 가정에 표시됨")


class PriceTracker:
    """Collects deflator sources across channels for the response."""

    def __init__(self, price_basis: str, price_year: int | None, unavailable: str | None):
        self.price_basis = price_basis
        self.price_year = price_year
        self.unavailable = unavailable
        self.sources: Counter = Counter()
        self.by_channel: dict[str, dict[str, int]] = {}
        self.used: dict[tuple[str, str], None] = {}
        self.warnings: list[str] = []

    def add(self, sources: list[str], used: list[tuple[str, str]],
            channel: str | None = None) -> None:
        c = Counter(s for s in sources if s != "n/a")
        self.sources.update(c)
        if channel:
            self.by_channel[channel] = dict(c)
        for u in used:
            self.used.setdefault(u, None)

    def method(self) -> str:
        if self.price_basis == "constant":
            return "constant"
        applied = [s for s in ("builtin", *EXPLICIT_SOURCES) if self.sources.get(s)]
        if not applied:
            return "none"
        return applied[0] if len(applied) == 1 else "mixed"

    def basis(self) -> dict:
        """The response's ``price_basis`` entry."""
        out = {"basis": self.price_basis, "method": self.method(),
               "price_year": self.price_year}
        if self.price_basis == "nominal":
            out["sources"] = dict(self.sources)
            if self.by_channel:
                out["by_channel"] = self.by_channel
        return out

    def builtin_assumption(self) -> dict | None:
        """First assumption line when any built-in value was used."""
        if not self.sources.get("builtin"):
            return None
        proxies = sorted(((c, g) for c, g in self.used if g in builtin.PROXY_GRADES),
                         key=lambda x: x[0])
        msg = (f"내장 부문별 산출 디플레이터 적용({builtin.SOURCE_LABEL}, "
               f"{builtin.BASE_YEAR}=1.0, {self.price_year}년 값)")
        if proxies:
            msg += " — 대리 지수 사용 부문: " + ", ".join(f"{c} {g}" for c, g in proxies)
        return {"code": "builtin_deflator", "message": msg, "price_year": self.price_year,
                "n_lines": self.sources["builtin"],
                "proxy_sectors": [{"sector_code": c, "grade": g} for c, g in proxies]}
