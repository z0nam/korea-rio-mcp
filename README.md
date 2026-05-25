# korea-rio-mcp

Regional Input-Output (RIO) economic-impact analysis as a **cross-platform MCP server**.
Computes production / value-added / employment induced effects (split in-region vs
out-of-region) for an economic event in any Korean region, using Bank of Korea
regional input-output tables. Works with Claude Code, Codex, and Gemini CLI over stdio.

Generalized from the 26p17 Seogwipo festival impact study; the Jeju 2020 table ships
as a validated golden case.

Unlike data-access MCP servers (e.g. OECD-MCP, bcrp-mcp) that fetch published
statistics, korea-rio-mcp *computes* induced economic effects from regional IO coefficients —
an open, MCP-native counterpart to commercial tools like IMPLAN, built on Bank of Korea
regional input-output tables.

## What it does

1. **Acquire the base table** — check whether BOK has published a newer regional IO base
   year and ingest its workbook into versioned induced coefficients.
2. **Compute effects** — apply induced coefficients to event spending (policy expenditure
   + outside-visitor on-site consumption + ancillary stay), keeping the reliable
   policy channel separate from the variable participant channel.
3. **Document** — render standardized markdown effect tables (interim: production only;
   final: all three indicators).

## Install

```bash
pip install -e .        # or: uvx --from . korea-rio-mcp
```

Requires Python ≥ 3.10. The Jeju 2020 medium-classification (83-sector) coefficient
table is bundled, so effect computation works out of the box.

## Tools

| Tool | Purpose |
|---|---|
| `rio_list_coefficients` | List available coefficient tables (cached/bundled) |
| `rio_check_base_table_update` | Check BOK for a newer regional IO base year |
| `rio_load_base_table` | Extract + cache coefficients from a BOK workbook |
| `rio_compute_effects` | Effects for sector-level spending lines |
| `rio_compute_event` | Combined event effect (policy + visitor channels, kept separate) |
| `rio_render_report` | Standardized markdown effect table (`interim` / `final`) |

Prompts: `map_budget_to_sectors`, `documentation_standard` — the judgment-heavy steps
(budget→sector mapping, reporting tone) are intentionally left to the LLM layer.

## MCP client config

Run the server with the `korea-rio-mcp` console script (stdio transport).

**Claude Code** — `.mcp.json` in your project (or `claude mcp add`):

```json
{
  "mcpServers": {
    "rio": { "command": "korea-rio-mcp" }
  }
}
```

**Codex** — `~/.codex/config.toml`:

```toml
[mcp_servers.rio]
command = "korea-rio-mcp"
```

**Gemini CLI** — `~/.gemini/settings.json`:

```json
{
  "mcpServers": {
    "rio": { "command": "korea-rio-mcp" }
  }
}
```

If `korea-rio-mcp` is not on PATH, use the absolute path to the console script (or
`python -m rio_mcp.server`).

## Adding a new region

The induced-coefficient extraction needs each region's subtotal row in the BOK
workbook. Register a `RegionTableLayout` in `src/rio_mcp/engine/regions.py` (the
Jeju 2020 entry is the worked example), then call `rio_load_base_table`.

## Data note

BOK **regional** IO tables are not in a clean API — they are published as Excel files
under [BOK 간행물](https://www.bok.or.kr/portal/singl/newsData/list.do?menuNo=200457),
irregularly (~5-year cadence: 2003 → 2005 → 2010 → 2013 → 2015 → 2020). `rio_check_base_table_update`
reports the latest published year and hands you the download URL; ingestion is then a
manual download + `rio_load_base_table`.

## Tests

```bash
pytest    # golden test: reproduces 26p17 Jeju 2020 figures
```

## Data source & attribution

The bundled coefficient tables (`data/coefficients/`, `data/reference/`) are
**derived works** computed from the Bank of Korea (한국은행) regional
input-output tables (지역산업연관표, 2020 base year), published at the
[BOK 간행물 listing](https://www.bok.or.kr/portal/singl/newsData/list.do?menuNo=200457).

- **Source: Bank of Korea (한국은행).**
- These files are **not** the original BOK workbooks — they are induced
  coefficients (production / value-added / employment, in-region vs
  out-of-region) extracted and transformed from them.
- Use of BOK data is subject to the
  [BOK copyright policy](https://www.bok.or.kr/portal/main/contents.do?menuNo=200228),
  which requires attribution to the Bank of Korea and disclosure of any
  modification.

## License

The MIT license (see [`LICENSE`](LICENSE)) covers the **software only**. It does
**not** extend to the underlying BOK statistical data, whose use is governed by
the BOK copyright policy linked above.
