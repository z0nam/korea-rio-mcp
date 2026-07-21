# Data source & attribution

The files in this directory are **derived works** computed from the Bank of
Korea (한국은행) regional input-output tables (지역산업연관표, 2020 base year),
published at:

https://www.bok.or.kr/portal/singl/newsData/list.do?menuNo=200457

- **Source: Bank of Korea (한국은행).**
- `coefficients/` — induced coefficients (production / value-added / employment,
  in-region vs out-of-region) **extracted and transformed** from the BOK
  workbooks. These are not the original BOK files.
- `reference/` — unit-cost and sector-mapping tables used by the engine.

Use of BOK data is subject to the BOK copyright policy
(https://www.bok.or.kr/portal/main/contents.do?menuNo=200228), which requires
attribution to the Bank of Korea and disclosure of any modification. The MIT
license of this repository covers the software only, not this data.

## Stay-spending profile sources (raw survey docs — not in repo)

Each `reference/profiles/<name>/` bundles small derived unit-cost CSVs; the
original survey documents are large and kept out of the repo (like the BOK
coefficient workbooks). Canonical copies live in the consuming project's
reference library:

- **제주 방문관광객 실태조사 (2025)** — `jeju_*_business`, `jeju_*_visitor`
  profiles. Source: 제주특별자치도·제주관광공사(2026), 통계청 승인 제218007호.
  PDF (분석편/통계편) at `20260704_이슈브리프_제주포럼경제효과/99.Reference/외부문헌/02_제주도_제주관광공사/`.
  **Verified against source 2026-07-21** — see each profile's SOURCE.md.
- **2016 MICE 산업 경제적 파급효과 분석** — `jeju_*_mice_kto2016` profiles.
  Source: 한국관광공사(2018), 표 부록-3 제주 Convention. PDF at the same
  project's `99.Reference/외부문헌/01_한국관광공사/`.
- **외래관광객조사 (2025)** — 국가승인 외래객 조사 원자료(zip) at the same
  project's `99.Reference/외부문헌/03_한국문화관광연구원/` (전국 단위 교차검증용).
