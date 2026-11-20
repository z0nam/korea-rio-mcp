"""Build the sector output-deflator table (중분류 83부문 × 2020–2025, 2020=1.0).

Two steps, kept separate so the committed CSV is reproducible offline:

1. ``--fetch``: download the annual series for every source item from the Bank
   of Korea ECOS API and store each raw API response unchanged (pretty-printed)
   under ``data/reference/deflators/raw/``. The API key is read only from the
   ``ECOS_API_KEY`` environment variable; without it the public ECOS ``sample``
   key is used (fine here: each request returns 6 annual rows, below the
   sample key's 10-row cap; a truncated response is rejected). The key is part
   of the request URL, so the URL is never printed or logged.
2. default: rebuild ``sector_deflators.csv`` from the cached raw responses.
   The only numeric operation is ``round(value / value_2020, 6)``.

Usage:
    python scripts/build_deflators.py --fetch   # refresh raw/ from ECOS
    python scripts/build_deflators.py           # raw/ -> sector_deflators.csv
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "reference" / "deflators"
RAW_DIR = OUT_DIR / "raw"
OUT_CSV = OUT_DIR / "sector_deflators.csv"
NAMES_CSV = ROOT / "src" / "rio_mcp" / "data" / "coefficients" / "induce_coef_제주_2020_중분류.csv"

YEARS = list(range(2020, 2026))
BASE_YEAR = 2020
COLUMNS = ["sector_code", "sector_name", "year", "deflator",
           "source_table", "source_item", "grade"]

OUTPUT = "산출지수"        # ECOS 405Y007 총산출물가지수, matching sector
OUTPUT_PROXY = "산출측대리"  # output-side proxy (construction investment deflator)
VA_PROXY = "VA대리"         # value-added (GDP by activity) deflator
TOTAL_PROXY = "총지수대리"   # 405Y007 all-sector total index
GRADES = (OUTPUT, OUTPUT_PROXY, VA_PROXY, TOTAL_PROXY)


def _o(item: str) -> tuple[str, str, str]:
    return ("405Y007", item, OUTPUT)


# 83 sector code -> (ECOS table, item code, grade)
MAPPING: dict[str, tuple[str, str, str]] = {
    **{f"{i:02d}": _o("1A") for i in range(1, 6)},          # 농림수산
    **{f"{i:02d}": _o("2A") for i in (6, 7)},               # 광산품
    **{f"{i:02d}": _o("301A") for i in (8, 9, 10)},         # 음식료품
    **{f"{i:02d}": _o("302A") for i in (11, 12)},           # 섬유·가죽
    **{f"{i:02d}": _o("303A") for i in (13, 14, 15)},       # 목재·종이·인쇄
    "16": _o("304A"),                                        # 석탄·석유
    **{f"{i:02d}": _o("305A") for i in range(17, 25)},      # 화학
    **{f"{i:02d}": _o("306A") for i in (25, 26)},           # 비금속광물
    **{f"{i:02d}": _o("307A") for i in (27, 28, 29)},       # 1차금속
    "30": _o("308A"),                                        # 금속가공
    **{f"{i:02d}": _o("309A") for i in range(31, 37)},      # 전자·광학
    "37": _o("310A"),                                        # 전기장비
    **{f"{i:02d}": _o("311A") for i in (38, 39)},           # 기계
    **{f"{i:02d}": _o("312A") for i in (40, 41, 42)},       # 운송장비
    **{f"{i:02d}": _o("313A") for i in (43, 44)},           # 기타제조
    **{f"{i:02d}": _o("401A") for i in (45, 46)},           # 전력·가스·증기
    **{f"{i:02d}": _o("402A") for i in (47, 48, 49)},       # 수도·폐기물
    "50": ("200Y112", "1020111", OUTPUT_PROXY),              # 건설투자 디플레이터
    "51": ("200Y112", "1020111", OUTPUT_PROXY),
    "52": ("200Y111", "1106", VA_PROXY),                     # 도소매및숙박음식업 VA
    **{f"{i:02d}": _o("501A") for i in range(53, 58)},      # 운송
    "58": _o("502A"),                                        # 음식점·숙박
    **{f"{i:02d}": _o("503A") for i in range(59, 65)},      # 정보통신·방송
    **{f"{i:02d}": _o("504A") for i in (65, 66, 67)},       # 금융·보험
    **{f"{i:02d}": _o("505A") for i in (68, 69)},           # 부동산
    **{f"{i:02d}": _o("506A") for i in (70, 71, 72)},       # 전문·과학·기술
    **{f"{i:02d}": _o("507A") for i in (73, 74)},           # 사업지원
    "75": ("200Y111", "1110", VA_PROXY),                     # 공공행정 VA
    "76": _o("508A"),                                        # 교육
    "77": ("200Y111", "1112", VA_PROXY),                     # 보건·사회복지 VA
    "78": ("200Y111", "1112", VA_PROXY),
    **{f"{i:02d}": _o("509A") for i in (79, 80)},           # 예술·스포츠·여가
    **{f"{i:02d}": _o("510A") for i in (81, 82)},           # 기타서비스
    "83": ("405Y007", "*A", TOTAL_PROXY),                    # 기타 → 총지수
}


def raw_path(table: str, item: str) -> Path:
    return RAW_DIR / f"{table}_{item.replace('*', 'TOTAL')}.json"


def source_items() -> list[tuple[str, str]]:
    return sorted({(t, i) for t, i, _ in MAPPING.values()})


def fetch(key: str) -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    for table, item in source_items():
        url = "/".join([
            "https://ecos.bok.or.kr/api/StatisticSearch",
            urllib.parse.quote(key, safe=""), "json", "kr", "1", "10",
            table, "A", str(YEARS[0]), str(YEARS[-1]),
            urllib.parse.quote(item, safe=""),
        ])
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                body = json.load(r)
        except Exception as e:  # never chain: the exception may carry the URL
            raise SystemExit(f"ECOS 요청 실패 {table}:{item} ({type(e).__name__})") from None
        rows = body.get("StatisticSearch", {}).get("row")
        if not rows:
            raise SystemExit(f"ECOS 응답에 행이 없음 {table}:{item}: {body.get('RESULT')}")
        total = body["StatisticSearch"].get("list_total_count")
        if total != len(rows) or len(rows) != len(YEARS):
            raise SystemExit(f"{table}:{item} 행 수 {len(rows)}/{total} (기대 {len(YEARS)})")
        raw_path(table, item).write_text(
            json.dumps(body, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
            encoding="utf-8")
        print(f"fetched {table}:{item} {rows[0]['ITEM_NAME1']}")


def load_series(table: str, item: str, raw_dir: Path = RAW_DIR) -> tuple[str, dict[int, float]]:
    p = raw_dir / raw_path(table, item).name
    body = json.loads(p.read_text(encoding="utf-8"))
    rows = body["StatisticSearch"]["row"]
    series = {}
    for r in rows:
        assert r["STAT_CODE"] == table and r["ITEM_CODE1"] == item, p
        series[int(r["TIME"])] = float(r["DATA_VALUE"])
    missing = [y for y in YEARS if y not in series]
    if missing:
        raise ValueError(f"{table}:{item} 연도 누락 {missing}")
    return rows[0]["ITEM_NAME1"], series


def sector_names(path: Path = NAMES_CSV) -> dict[str, str]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return {r["sector_code"]: r["sector_name"] for r in csv.DictReader(f)}


def build_rows(raw_dir: Path = RAW_DIR) -> list[dict]:
    names = sector_names()
    if set(names) != set(MAPPING):
        raise ValueError(f"부문 불일치: {sorted(set(names) ^ set(MAPPING))}")
    cache = {ti: load_series(*ti, raw_dir=raw_dir)[1] for ti in source_items()}
    rows = []
    for code in sorted(MAPPING):
        table, item, grade = MAPPING[code]
        s = cache[(table, item)]
        for y in YEARS:
            rows.append({
                "sector_code": code, "sector_name": names[code], "year": y,
                "deflator": f"{round(s[y] / s[BASE_YEAR], 6):.6f}",
                "source_table": table, "source_item": item, "grade": grade,
            })
    return rows


def render_csv(rows: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=COLUMNS, lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--fetch", action="store_true",
                    help="refresh raw/ from ECOS before building")
    args = ap.parse_args(argv)
    if args.fetch:
        fetch(os.environ.get("ECOS_API_KEY") or "sample")
    OUT_CSV.write_text(render_csv(build_rows()), encoding="utf-8")
    print(f"wrote {OUT_CSV.relative_to(ROOT)} ({len(MAPPING)} sectors × {len(YEARS)} years)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
