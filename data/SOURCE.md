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
