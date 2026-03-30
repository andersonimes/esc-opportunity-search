# Quickstart: ESC Opportunity Search

**Branch**: `001-esc-opportunity-search`

## Prerequisites

- Python 3.12+
- `uv` package manager
- Databricks workspace (Free Edition) with:
  - Unity Catalog enabled
  - Vector Search endpoint provisioned
  - Personal access token
- Network access to `youth.europa.eu`

## Environment Variables

```bash
export DATABRICKS_HOST="https://your-workspace.cloud.databricks.com"
export DATABRICKS_TOKEN="dapi..."
export DATABRICKS_CATALOG="main"        # or your catalog name
export DATABRICKS_SCHEMA="esc"          # or your schema name
```

## Install

```bash
uv sync
```

## Run Ingestion (manual)

```bash
uv run python -m esc_opportunity_search.ingestion
```

This fetches all NL-eligible ESC opportunities, scrapes deadlines, writes to the Delta table, and triggers a Vector Search index sync.

## Run MCP Server (local/dev)

```bash
uv run python -m esc_opportunity_search.server
```

The server runs on stdio transport. For development/debugging:

```bash
uv run mcp dev src/esc_opportunity_search/server.py
```

This opens the MCP Inspector in your browser.

## Claude Desktop Configuration

Add to Claude Desktop config (`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS):

```json
{
  "mcpServers": {
    "esc-opportunity-search": {
      "command": "uv",
      "args": [
        "--directory", "/path/to/esc-opportunity-search",
        "run", "python", "-m", "esc_opportunity_search.server"
      ],
      "env": {
        "DATABRICKS_HOST": "https://your-workspace.cloud.databricks.com",
        "DATABRICKS_TOKEN": "dapi..."
      }
    }
  }
}
```

## Run Tests

```bash
uv run pytest
```

## Daily Refresh (cron)

On the Proxmox container:

```bash
# crontab -e
0 6 * * * cd /path/to/esc-opportunity-search && /path/to/uv run python -m esc_opportunity_search.ingestion >> /var/log/esc-ingestion.log 2>&1
```
