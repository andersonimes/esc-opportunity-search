# Tasks: ESC Opportunity Search

**Input**: Design documents from `/specs/001-esc-opportunity-search/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/mcp-tools.md

**Tests**: Required by constitution (Principle II: Perimeter Testing). Every MCP tool and pipeline step must have integration tests.

**Organization**: Tasks grouped by user story. US5 (Data Ingestion) is executed before US1–US4 because search requires data.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1–US5)
- Exact file paths included in all descriptions

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and dependency management

- [x] T001 Create project structure: `src/esc_opportunity_search/` with `__init__.py`, `server.py`, `search.py`, `ingestion.py`, `models.py`; `tests/integration/` and `tests/fixtures/`
- [x] T002 Initialize `pyproject.toml` with uv: add runtime deps (`mcp[cli]`, `databricks-vectorsearch`, `databricks-sdk`, `httpx`) and dev deps (`pytest`, `pytest-asyncio`). Set `[project.scripts]` entry point for server. Pin all versions.
- [x] T003 [P] Record ESC API fixture: fetch one page of real API responses and save to `tests/fixtures/esc_api_page1.json`; save a sample opportunity HTML page to `tests/fixtures/opportunity_page.html`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Shared models, Databricks connection, MCP skeleton, and logging — MUST complete before any user story

**CRITICAL**: No user story work can begin until this phase is complete

- [x] T004 Create Opportunity and RefreshLog Pydantic models in `src/esc_opportunity_search/models.py` with all fields from data-model.md. Include `description_preview` computed property (first 200 chars). Include JSON serialization helpers for MCP tool responses.
- [x] T005 [P] Create Databricks connection setup in `src/esc_opportunity_search/search.py`: `VectorSearchClient` initialization from `DATABRICKS_HOST` + `DATABRICKS_TOKEN` env vars, index name from `DATABRICKS_CATALOG` + `DATABRICKS_SCHEMA` env vars. Include a `get_spark_session()` helper for Delta table operations via `databricks-sdk`.
- [x] T006 Initialize FastMCP server in `src/esc_opportunity_search/server.py`: create `FastMCP("esc-opportunity-search")` instance, add `__main__` block with `mcp.run(transport="stdio")`, configure logging to stderr (never stdout).
- [x] T007 [P] Configure structured logging in `src/esc_opportunity_search/__init__.py`: stderr handler for MCP server context, file handler (`/var/log/esc-ingestion.log`) for ingestion context. Include timestamps and log level.

**Checkpoint**: Foundation ready — user story implementation can begin

---

## Phase 3: User Story 5 — Data Stays Current (Priority: P5, but prerequisite for all search stories)

**Goal**: Automated daily ingestion of all NL-eligible ESC opportunities into Databricks with full descriptions and scraped deadlines

**Independent Test**: Run ingestion, verify all opportunities from the ESC API are present in the Delta table with correct fields, and Vector Search index is synced

### Implementation for User Story 5

- [x] T008 [US5] Implement ESC API paginated fetch in `src/esc_opportunity_search/ingestion.py`: POST to `https://youth.europa.eu/api/rest/eyp/v1/search_en` with request body from research.md, page through all results (size=500, increment `from`), filter expired opportunities client-side (`date_end >= today`). Use `httpx.AsyncClient` with browser User-Agent header.
- [x] T009 [US5] Implement deadline scraping in `src/esc_opportunity_search/ingestion.py`: for each opportunity where `has_no_deadline` is false, fetch `https://youth.europa.eu/solidarity/opportunity/{opid}_en` and extract deadline with regex `Application deadline:\s*(\d{2}/\d{2}/\d{4}(?:\s+\d{2}:\d{2})?)`. Rate-limit to 1 request/second. On failure, set deadline to None and continue.
- [x] T010 [US5] Implement `search_text` field computation in `src/esc_opportunity_search/ingestion.py`: concatenate title + description + topics (joined) + town + country + participant_profile for each opportunity. Construct `url` field as `https://youth.europa.eu/solidarity/opportunity/{opid}_en`.
- [x] T011 [US5] Implement Delta table full-replace write in `src/esc_opportunity_search/ingestion.py`: write complete dataset to Delta table using `databricks-sdk`. Overwrite mode for atomic swap. On write failure, log error and preserve existing data.
- [x] T012 [US5] Implement Vector Search index sync trigger in `src/esc_opportunity_search/ingestion.py`: after successful Delta table write, call `index.sync()` on the triggered-mode Vector Search index. Log sync status.
- [x] T013 [US5] Implement RefreshLog tracking in `src/esc_opportunity_search/ingestion.py`: create RefreshLog entry at start, update with counts (fetched, added, removed, deadlines scraped/failed) and status (success/failed) on completion. Append structured JSON log entry to the ingestion log file.
- [x] T014 [US5] Add `__main__` entry point in `src/esc_opportunity_search/ingestion.py`: parse optional `--dry-run` flag, run full ingestion pipeline, log summary to file per FR-011.
- [x] T015 [US5] Write integration test for ingestion in `tests/integration/test_ingestion.py`: test API fetch parsing with recorded fixture (`tests/fixtures/esc_api_page1.json`), test deadline extraction with recorded HTML (`tests/fixtures/opportunity_page.html`), test `search_text` computation, test expired opportunity filtering.

**Checkpoint**: Ingestion pipeline functional — data available for search stories

---

## Phase 4: User Story 1 — Semantic Opportunity Search (Priority: P1) MVP

**Goal**: Alex can describe what she's looking for in natural language and receive semantically relevant opportunities

**Independent Test**: Invoke `search_opportunities` tool with a natural language query, verify results are ranked by relevance and contain accurate summary fields

### Implementation for User Story 1

- [x] T016 [US1] Implement `semantic_search()` function in `src/esc_opportunity_search/search.py`: call `index.similarity_search(query_text=..., columns=[all needed], num_results=limit, filters=...)`. Map optional country/topics/date filters to Databricks filter pushdown syntax. Return list of Opportunity models with relevance scores.
- [x] T017 [US1] Implement `search_opportunities` MCP tool in `src/esc_opportunity_search/server.py` per `contracts/mcp-tools.md`: accept `query` (required), `limit`, `country`, `topics`, `date_start_after`, `date_start_before` parameters. Call `semantic_search()`, format results as JSON string with `description_preview`, `relevance_score`, `total_available`.
- [x] T018 [US1] Handle edge cases in `search_opportunities`: no results message, search service unavailable error, limit clamping (1–50, default 10).
- [x] T019 [US1] Write integration test for `search_opportunities` in `tests/integration/test_tools.py`: invoke tool via MCP client with sample queries, verify response structure matches contract, verify no-results case returns informative message.

**Checkpoint**: MVP functional — Alex can search opportunities conversationally

---

## Phase 5: User Story 2 — Structured Filtering (Priority: P2)

**Goal**: Alex can narrow opportunities by country, topic, date range, and deadline

**Independent Test**: Invoke `filter_opportunities` tool with specific criteria, verify every returned opportunity matches all specified filters exactly

### Implementation for User Story 2

- [x] T020 [US2] Implement `filter_query()` function in `src/esc_opportunity_search/search.py`: build SQL query against Delta table with WHERE clauses for country (exact match), topics (array contains), date_start range, deadline_before. Support sort_by parameter (date_start, deadline, title). Use `databricks-sdk` SQL execution.
- [x] T021 [US2] Implement `filter_opportunities` MCP tool in `src/esc_opportunity_search/server.py` per `contracts/mcp-tools.md`: accept `country`, `topics`, `date_start_after`, `date_start_before`, `deadline_before`, `limit`, `sort_by`. Validate at least one filter is provided. Call `filter_query()`, format results as JSON.
- [x] T022 [US2] Handle edge cases in `filter_opportunities`: no filters provided error, no matching results message, combined filter interaction.
- [x] T023 [US2] Write integration test for `filter_opportunities` in `tests/integration/test_tools.py`: invoke with country filter, topic filter, date filter, combined filters. Verify exact match behavior and sort order.

**Checkpoint**: Alex can refine search results by structured criteria

---

## Phase 6: User Story 3 — View Full Opportunity Details (Priority: P3)

**Goal**: Alex can get the complete information for any opportunity to decide whether to apply

**Independent Test**: Invoke `get_opportunity_details` with a known opid, verify all fields (including full description, portal link, deadline) are returned

### Implementation for User Story 3

- [x] T024 [US3] Implement `get_opportunity_by_opid()` function in `src/esc_opportunity_search/search.py`: query Delta table for single row by opid, return full Opportunity model or None.
- [x] T025 [US3] Implement `get_opportunity_details` MCP tool in `src/esc_opportunity_search/server.py` per `contracts/mcp-tools.md`: accept `opid` (required), call `get_opportunity_by_opid()`, return full JSON with all fields including `url` portal link. Return structured error for not-found case.
- [x] T026 [US3] Write integration test for `get_opportunity_details` in `tests/integration/test_tools.py`: invoke with valid opid (verify all fields present), invoke with invalid opid (verify error response).

**Checkpoint**: Complete search-to-decision workflow functional

---

## Phase 7: User Story 4 — Explore Available Opportunities (Priority: P4)

**Goal**: Alex can see summary statistics, breakdowns by country/topic, and approaching deadlines

**Independent Test**: Invoke `get_stats`, verify total count matches data, country/topic breakdowns sum correctly, closing_soon entries have deadlines within 30 days

### Implementation for User Story 4

- [x] T027 [US4] Implement `get_aggregate_stats()` function in `src/esc_opportunity_search/search.py`: query Delta table for total count, GROUP BY country, GROUP BY topic (unnest array), and opportunities with deadline within 30 days sorted ascending. Include last `fetched_at` timestamp as `last_refreshed`.
- [x] T028 [US4] Implement `get_stats` MCP tool in `src/esc_opportunity_search/server.py` per `contracts/mcp-tools.md`: no parameters, call `get_aggregate_stats()`, format as JSON with `total_opportunities`, `by_country`, `by_topic`, `closing_soon` (with `days_remaining`), `last_refreshed`.
- [x] T029 [US4] Write integration test for `get_stats` in `tests/integration/test_tools.py`: invoke tool, verify response structure, verify country/topic counts are consistent with total.

**Checkpoint**: All 4 MCP tools functional — full feature complete

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: Documentation, deployment config, and end-to-end validation

- [x] T030 [P] Update `CLAUDE.md` with complete setup instructions, test commands (`uv run pytest`), and run commands for both ingestion and MCP server
- [x] T031 [P] Create `README.md` with project overview, architecture diagram (text), prerequisites, quickstart, and Claude Desktop config example
- [x] T032 [P] Create sample `claude_desktop_config.json` in `examples/` showing the MCP server configuration for Alex's machine
## Phase 8a: FR-010a — Rolling/Open Deadline Handling (Spec Correction)

**Purpose**: Ensure opportunities with no deadline or failed deadline scraping are displayed as "Rolling/Open" and never excluded from results (FR-010a)

- [x] T035 [US5] Update `build_opportunity()` in `src/esc_opportunity_search/ingestion.py`: set `deadline="Rolling/Open"` (instead of `None`) when `has_no_deadline` is true or deadline scraping fails.
- [x] T036 [P] [US2] Update `filter_query()` in `src/esc_opportunity_search/search.py`: when filtering by `deadline_before`, exclude "Rolling/Open" deadlines from that filter only — do not remove these opportunities from results when other filters (country, topic, date) are applied.
- [x] T037 [P] [US4] Update `get_aggregate_stats()` in `src/esc_opportunity_search/search.py`: exclude "Rolling/Open" from `closing_soon` list but include them in total count, by_country, and by_topic breakdowns.
- [x] T038 [P] [US3] Update `to_detail()` in `src/esc_opportunity_search/models.py`: ensure `deadline` field displays "Rolling/Open" string (not null) for opportunities without deadlines.
- [x] T039 Update integration tests in `tests/integration/test_ingestion.py`: add test that `build_opportunity()` sets deadline to "Rolling/Open" when `has_no_deadline=true` and when deadline param is None.
- [x] T040 Update integration tests in `tests/integration/test_tools.py`: add test that `filter_opportunities` with `deadline_before` does not exclude rolling-deadline opportunities from non-deadline filters.

**Checkpoint**: Rolling/open opportunities never erroneously filtered from results

---

- [ ] T033 End-to-end validation: run ingestion against live ESC API, then invoke all 4 MCP tools via `mcp dev` inspector and verify responses match contracts
- [ ] T034 Configure daily ingestion cron job on Proxmox: add crontab entry running `uv run python -m esc_opportunity_search.ingestion` at 06:00 UTC, logging to the configured log file. Verify first scheduled run completes successfully.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Setup completion — BLOCKS all user stories
- **US5 Data Ingestion (Phase 3)**: Depends on Foundational — BLOCKS US1–US4 (search needs data)
- **US1 Semantic Search (Phase 4)**: Depends on US5 — can start after data is loaded
- **US2 Structured Filtering (Phase 5)**: Depends on US5 for data — can run in parallel with US1
- **US3 Opportunity Details (Phase 6)**: Depends on US5 for data — can run in parallel with US1/US2
- **US4 Stats (Phase 7)**: Depends on US5 for data — can run in parallel with US1–US3
- **Polish (Phase 8)**: Depends on all user stories complete

### User Story Dependencies

- **US5 (P5)**: Prerequisite for all other stories — data must exist before search works
- **US1 (P1)**: Depends on US5 for data. Requires Vector Search index to be populated.
- **US2 (P2)**: Depends on US5 for data. Independent of US1 (queries Delta table directly).
- **US3 (P3)**: Depends on US5 for data. Independent of US1/US2 (single row lookup).
- **US4 (P4)**: Depends on US5 for data. Independent of US1–US3 (aggregate queries).

### Within Each User Story

- Search function in `search.py` before MCP tool in `server.py`
- Core implementation before edge case handling
- Implementation before integration test

### Parallel Opportunities

- T003 (fixtures) can run in parallel with T001/T002
- T005 + T007 can run in parallel within Phase 2
- After US5 completes: US1, US2, US3, US4 can ALL start in parallel (different functions in search.py, different tools in server.py)
- T030 + T031 + T032 can run in parallel within Phase 8
- All integration tests (T019, T023, T026, T029) can run in parallel once their respective tools are implemented

---

## Parallel Example: After US5 Completes

```
# All four tool implementations can proceed simultaneously:
Agent A: T016 → T017 → T018 → T019  (US1: semantic search)
Agent B: T020 → T021 → T022 → T023  (US2: structured filtering)
Agent C: T024 → T025 → T026          (US3: opportunity details)
Agent D: T027 → T028 → T029          (US4: stats)
```

---

## Implementation Strategy

### MVP First (US5 + US1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational
3. Complete Phase 3: US5 — Data Ingestion (load real data)
4. Complete Phase 4: US1 — Semantic Search
5. **STOP and VALIDATE**: Alex can search opportunities in Claude Desktop
6. Deploy to Proxmox, set up daily cron

### Incremental Delivery

1. Setup + Foundational → Framework ready
2. US5 → Data loaded and refreshing daily
3. US1 → Alex can search (MVP!)
4. US2 → Alex can filter by criteria
5. US3 → Alex can view full details and apply
6. US4 → Alex can explore stats and deadlines
7. Each story adds capability without breaking previous stories

---

## Notes

- Constitution requires perimeter tests for every MCP tool and pipeline step — tests are mandatory
- All MCP tools return JSON strings (not raw objects) per FastMCP patterns
- Never print to stdout in server.py — corrupts stdio transport
- Ingestion logs to file; server logs to stderr
- Databricks auth via environment variables (DATABRICKS_HOST, DATABRICKS_TOKEN)
- ESC API requires browser-like User-Agent header
- Rate-limit deadline scraping to 1 req/sec to avoid blocking
