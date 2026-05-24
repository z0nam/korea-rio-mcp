"""Resolve and persist coefficient tables, versioned by region/year/classification.

Lookup order for a requested table: writable cache dir (populated by
``rio_load_base_table``) first, then the bundled ``data/coefficients`` shipped
with the package (seeded with Jeju 2020). Filenames encode the version key.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .. import _paths


def _filename(region: str, table_year: int, classification: str) -> str:
    # classification like "중분류(83부문)" -> compact token
    cls = classification.split("(")[0].strip() or classification
    return f"induce_coef_{region}_{table_year}_{cls}.csv"


def _bundled_dir() -> Path:
    pkg = Path(__file__).resolve().parents[1]
    for cand in (pkg / "data" / "coefficients", pkg.parents[1] / "data" / "coefficients"):
        if cand.exists():
            return cand
    return pkg / "data" / "coefficients"


def resolve_path(region: str, table_year: int, classification: str = "중분류(83부문)") -> Path:
    """Return the path to a cached/bundled coefficient table, or raise."""
    name = _filename(region, table_year, classification)
    for d in (_paths.cache_dir(), _bundled_dir()):
        p = d / name
        if p.exists():
            return p
    raise FileNotFoundError(
        f"No coefficient table for {region} {table_year} {classification}. "
        f"Run rio_load_base_table to extract one from a BOK workbook."
    )


def save(df: pd.DataFrame, region: str, table_year: int, classification: str = "중분류(83부문)") -> Path:
    """Persist an extracted coefficient table to the writable cache."""
    path = _paths.cache_dir() / _filename(region, table_year, classification)
    df.to_csv(path, index=False, encoding="utf-8-sig")
    return path


def list_available() -> list[dict]:
    """Enumerate coefficient tables from both cache and bundled dirs."""
    seen, out = set(), []
    for source, d in (("cache", _paths.cache_dir()), ("bundled", _bundled_dir())):
        if not d.exists():
            continue
        for p in sorted(d.glob("induce_coef_*.csv")):
            if p.name in seen:
                continue
            seen.add(p.name)
            out.append({"file": p.name, "source": source, "path": str(p)})
    return out
