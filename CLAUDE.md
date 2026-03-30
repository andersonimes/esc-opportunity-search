# ESC Opportunity Search

MCP server that lets Alex search European Solidarity Corps volunteering opportunities conversationally from Claude.

## Project Context

- **Vault project doc**: ~/vault/projects/esc-opportunity-search.md
- **Data source**: ESC API at `POST https://youth.europa.eu/api/rest/eyp/v1/search_en`
- **Constitution**: .specify/memory/constitution.md

## Spec-Driven Development

This project uses [GitHub Spec Kit](https://github.com/github/spec-kit). Specs live in `specs/`. Use `/speckit.*` slash commands to drive the workflow.

## Setup

```bash
uv sync                          # Install all dependencies
```

Required environment variables (set in `.env` or export):
```
DATABRICKS_HOST=https://your-workspace.cloud.databricks.com
DATABRICKS_TOKEN=dapi...
DATABRICKS_CATALOG=main
DATABRICKS_SCHEMA=esc
```

## Running

```bash
# Run the MCP server (stdio transport, for Claude Desktop)
uv run python -m esc_opportunity_search.server

# Run data ingestion (fetches all ESC opportunities into Databricks)
uv run python -m esc_opportunity_search.ingestion

# Dry run ingestion (fetch + process without writing to Databricks)
uv run python -m esc_opportunity_search.ingestion --dry-run

# MCP Inspector (browser-based tool debugger)
uv run mcp dev src/esc_opportunity_search/server.py
```

## Testing

```bash
uv run pytest           # Run all tests
uv run pytest -v        # Verbose output
```

## Active Technologies
- Python 3.12+ + `mcp[cli]` (MCP server SDK), `databricks-vectorsearch` (vector search client), `databricks-sdk` (Delta table operations), `httpx` (async HTTP for API + scraping) (001-esc-opportunity-search)
- Databricks Delta table + Vector Search index (Free Edition) (001-esc-opportunity-search)

## Recent Changes
- 001-esc-opportunity-search: Added Python 3.12+ + `mcp[cli]` (MCP server SDK), `databricks-vectorsearch` (vector search client), `databricks-sdk` (Delta table operations), `httpx` (async HTTP for API + scraping)
