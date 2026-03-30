# Data Model: ESC Opportunity Search

**Date**: 2026-03-30
**Branch**: `001-esc-opportunity-search`

## Entities

### Opportunity

The central entity. One record per ESC volunteering placement.

| Field | Type | Source | Notes |
|-------|------|--------|-------|
| opid | string (PK) | API `_source.opid` | Unique identifier from ESC portal |
| title | string | API `_source.title` | Opportunity title |
| description | text | API `_source.description` | Full text, no truncation |
| town | string | API `_source.town` | City/town of placement |
| country | string | API `_source.country` | ISO 2-letter country code (destination) |
| date_start | date | API `_source.date_start` | Placement start date |
| date_end | date | API `_source.date_end` | Placement end date |
| has_no_deadline | boolean | API `_source.has_no_deadline` | Whether opportunity has rolling/no deadline |
| deadline | string (nullable) | Scraped from HTML | Format: `DD/MM/YYYY` or `DD/MM/YYYY HH:MM`. Null if scraping failed or `has_no_deadline` is true |
| topics | array of strings | API `_source.topics` | Topic tags (e.g., "Environment", "Digital") |
| countries | array of strings | API `_source.countries` | Destination countries (may differ from `country`) |
| volunteer_countries | array of strings | API `_source.volunteer_countries` | Eligible volunteer home countries (always includes "NL") |
| participant_profile | text | API `_source.participant_profile` | Full text, no truncation |
| url | string | Constructed | `https://youth.europa.eu/solidarity/opportunity/{opid}_en` |
| search_text | text | Computed | Concatenation of title + description + topics + town + country + participant_profile for embedding |
| fetched_at | timestamp | System | When this record was last fetched/updated |

**Identity**: `opid` is the primary key and unique identifier.

**Lifecycle**:
- Created: When first fetched from the ESC API
- Updated: When data changes on a subsequent refresh (detected by comparing fields)
- Removed: When no longer returned by the API on a successful full refresh

### RefreshLog

Tracks each data refresh run for observability.

| Field | Type | Notes |
|-------|------|-------|
| run_id | string (PK) | UUID for each refresh run |
| started_at | timestamp | When the refresh started |
| completed_at | timestamp (nullable) | When the refresh completed (null if failed) |
| status | string | `success`, `failed`, `partial` |
| opportunities_fetched | integer | Total opportunities retrieved from API |
| opportunities_added | integer | New opportunities added |
| opportunities_removed | integer | Stale opportunities removed |
| deadlines_scraped | integer | Deadlines successfully extracted |
| deadlines_failed | integer | Deadline scrapes that failed |
| pages_fetched | integer | API pages retrieved |
| error_message | text (nullable) | Error details if status is `failed` |

## Relationships

```
Opportunity (many) ──fetched-by──> RefreshLog (one)
```

Each refresh produces/updates many opportunities. The RefreshLog is independent — opportunities don't store a foreign key to their refresh run (the `fetched_at` timestamp serves this purpose).

## Data Volume Estimates

- Total NL-eligible opportunities: ~500–3,000 (based on ESC portal observations)
- Record size: ~2–5 KB per opportunity (mostly description + participant_profile text)
- Total dataset: ~5–15 MB
- Vector index: ~1,000 dimensions × ~3,000 records = ~12 MB of vectors
- Refresh frequency: daily
- Growth rate: slow (net new opportunities per day is small)

## Delta Table Schema

```
catalog.schema.esc_opportunities (
  opid STRING NOT NULL,
  title STRING,
  description STRING,
  town STRING,
  country STRING,
  date_start STRING,
  date_end STRING,
  has_no_deadline BOOLEAN,
  deadline STRING,
  topics ARRAY<STRING>,
  countries ARRAY<STRING>,
  volunteer_countries ARRAY<STRING>,
  participant_profile STRING,
  url STRING,
  search_text STRING,
  fetched_at TIMESTAMP
)
```

Primary key for Vector Search index: `opid`
Embedding source column: `search_text`
Embedding model: `databricks-bge-large-en`
