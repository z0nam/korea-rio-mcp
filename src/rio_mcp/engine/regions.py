"""Region registry for Bank of Korea regional IO coefficient extraction.

Each entry tells :mod:`rio_mcp.engine.coefficients` how to read induced
coefficients for one region from a BOK 유발계수 workbook:

* ``sheets`` — sheet name per metric (production / value-added / employment)
* ``region_subtotal_row`` — the row holding that region's in-region column sum
  (e.g. Jeju 2020 medium-classification: "제주합" on row 92)
* ``national_total_row`` — the row holding the all-region (전국) column sum;
  out-of-region leakage = national_total − region_subtotal
* data row/column ranges for the sector header

Only Jeju 2020 (medium, 83 sectors) is seeded — it is the validated case
ported from 26p17. Other regions are added once their row indices are
confirmed against the source workbook; the layout differs per publication.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RegionTableLayout:
    """Workbook layout for extracting one region's coefficients."""

    region: str
    table_year: int
    classification: str
    sheets: dict = field(default_factory=dict)
    national_total_row: int = 0
    region_subtotal_row: int = 0
    data_col_start: int = 4
    data_col_end: int = 86
    sector_code_row: int = 6
    sector_name_row: int = 7

    @property
    def key(self) -> str:
        return f"{self.region}:{self.table_year}:{self.classification}"


# Seeded with the validated 26p17 case. The 2020 medium-classification
# coefficient workbook lists the all-region sum on row 91 and the Jeju
# in-region sum ("제주합") on row 92, for each sector column 4..86.
JEJU_2020_MEDIUM = RegionTableLayout(
    region="제주",
    table_year=2020,
    classification="중분류(83부문)",
    sheets={
        "production": "생산유발계수표_중",
        "value_added": "부가가치유발계수표_중",
        "employment": "취업유발계수표_중",
    },
    national_total_row=91,
    region_subtotal_row=92,
    data_col_start=4,
    data_col_end=86,
    sector_code_row=6,
    sector_name_row=7,
)

REGISTRY: dict[str, RegionTableLayout] = {
    JEJU_2020_MEDIUM.key: JEJU_2020_MEDIUM,
}


def get_layout(region: str, table_year: int, classification: str = "중분류(83부문)") -> RegionTableLayout:
    key = f"{region}:{table_year}:{classification}"
    if key not in REGISTRY:
        known = ", ".join(REGISTRY) or "(none)"
        raise KeyError(
            f"No table layout registered for '{key}'. "
            f"Known layouts: {known}. Register one in regions.py with the "
            f"region_subtotal_row / national_total_row indices for that workbook."
        )
    return REGISTRY[key]


def list_regions() -> list[str]:
    return sorted(REGISTRY)
