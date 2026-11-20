"""Bundled per-sector output deflators (#20).

``data/reference/deflators/sector_deflators.csv`` holds one deflator per
중분류 83-sector code and year (2020 = 1.0), with a ``grade`` column telling
whether the value is the sector's own output price index (``산출지수``) or a
proxy (``산출측대리`` / ``VA대리`` / ``총지수대리``). See its SOURCE.md.

The table is national and only valid for coefficient tables whose base year
is :data:`BASE_YEAR` and whose classification is 중분류(83부문). Years outside
the table are not extrapolated.
"""
from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path

from .. import _paths
from .coefficients import normalize_sector_code

BASE_YEAR = 2020
CLASSIFICATION = "중분류(83부문)"
SOURCE_LABEL = "ECOS 405Y007 등"
OUTPUT_GRADE = "산출지수"
PROXY_GRADES = ("산출측대리", "VA대리", "총지수대리")


def deflator_path() -> Path:
    """Bundled CSV path (installed: rio_mcp/data/reference, dev: <repo>/data/reference)."""
    return _paths.reference_dir() / "deflators" / "sector_deflators.csv"


@lru_cache(maxsize=1)
def load_table() -> dict[tuple[str, int], tuple[float, str]]:
    """``{(sector_code, year): (deflator, grade)}`` from the bundled CSV."""
    out: dict[tuple[str, int], tuple[float, str]] = {}
    with deflator_path().open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            code = normalize_sector_code(r["sector_code"])
            out[(code, int(r["year"]))] = (float(r["deflator"]), r["grade"].strip())
    return out


def years() -> tuple[int, ...]:
    """Years covered by the bundled table, ascending."""
    return tuple(sorted({y for _, y in load_table()}))


def lookup(sector_code, year: int) -> tuple[float, str] | None:
    """``(deflator, grade)`` for a sector code and year, or None if absent."""
    code = normalize_sector_code(sector_code)
    if code is None:
        return None
    return load_table().get((code, int(year)))
