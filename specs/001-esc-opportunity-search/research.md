# Research: ESC Opportunity Search

**Date**: 2026-03-30
**Branch**: `001-esc-opportunity-search`

## 1. ESC Portal API

**Decision**: Use the undocumented Elasticsearch-backed API at `POST https://youth.europa.eu/api/rest/eyp/v1/search_en`

**Rationale**: Already proven in the existing N8N workflow (`AzHHRafxpowj2idn`), running every 12 hours since January 2026. The API is stable enough for production use.

**Request format**:
```json
{
  "type": "Opportunity",
  "filters": {
    "status": "open",
    "funding_programme": {
      "id": [1, 2, 3, 4, 5, 6, 7, 8]
    },
    "volunteer_countries": ["NL"]
  },
  "fields": [
    "opid", "title", "description", "town", "country",
    "date_start", "date_end", "has_no_deadline", "topics",
    "countries", "volunteer_countries", "participant_profile"
  ],
  "sort": { "created": "desc" },
  "from": 0,
  "size": 500
}
```

**Response format**: Elasticsearch `hits.hits[]._source` structure. Each hit contains the requested fields directly.

**Pagination**: `from` / `size` style (Elasticsearch offset pagination). Page size 500 max. Continue fetching until `hits.hits` count < 500.

**Required headers**:
- `Content-Type: application/json`
- `User-Agent: Mozilla/5.0 ...` (browser-like UA required)

**Key observations from N8N workflow**:
- The existing workflow truncates descriptions at 500 chars and participant_profile at 1000 chars. Our system will store full text.
- `has_no_deadline` is a boolean field in the API response (not the actual deadline date).
- Past events are filtered client-side by checking `date_end >= today`.
- The `countries` field (destination countries) is separate from `volunteer_countries` (eligible volunteer home countries).

## 2. Opportunity Page URL & Deadline Scraping

**Decision**: Construct URLs as `https://youth.europa.eu/solidarity/opportunity/{opid}_en` and scrape deadlines from HTML.

**Rationale**: The API returns `has_no_deadline` (boolean) but not the actual deadline date. The N8N workflow already scrapes individual pages for this.

**Deadline extraction**: Regex pattern `Application deadline:\s*(\d{2}/\d{2}/\d{4}(?:\s+\d{2}:\d{2})?)` against page HTML.

**Rate limiting**: The N8N workflow uses a 1-second delay between scrapes. We should do the same to avoid being blocked.

**Failure handling**: If scraping fails for an opportunity, store it without a deadline. The `has_no_deadline` API field can be used as a hint — if `true`, skip scraping entirely.

## 3. Databricks Vector Search

**Decision**: Use Delta Sync Index with managed embeddings on Databricks Free Edition.

**Rationale**: Simplest path — Databricks handles embedding generation and index synchronization. Anderson works at Databricks, so access and support are available. $0 cost on free tier.

**Architecture**:
- Delta table stores all opportunity data (source of truth)
- Vector Search index syncs from the Delta table with managed embeddings
- Embedding model: `databricks-bge-large-en` (1024 dimensions, English-focused)
- Sync mode: Triggered (manual trigger after each ingestion run, cheaper than continuous)

**SDK**: `databricks-vectorsearch` package
- `VectorSearchClient` for endpoint and index management
- `index.similarity_search(query_text=..., columns=..., num_results=..., filters={...})` for querying
- Filter pushdown supported (e.g., `{"country =": "Spain"}`)
- Auth: `DATABRICKS_HOST` + `DATABRICKS_TOKEN` environment variables

**Embedding source**: All text fields concatenated — title, description, topics, town, country, participant_profile (per spec clarification).

**Alternatives considered**:
- ChromaDB (local): Simpler but lacks managed embeddings, would need separate embedding service. Fallback option if Databricks free tier proves insufficient.
- Direct Access Index: More control but requires managing embeddings ourselves. Unnecessary complexity.

## 4. Python MCP SDK

**Decision**: Use `mcp` (official Python SDK) with FastMCP high-level API.

**Rationale**: Tier 1 SDK maintained by Model Context Protocol (Anthropic-backed). FastMCP provides decorator-based tool definitions with automatic JSON Schema generation from type hints.

**Key patterns**:
- `FastMCP("server-name")` creates the server instance
- `@mcp.tool()` decorator defines tools; docstrings become descriptions, type hints become JSON Schema
- Tools should be `async def` for I/O operations
- Return strings (text) or structured JSON-serialized strings
- `Context` parameter available for logging and progress reporting
- **Never `print()` to stdout** in stdio transport — corrupts JSON-RPC

**Transport**: stdio for Claude Desktop connection. Server is spawned as a subprocess.

**Claude Desktop config** (macOS, for Alex):
```json
{
  "mcpServers": {
    "esc-opportunity-search": {
      "command": "uv",
      "args": ["--directory", "/path/to/esc-opportunity-search", "run", "python", "-m", "esc_opportunity_search.server"],
      "env": {
        "DATABRICKS_HOST": "https://xxx.cloud.databricks.com",
        "DATABRICKS_TOKEN": "dapi..."
      }
    }
  }
}
```

**For Proxmox deployment**: The MCP server runs on the Proxmox container. Alex's Claude Desktop connects via SSH tunnel or direct network access with SSE transport as an alternative to stdio.

**Package**: `mcp[cli]` (includes dev tools like `mcp dev` inspector and `mcp install`).

## 5. Data Refresh Strategy

**Decision**: Full replace with atomic swap on each daily run.

**Rationale**: The dataset is small (low thousands of opportunities) and the API returns the full set. Incremental updates add complexity without meaningful performance benefit. Atomic swap ensures no partial data is visible.

**Process**:
1. Fetch all pages from ESC API into memory
2. Scrape deadlines for new/changed opportunities (use `has_no_deadline` to skip where possible)
3. Write complete dataset to a staging Delta table
4. On success: swap staging → production (overwrite)
5. On failure: log error, keep existing production data intact
6. Trigger Vector Search index sync

**Alternatives considered**:
- Incremental upsert: More complex, harder to detect removed opportunities, not worth it for this data volume.
- N8N workflow continuation: Already works but truncates data and stores in Google Sheets. Not suitable for vector search.

## 6. Existing N8N Workflow

**Decision**: Keep the N8N workflow running as-is for now. The new system replaces its data function but the Slack notifications are still useful.

**Rationale**: The N8N workflow (`AzHHRafxpowj2idn`) currently:
- Runs every 12 hours
- Stores to Google Sheet `1zZ-hfeuc2kkZpDQ6GOQS_6RAu1-SyqOTjDU6kfA5-ns`
- Sends Slack notifications for new opportunities to #adventures channel
- Truncates descriptions (500 chars) and participant profiles (1000 chars)

Once the new system is stable, the N8N workflow can be deprecated or modified to only send Slack notifications (sourcing data from Databricks instead of the API directly).
