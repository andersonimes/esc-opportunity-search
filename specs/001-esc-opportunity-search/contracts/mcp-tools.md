# MCP Tool Contracts: ESC Opportunity Search

**Date**: 2026-03-30
**Branch**: `001-esc-opportunity-search`

The MCP server exposes four tools to Claude. Each tool definition below shows the name, description, parameters (with types), and return format.

---

## `search_opportunities`

Semantic search over ESC volunteering opportunities using natural language.

**Parameters**:

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| query | string | yes | — | Natural language search query (e.g., "environmental volunteering in Spain") |
| limit | integer | no | 10 | Maximum number of results to return (1–50) |
| country | string | no | null | Filter by destination country code (e.g., "ES", "IT") |
| topics | array of strings | no | null | Filter by topic tags (e.g., ["Environment", "Digital"]) |
| date_start_after | string | no | null | Filter: only opportunities starting on or after this date (YYYY-MM-DD) |
| date_start_before | string | no | null | Filter: only opportunities starting on or before this date (YYYY-MM-DD) |

**Returns**: JSON-serialized string containing:
```json
{
  "results": [
    {
      "opid": "12345",
      "title": "Nature Conservation in Andalusia",
      "town": "Seville",
      "country": "ES",
      "date_start": "2026-09-01",
      "date_end": "2027-06-30",
      "topics": ["Environment and natural protection"],
      "description_preview": "First 200 characters of description...",
      "url": "https://youth.europa.eu/solidarity/opportunity/12345_en",
      "relevance_score": 0.87
    }
  ],
  "total_available": 42,
  "query": "environmental volunteering in Spain",
  "filters_applied": {"country": "ES"}
}
```

---

## `filter_opportunities`

Structured filtering on opportunity metadata. No semantic search — returns exact matches on specified criteria.

**Parameters**:

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| country | string | no | null | Destination country code |
| topics | array of strings | no | null | Topic tags to match (any match) |
| date_start_after | string | no | null | Opportunities starting on or after (YYYY-MM-DD) |
| date_start_before | string | no | null | Opportunities starting on or before (YYYY-MM-DD) |
| deadline_before | string | no | null | Opportunities with deadline before this date (YYYY-MM-DD) |
| limit | integer | no | 20 | Maximum results (1–50) |
| sort_by | string | no | "date_start" | Sort field: "date_start", "deadline", "title" |

At least one filter parameter must be provided.

**Returns**: JSON-serialized string containing:
```json
{
  "results": [
    {
      "opid": "12345",
      "title": "Nature Conservation in Andalusia",
      "town": "Seville",
      "country": "ES",
      "date_start": "2026-09-01",
      "date_end": "2027-06-30",
      "topics": ["Environment and natural protection"],
      "deadline": "15/06/2026",
      "description_preview": "First 200 characters...",
      "url": "https://youth.europa.eu/solidarity/opportunity/12345_en"
    }
  ],
  "total_matching": 15,
  "filters_applied": {"country": "ES", "date_start_after": "2026-09-01"}
}
```

---

## `get_opportunity_details`

Retrieve full details for a single opportunity.

**Parameters**:

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| opid | string | yes | — | Unique opportunity identifier |

**Returns**: JSON-serialized string containing:
```json
{
  "opid": "12345",
  "title": "Nature Conservation in Andalusia",
  "description": "Full untruncated description text...",
  "town": "Seville",
  "country": "ES",
  "date_start": "2026-09-01",
  "date_end": "2027-06-30",
  "topics": ["Environment and natural protection"],
  "volunteer_countries": ["NL", "DE", "FR"],
  "participant_profile": "Full participant profile text...",
  "deadline": "15/06/2026",
  "has_no_deadline": false,
  "url": "https://youth.europa.eu/solidarity/opportunity/12345_en"
}
```

**Error case** (opportunity not found):
```json
{
  "error": "not_found",
  "message": "No opportunity found with ID '99999'. It may have been removed or the ID may be incorrect."
}
```

---

## `get_stats`

Summary statistics about all available opportunities.

**Parameters**: None.

**Returns**: JSON-serialized string containing:
```json
{
  "total_opportunities": 1247,
  "by_country": {
    "ES": 145,
    "IT": 132,
    "DE": 98
  },
  "by_topic": {
    "Environment and natural protection": 234,
    "Inclusion": 189,
    "Digital": 112
  },
  "closing_soon": [
    {
      "opid": "12345",
      "title": "Nature Conservation in Andalusia",
      "deadline": "15/04/2026",
      "days_remaining": 16,
      "url": "https://youth.europa.eu/solidarity/opportunity/12345_en"
    }
  ],
  "last_refreshed": "2026-03-30T06:00:00Z"
}
```

`closing_soon` includes opportunities with deadlines within the next 30 days, sorted by deadline ascending.
