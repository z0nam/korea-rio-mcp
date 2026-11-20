"""Bundled sector output-deflator table (#20): offline reproducibility + shape."""
import csv
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "data" / "reference" / "deflators" / "sector_deflators.csv"


@pytest.fixture(scope="module")
def build():
    spec = importlib.util.spec_from_file_location(
        "build_deflators", ROOT / "scripts" / "build_deflators.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def rows():
    with CSV_PATH.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def test_committed_csv_reproduces_from_raw_cache(build):
    assert build.render_csv(build.build_rows()) == CSV_PATH.read_text(encoding="utf-8")


def test_columns(build, rows):
    assert list(rows[0]) == build.COLUMNS


def test_all_83_sectors_all_years(build, rows):
    codes = {r["sector_code"] for r in rows}
    assert codes == {f"{i:02d}" for i in range(1, 84)}
    assert len(rows) == 83 * len(build.YEARS)
    for code in codes:
        assert sorted(int(r["year"]) for r in rows if r["sector_code"] == code) == build.YEARS


def test_base_year_is_one(rows):
    base = [r for r in rows if r["year"] == "2020"]
    assert len(base) == 83
    assert all(float(r["deflator"]) == 1.0 for r in base)


def test_deflators_positive(rows):
    assert all(float(r["deflator"]) > 0 for r in rows)


def test_grade_values(build, rows):
    assert {r["grade"] for r in rows} == set(build.GRADES)
    per_sector = {r["sector_code"]: r["grade"] for r in rows}
    counts = {g: sum(1 for v in per_sector.values() if v == g) for g in build.GRADES}
    assert counts == {"산출지수": 76, "산출측대리": 2, "VA대리": 4, "총지수대리": 1}
    assert {c for c, g in per_sector.items() if g == "VA대리"} == {"52", "75", "77", "78"}


def test_raw_cache_has_no_api_key(build):
    for p in build.RAW_DIR.glob("*.json"):
        text = p.read_text(encoding="utf-8")
        assert "ecos.bok.or.kr/api" not in text and "sample" not in text
