"""Generate per-region 2020 중분류 coefficient CSVs for all 17 regions.

Reads the KOSIS regional 유발계수 workbooks (생산유발 + 부가가치유발) once each,
extracts every region's in/out-region coefficients by row-block summation, and
writes one cache CSV per region. Employment is not in the KOSIS regional set;
for 제주 it is merged from the existing 26p17 table, others left NaN pending a
regional employment source.

Usage:
    python scripts/build_coefficients_2020.py \
        --prod <생산유발.xlsx> --va <부가가치유발.xlsx> \
        [--jeju-employment <induce_coefficients_jeju_medium.csv>] \
        --out src/rio_mcp/data/coefficients
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from rio_mcp.engine.multiregional import (  # noqa: E402
    REGIONS_17, _load_grid, _index_blocks,
)

YEAR = 2020
CLASSIFICATION = "중분류(83부문)"


def extract_all_regions(grid, metric: str) -> dict[str, pd.DataFrame]:
    row_blocks, col_blocks, nat_idx, sector_meta = _index_blocks(grid)
    out = {}
    for region in REGIONS_17:
        rows_r = row_blocks[region]
        rec = []
        for c in col_blocks[region]:
            code, name = sector_meta[c]
            in_region = sum(grid[i][c] for i in rows_r
                            if c < len(grid[i]) and isinstance(grid[i][c], (int, float)))
            nat = grid[nat_idx][c] if c < len(grid[nat_idx]) and isinstance(grid[nat_idx][c], (int, float)) else 0.0
            rec.append({"sector_code": code, "sector_name": name,
                        f"multiplier_{metric}_in_region": in_region,
                        f"multiplier_{metric}_out_region": max(0.0, nat - in_region)})
        out[region] = pd.DataFrame(rec).sort_values("sector_code").reset_index(drop=True)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prod", required=True)
    ap.add_argument("--va", required=True)
    ap.add_argument("--jeju-employment", default=None)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)

    print("loading production workbook ...")
    prod = extract_all_regions(_load_grid(args.prod), "production")
    print("loading value-added workbook ...")
    va = extract_all_regions(_load_grid(args.va), "value_added")

    emp = None
    if args.jeju_employment:
        e = pd.read_csv(args.jeju_employment, dtype={"sector_code": str})
        e["sector_code"] = e["sector_code"].str.zfill(2)
        emp = e[["sector_code", "multiplier_employment_jeju", "multiplier_employment_outside"]].rename(columns={
            "multiplier_employment_jeju": "multiplier_employment_in_region",
            "multiplier_employment_outside": "multiplier_employment_out_region"})

    for region in REGIONS_17:
        df = prod[region].merge(va[region].drop(columns=["sector_name"]), on="sector_code")
        if region == "제주" and emp is not None:
            df = df.merge(emp, on="sector_code", how="left")
        for scope in ("in_region", "out_region"):
            col = f"multiplier_employment_{scope}"
            if col not in df.columns:
                df[col] = pd.NA
        df["unit_production"] = "원/원"
        df["unit_value_added"] = "원/원"
        df["unit_employment"] = "명/10억원"
        df["region"] = region
        df["table_year"] = YEAR
        df["classification"] = CLASSIFICATION
        cls = CLASSIFICATION.split("(")[0]
        path = outdir / f"induce_coef_{region}_{YEAR}_{cls}.csv"
        df.to_csv(path, index=False, encoding="utf-8-sig")
        emp_state = "with-employment" if region == "제주" and emp is not None else "no-employment"
        print(f"  {region}: {len(df)} sectors -> {path.name} ({emp_state})")


if __name__ == "__main__":
    main()
