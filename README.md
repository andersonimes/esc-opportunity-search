# ESC Opportunity Search

MCP server that lets you search European Solidarity Corps volunteering opportunities conversationally from Claude.

## Architecture

```
ESC Portal API --> Ingestion Script --> Databricks Free Edition
(Python, daily)                        (Delta Table + Vector Search Index)
                                                    |
                                        MCP Server (Python, on Proxmox)
                                          - search_opportunities
                                          - filter_opportunities
                                          - get_opportunity_details
                                          - get_stats
                                                    |
                                        Claude Desktop (Alex)
```

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager
- Databricks workspace (Free Edition) with Unity Catalog, Vector Search endpoint, and SQL warehouse
- Network access to `youth.europa.eu`

## Setup

```bash
git clone <repo-url> && cd esc-opportunity-search
uv sync
```

Set environment variables:

```bash
export DATABRICKS_HOST="https://your-workspace.cloud.databricks.com"
export DATABRICKS_TOKEN="dapi..."
export DATABRICKS_CATALOG="main"
export DATABRICKS_SCHEMA="esc"
```

## Usage

### Load data

```bash
uv run python -m esc_opportunity_search.ingestion
```

### Run MCP server

```bash
uv run python -m esc_opportunity_search.server
```

### Claude Desktop configuration

Add to `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS):

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
        "DATABRICKS_TOKEN": "dapi...",
        "DATABRICKS_CATALOG": "main",
        "DATABRICKS_SCHEMA": "esc"
      }
    }
  }
}
```

## Testing

```bash
uv run pytest -v
```

## MCP Tools

| Tool | Description |
|------|-------------|
| `search_opportunities` | Semantic natural language search over all opportunities |
| `filter_opportunities` | Filter by country, topic, date range, deadline |
| `get_opportunity_details` | Full details for a single opportunity by ID |
| `get_stats` | Summary statistics, country/topic breakdowns, closing deadlines |
