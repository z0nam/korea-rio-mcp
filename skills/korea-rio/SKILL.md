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
1. Check Tables/Profiles ──▶ 2. Map Spending ──▶ 3. Compute Effects ──▶ 4. Render Report
   (rio_list_coefficients)     (Budget to RIO      (rio_compute_effects    (rio_render_report
   (rio_list_profiles)          Sectors)            or rio_compute_event)   interim / final)
```

### Step 1. Inspect Available Coefficient Tables & Profiles
- `rio_list_coefficients`: List available coefficient tables (bundled: Jeju 2020 83-sector intermediate classification).
- `rio_list_profiles`: Inspect built-in per-capita spending profiles for event attendees (e.g., `jeju_domestic_leisure` for festival visitors, `jeju_domestic_visitor`/`jeju_foreign_visitor` for MICE/forum participants).
- (Optional) `rio_check_base_table_update`: Check if BOK has published newer regional IO tables.

### Step 2. Map Expenditures to Industrial Sectors
- Translate budget lines or consumption spending into Regional IO sector codes (e.g. 83-sector classification).
- Specify:
  - `sector_code` (and optional `sector_name`)
  - `amount_mw` (amount in million KRW, 백만 원)
  - `vendor_in_region_share` (fraction captured by regional vendors, default `1.0`)

### Step 3. Compute Effects
Choose between direct spending calculation and combined event calculation:

- **Sector-level spending**:
  - Use `rio_compute_effects` with `region`, `table_year`, and `spending` list.
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
