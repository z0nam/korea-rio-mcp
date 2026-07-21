"""Consumption profiles: visitor-type unit-cost bundles for stay spending.

A profile is a directory under ``data/reference/profiles/<name>/`` holding:

* ``unit_cost.csv`` — ``item`` + one numeric column per period. Periods are
  arbitrary column names: monthly (``jul``..``oct``) for seasonal tables, or a
  single ``annual`` column for surveys published as annual averages.
* ``industry_mapping.csv`` — ``stay_item`` → BOK sector code (``매핑_부문코드``;
  code 0 = spending occurs out-of-region, zero in-region effect).
* ``meta.json`` — ``label`` / ``period_columns`` / ``default_weight`` / ``source``.
  ``default_weight`` (period → weight, summing to 1) is used when the caller
  passes no explicit ``monthly_weight``.
* ``SOURCE.md`` — human-readable provenance notes.

Profiles keep the deterministic engine region/visitor-type agnostic: a new
visitor track (e.g. foreign MICE attendees) is a data drop, not a code change.
"""
from __future__ import annotations

import json
from pathlib import Path

from .. import _paths

DEFAULT_PROFILE = "jeju_domestic_leisure"

# Pre-profile flat filenames, kept resolvable so cached/old layouts still work.
_LEGACY_FLAT = {
    "jeju_domestic_leisure": ("outsider_stay_spending_unit_cost.csv",
                              "outsider_stay_spending_industry_mapping.csv"),
}


def profiles_root() -> Path:
    return _paths.reference_dir() / "profiles"


def resolve(name: str) -> dict:
    """Return ``{"unit_cost_path", "industry_map_path", "meta"}`` for a profile."""
    d = profiles_root() / name
    if (d / "unit_cost.csv").exists():
        meta_path = d / "meta.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
        return {"unit_cost_path": d / "unit_cost.csv",
                "industry_map_path": d / "industry_mapping.csv",
                "meta": meta}
    if name in _LEGACY_FLAT:
        unit, smap = _LEGACY_FLAT[name]
        ref = _paths.reference_dir()
        if (ref / unit).exists():
            return {"unit_cost_path": ref / unit, "industry_map_path": ref / smap, "meta": {}}
    available = ", ".join(sorted(p["name"] for p in list_profiles())) or "(none)"
    raise FileNotFoundError(f"Unknown stay-spending profile {name!r}. Available: {available}")


def list_profiles() -> list[dict]:
    """Enumerate bundled profiles with their meta labels/sources."""
    root = profiles_root()
    out = []
    if not root.exists():
        return out
    for d in sorted(root.iterdir()):
        if not (d / "unit_cost.csv").exists():
            continue
        meta_path = d / "meta.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
        out.append({"name": d.name, **{k: meta.get(k) for k in ("label", "source", "period_columns")}})
    return out
