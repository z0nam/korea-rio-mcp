"""Bank of Korea regional IO table — availability check and extraction.

Reality check (verified May 2026): the BOK *regional* input-output table
(지역산업연관표) is NOT in a clean API. ECOS / data.go.kr expose only the
*national* table. The regional multiregional matrix is published as Excel files
under BOK 간행물 (menuNo=200457), irregularly (2003 → 2005 → 2010 → 2013 →
2015 → 2020, ~5-year cadence). So acquisition is: poll the publication list,
compare the latest published base year against what is cached, and hand the
user the download URL — not an automated pull.
"""
from __future__ import annotations

import re
from pathlib import Path

from ..engine.coefficients import extract_coefficients
from ..engine.regions import get_layout
from ..store import cache

BOK_PUBLICATION_LIST = (
    "https://www.bok.or.kr/portal/singl/newsData/list.do?menuNo=200457"
)
# Base years known to be published (for offline comparison if fetch fails).
KNOWN_PUBLISHED_YEARS = [2003, 2005, 2010, 2013, 2015, 2020]


def parse_published_years(html: str) -> list[int]:
    """Pull candidate '지역산업연관표' base years from the listing HTML."""
    years = set()
    for m in re.finditer(r"(20\d{2})\s*년[^<]{0,30}지역산업연관표", html):
        years.add(int(m.group(1)))
    return sorted(years)


def check_update(cached_year: int | None = None) -> dict:
    """Compare the latest BOK-published base year against the cached one.

    Tries to fetch the live publication list; falls back to the known-years
    table if the network is unavailable. Returns a structured report including
    the manual-download URL (downloads are not automated).
    """
    fetched, source = [], "offline-known-years"
    try:
        import httpx

        resp = httpx.get(BOK_PUBLICATION_LIST, timeout=15.0,
                         headers={"User-Agent": "rio-mcp/0.1"})
        resp.raise_for_status()
        fetched = parse_published_years(resp.text)
        source = "bok-live" if fetched else "bok-live-no-match"
    except Exception as exc:  # network blocked, layout change, etc.
        source = f"offline-fallback ({type(exc).__name__})"

    published = sorted(set(fetched) | set(KNOWN_PUBLISHED_YEARS))
    latest = max(published) if published else None
    newer = bool(latest and cached_year and latest > cached_year)
    return {
        "source": source,
        "published_years": published,
        "latest_published_year": latest,
        "cached_year": cached_year,
        "newer_available": newer,
        "download_url": BOK_PUBLICATION_LIST,
        "note": (
            "Regional IO tables are published as Excel under BOK 간행물 and must "
            "be downloaded manually, then ingested with rio_load_base_table."
        ),
    }


def load_base_table(xlsx_path: str | Path, region: str, table_year: int,
                    classification: str = "중분류(83부문)") -> dict:
    """Extract induced coefficients from a BOK workbook and cache them."""
    layout = get_layout(region, table_year, classification)
    df = extract_coefficients(xlsx_path, layout)
    saved = cache.save(df, region, table_year, classification)
    return {
        "region": region,
        "table_year": table_year,
        "classification": classification,
        "sectors": int(len(df)),
        "cached_path": str(saved),
    }
