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
   (rio_list_coefficients)     (Budget to RIO      (reserved, #6)      (rio_compute_effects    (rio_render_report      (checklist
   (rio_list_profiles)          Sectors)                                or rio_compute_event)   interim / final)        below)
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
- Reserved. Guidance for this step will be added once the price-basis design in issue #6 is decided.

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
6. **Price basis** — reserved (#6).

### Common Mistakes (흔한 실수)
- **Unit confusion**: entering 원 or 천 원 or 억 원 as 백만 원 (amounts 10⁶× too large, or 100× too small). The unit warnings catch only the extremes.
- **Sector mis-mapping**: guessing codes instead of checking `rio_list_sectors`; mapping transfers, reserves or prize money as demand (they should be `effect_yn` N); mapping by item name rather than by what is actually purchased.
- **Entering current prices as-is**: amounts from a later year than the coefficient table entered without recording their price year. Handling is pending the price-basis decision (#6); until then, note the price year of the amounts in the report.
- Omitting `vendor_in_region_share` and silently reporting the 100% default as fact.
- Adding the participant channel onto policy spending that already pays for the same catering/lodging (double counting).
