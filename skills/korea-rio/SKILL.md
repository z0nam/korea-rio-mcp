---
name: korea-rio
description: >-
  Analyze regional economic impacts (production, value-added, and employment induction)
  using the Bank of Korea Regional Input-Output (RIO) tables via the korea-rio MCP server.
  Use when calculating the economic effects of policy expenditures, regional festivals,
  or MICE/forum events, and generating standardized markdown effect reports.
---

# Regional Input-Output Economic Impact Analysis (`korea-rio`)

Computes regional economic impact effects (production, value-added, employment / job induction) split into in-region and out-of-region channels using Bank of Korea (BOK) Regional Input-Output tables.

## When to Use

- Evaluating the economic impact of regional policy spending, public investments, or subsidy projects.
- Analyzing economic ripple effects for cultural events, festivals, or international forums/MICE (e.g. separating direct policy spending from visitor consumption).
- Generating standardized reporting tables for interim or final research deliverables.

## Core Analysis Workflow

```
1. Check Tables/Profiles ──▶ 2. Map Spending ──▶ 2b. Price Basis ──▶ 3. Compute Effects ──▶ 4. Render Report ──▶ 5. Verify
   (rio_list_coefficients)     (Budget to RIO      (price_basis /      (rio_compute_effects    (rio_render_report      (checklist
   (rio_list_profiles)          Sectors)            deflator)           or rio_compute_event)   interim / final)        below)
```

### Step 1. Inspect Available Coefficient Tables & Profiles
- `rio_list_coefficients`: List available coefficient tables (bundled: Jeju 2020 83-sector intermediate classification).
- `rio_list_profiles`: Inspect built-in per-capita spending profiles for event attendees (e.g., `jeju_domestic_leisure` for festival visitors, `jeju_domestic_visitor`/`jeju_foreign_visitor` for MICE/forum participants).
- `rio_list_sectors(region, table_year)`: List valid sector codes/names of a table; use it to check `sector_code` values in Step 2.
- (Optional) `rio_check_base_table_update`: Check if BOK has published newer regional IO tables.

### Step 2. Map Expenditures to Industrial Sectors
- Translate budget lines or consumption spending into Regional IO sector codes (e.g. 83-sector classification).
- Specify:
  - `sector_code` (and optional `sector_name`)
  - `amount_mw` (amount in million KRW, 백만 원)
  - `vendor_in_region_share` (fraction captured by regional vendors, default `1.0`)
  - `effect_yn` (`Y`/`N`; N = transfer/reserve/non-demand item — kept in the table, excluded from totals)
  - plus `line_id`, `item`, `detail`, `rationale`, `confidence` (the `map_budget_to_sectors` prompt outputs exactly these keys; Korean column names such as `매핑_부문코드`/`추정금액_백만원`/`효과여부`/`vendor_jeju_share` are accepted as aliases)
- Run `rio_crosscheck_mapping(region, table_year, mapping, budget_total_mw?)` and fix every `issues` entry and `unmatched_sectors` before computing. `notes` (e.g. missing share → 1.0) are informational.

### Step 2b. Price Basis Check
The coefficient tables are base-year (e.g. 2020) tables. Employment coefficients are 명/10억원 **in base-year prices**, so current-price amounts overstate jobs by the price rise since the base year. Production and value-added are 원/원 ratios and need no adjustment.
1. **Find the price year of every amount** (budget year, survey year of unit costs).
2. **Amounts already in table-year prices** (or the price year equals `table_year`) → `price_basis="constant"` (default). The response always carries the assumption "금액을 <table_year>년(표 기준연도) 불변가격으로 간주함 …".
3. **Current-price amounts** (the usual case for later budgets) → `price_basis="nominal"` and give deflators with the table year = 1.0. Only employment is converted (amount ÷ deflator).
   - **Preferred: a sector deflator per line** (standard practice abroad), passed as each line's `deflator` key (alias `디플레이터`). Sources, rebased so that `table_year` = 1.0:
     - 한국은행 산업연관표 **연장표**: the sector's output at current prices ÷ output at constant (table-year) prices, or
     - the **생산자물가지수(PPI)** item that corresponds to the sector: `PPI(price year) ÷ PPI(table_year)`.
   - **Only if sector deflators cannot be obtained**: one index for all lines — the **GDP deflator** from 한국은행 ECOS, `GDP deflator(price year) ÷ GDP deflator(table_year)` (e.g. 117 with 2020 = 100 → `1.17`) — passed once as the top-level `deflator` (or `event_spec.policy_deflator` / `participant_deflator`, or a visitor group's `deflator`). The response then adds a `single_deflator` assumption and warning ("단일 디플레이터 적용 — 단순화 가정"); state it in the report. The participant channel always takes one index per channel/group, so it is always flagged.
4. **Price year unknown, or no deflator available** → run `nominal` without a deflator: employment comes back as `None` (N/A in the report) with a warning. **Do not publish employment induction** in that case; report production and value-added only and say why.
5. Visitor unit-cost profiles are never re-priced automatically; under `nominal`, a profile whose survey year differs from `table_year` is named in `warnings`.

### Step 3. Compute Effects
Choose between direct spending calculation and combined event calculation:

- **Sector-level spending**:
  - Use `rio_compute_effects` with `region`, `table_year`, and `spending` list (pass the checked mapping rows unchanged; `effect_yn` N rows come back under `excluded_lines`).
- Both tools return `unmatched_sectors` and `warnings`: a non-zero amount whose `sector_code` is not in the table is counted as 0 effect. Always check these and fix the code (or pass `strict=true` to fail instead). A null `sector_code` (e.g. air/sea leakage in stay profiles) is an intended zero and is not reported.
- Both tools also return `assumptions` (a list of `{code, message, ...}` for defaults the tool applied — e.g. `default_vendor_share` with `n_lines` when rows omit `vendor_in_region_share`: "역내 조달 비율을 지정하지 않아 100%로 가정함") and unit-check `warnings` for any single line above 10조 원 (10,000,000 백만원) or below 1 백만원. State every assumption in the report, and fix or explain every unit warning.
- **Combined event (policy + participants)**:
  - Use `rio_compute_event` with `event_spec`.
  - Keeps policy expenditure channel (homogeneous, reliable) and participant channel (variable visitor spending) distinct to prevent double-counting and bias.
  - Supports `event_type`: `"festival"` or `"forum_mice"`.
  - Supports `visitor_groups` (multi-group attendance) or `n_outsider` (single-track outside visitors).

### Step 4. Render Standardized Report
- Use `rio_render_report`:
  - `preset='interim'`: Focuses on production-induction effects (중간보고용).
  - `preset='final'`: Full breakdown including production, value-added, and employment effects (최종보고용).
  - Pass the totals dictionary from Step 3 and optional `title` or `input_budget_mw`.

### Step 5. Verify the Results (검산 체크리스트)
Go through every item before reporting numbers:
1. **Amount unit** — every `amount_mw` is in 백만 원 (million KRW). No unit warnings remain, or each one is explained. Sum of the mapping equals the budget total (`rio_crosscheck_mapping` with `budget_total_mw`).
2. **Sector codes** — every code was checked with `rio_list_sectors`; `unmatched_sectors` is empty (or run with `strict=true`); `effect_yn` N lines in `excluded_lines` are the intended transfers/reserves.
3. **In-region procurement** — `vendor_in_region_share` is set on every line from evidence; if `assumptions` contains `default_vendor_share`, the 100% assumption is stated in the report.
4. **In-region / out-of-region split** — report 도내 and 도외 separately and the 도내 share; out-of-region effects are leakage, not local benefit.
5. **Magnitude check** — in the bundled 2020 중분류 tables the in-region production coefficient is 1.0–2.1 (제주 median ≈ 1.2) and in+out ≤ about 2.9, so in-region production induction should be roughly 1–2× the in-region spending; value-added induction is below production induction; employment ≈ amount(백만원) ÷ 1,000 × the sector's 명/10억원 coefficient. Recompute one line by hand (amount × coefficient) to confirm.
6. **Price basis** — the price year of every amount is known; `assumptions` shows the intended `price_basis`; current-price amounts were run as `nominal` with per-line sector deflators (table year = 1.0), or — only when those were unavailable — a single GDP deflator with the `single_deflator` simplification stated; if employment is `None`, it is not published. The assumption text appears under the report table.

### Common Mistakes (흔한 실수)
- **Unit confusion**: entering 원 or 천 원 or 억 원 as 백만 원 (amounts 10⁶× too large, or 100× too small). The unit warnings catch only the extremes.
- **Sector mis-mapping**: guessing codes instead of checking `rio_list_sectors`; mapping transfers, reserves or prize money as demand (they should be `effect_yn` N); mapping by item name rather than by what is actually purchased.
- **Entering current prices as-is**: running later-year current-price amounts under the default `constant` basis — employment is overstated by the price rise. Use `price_basis="nominal"` with a deflator (Step 2b).
- **Wrong deflator base**: passing the raw index (e.g. 117) instead of the ratio to the table year (1.17), or rebasing to the wrong year.
- **Using one index when sector deflators exist**: a single GDP deflator for every line is a simplification; prefer the sector's output deflator (연장표) or matching PPI per line.
- Omitting `vendor_in_region_share` and silently reporting the 100% default as fact.
- Adding the participant channel onto policy spending that already pays for the same catering/lodging (double counting).
