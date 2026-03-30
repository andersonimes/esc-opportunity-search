# Feature Specification: ESC Opportunity Search

**Feature Branch**: `001-esc-opportunity-search`
**Created**: 2026-03-30
**Status**: Draft
**Input**: User description: "Build an MCP server that enables natural language search over European Solidarity Corps (ESC) volunteering opportunities, for use by a Dutch resident (Alex) from her Claude Desktop account."

## Clarifications

### Session 2026-03-30

- Q: Should the system include a direct link to the ESC portal page for each opportunity? → A: Yes, include a direct portal link in detail results so Alex can navigate to the application page.
- Q: What opportunity data should drive semantic search matching? → A: All text fields — title, description, topics, location, and participant profile — concatenated for maximum recall.
- Q: How should ingestion failures be surfaced? → A: Log to file only. Anderson checks manually or sets up external log monitoring.
- Q: How should opportunities with no deadline or failed deadline scraping be handled? → A: Display as "Rolling/Open". Never exclude from search/filter results. Only exclude from deadline-sorted lists like "closing soon". (FR-010a added)
- Q: How should the scraper handle ESC portal rate limiting? → A: 2-second base delay between requests, exponential backoff on 429s (2s/4s/8s, 3 retries). Failed scrapes get "Rolling/Open" deadline. (FR-010 updated)

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Semantic Opportunity Search (Priority: P1)

Alex opens Claude Desktop and describes what kind of volunteering she's looking for in her own words — for example, "Find me environmental volunteering in Spain" or "Show me anything related to working with refugees." The system understands the intent behind her query and returns a ranked list of the most relevant ESC opportunities, each showing key details (title, location, dates, and a brief description) so she can quickly scan what's available.

**Why this priority**: This is the core value proposition. The official ESC portal forces Alex to navigate rigid category filters and paginated lists. Semantic search lets her describe what she wants naturally and get relevant results immediately. Without this, the tool has no reason to exist.

**Independent Test**: Can be fully tested by submitting natural language queries and verifying that returned opportunities are semantically relevant (not just keyword matches), ranked by relevance, and display accurate summary information.

**Acceptance Scenarios**:

1. **Given** ESC opportunities exist in the system, **When** Alex asks "volunteering in Italy with animals", **Then** she receives a ranked list of opportunities related to animal welfare in Italy, each showing title, town, country, start/end dates, and a short description.
2. **Given** ESC opportunities exist in the system, **When** Alex asks "something outdoors in Northern Europe", **Then** she receives opportunities semantically related to outdoor/nature activities in Scandinavian and Baltic countries, not just exact keyword matches.
3. **Given** no opportunities match the query, **When** Alex searches for something unavailable (e.g., "underwater basket weaving in Antarctica"), **Then** she receives a clear message that no matching opportunities were found.
4. **Given** many opportunities match, **When** Alex searches a broad term like "volunteering", **Then** she receives a limited set of top results (default 10) with an indication that more exist.

---

### User Story 2 - Structured Filtering (Priority: P2)

Alex wants to narrow down opportunities by specific practical criteria: destination country, topic area, or date availability. She asks things like "What opportunities are available starting in September?" or "Show me digital skills projects in Portugal." The system applies structured filters and returns only opportunities matching the specified criteria.

**Why this priority**: After finding broad matches, Alex needs to refine results to match her real-world constraints — when she's available, where she wants to go, what topics interest her. This transforms the tool from a discovery engine into a practical decision-making aid.

**Independent Test**: Can be fully tested by requesting filtered results and verifying that every returned opportunity matches the specified filter criteria exactly.

**Acceptance Scenarios**:

1. **Given** opportunities exist across multiple countries, **When** Alex asks to filter by a specific destination country (e.g., "Spain"), **Then** only opportunities located in Spain are returned.
2. **Given** opportunities span various date ranges, **When** Alex filters by date (e.g., "starting after September 2026"), **Then** only opportunities with a start date on or after September 1, 2026 are returned.
3. **Given** opportunities cover multiple topics, **When** Alex filters by topic (e.g., "environment", "digital skills"), **Then** only opportunities tagged with matching topics are returned.
4. **Given** Alex combines multiple filters (e.g., country + topic), **When** she asks "environmental projects in Greece", **Then** only opportunities matching both criteria are returned.
5. **Given** no opportunities match the filter combination, **When** Alex applies overly restrictive filters, **Then** she receives a clear message that no opportunities match those criteria.

---

### User Story 3 - View Full Opportunity Details (Priority: P3)

Alex finds a promising opportunity in her search results and wants the complete picture before deciding to apply. She asks for full details and receives everything available: the complete description, participant profile requirements, exact dates, location details, topics, and application deadline (when available).

**Why this priority**: Completing the search-to-decision workflow. Without full details, Alex would still need to visit the ESC portal to evaluate opportunities, defeating the purpose of the tool.

**Independent Test**: Can be fully tested by requesting details for a known opportunity and verifying all stored fields are returned completely and accurately.

**Acceptance Scenarios**:

1. **Given** Alex has received search results, **When** she asks for more details about a specific opportunity (by title or identifier), **Then** she receives: full description (untruncated), town and country, start and end dates, all topic tags, volunteer country eligibility, participant profile requirements, and application deadline (if available).
2. **Given** an opportunity has no deadline information, **When** Alex requests its details, **Then** all other fields are shown and the deadline is noted as unavailable.
3. **Given** an invalid or non-existent opportunity identifier, **When** Alex requests details, **Then** she receives a clear message that the opportunity was not found.

---

### User Story 4 - Explore Available Opportunities (Priority: P4)

Alex wants to get a high-level picture of what's out there — how many opportunities exist, which countries have the most, what topics are trending, and what deadlines are approaching. She asks things like "What's closing soon?" or "How many opportunities are there in each country?" The system provides summary statistics and highlights.

**Why this priority**: Gives Alex situational awareness and helps her discover opportunities she might not have thought to search for. Also surfaces time-sensitive opportunities (approaching deadlines) that she might otherwise miss.

**Independent Test**: Can be fully tested by requesting summary statistics and verifying the counts, breakdowns, and deadline highlights are accurate against the stored data.

**Acceptance Scenarios**:

1. **Given** opportunities exist in the system, **When** Alex asks "how many opportunities are there?", **Then** she receives the total count and a breakdown by destination country.
2. **Given** opportunities exist with various topics, **When** Alex asks about available topics, **Then** she receives a breakdown of opportunity counts by topic area.
3. **Given** some opportunities have approaching deadlines, **When** Alex asks "what's closing soon?", **Then** she receives opportunities sorted by deadline (soonest first), with deadlines within the next 30 days highlighted.
4. **Given** the data was last refreshed at a known time, **When** Alex asks for stats, **Then** the response includes when the data was last updated.

---

### User Story 5 - Data Stays Current (Priority: P5)

The system automatically refreshes its opportunity data daily, fetching all currently open ESC opportunities eligible for Dutch residents. Alex never has to worry about stale data — the system always reflects what's currently available on the ESC portal (within a 24-hour window). New opportunities appear, closed opportunities are removed, and changed details are updated.

**Why this priority**: The tool is only useful if the data is current. Stale data leads to wasted effort applying to closed opportunities or missing new ones. This is infrastructure that underpins all other stories.

**Independent Test**: Can be fully tested by running the data refresh process, comparing the stored data against a fresh pull from the source, and verifying completeness and accuracy.

**Acceptance Scenarios**:

1. **Given** the system is deployed, **When** 24 hours have passed since the last refresh, **Then** the system has automatically fetched the latest opportunity data from the source.
2. **Given** a new opportunity appears on the ESC portal, **When** the next daily refresh runs, **Then** the new opportunity is searchable in the system.
3. **Given** an opportunity is removed from the ESC portal, **When** the next daily refresh runs, **Then** the opportunity is no longer returned in search results.
4. **Given** the source is temporarily unavailable during a refresh, **When** the refresh fails, **Then** the existing data is preserved (not deleted) and the failure is logged.
5. **Given** the source returns paginated results (500 per page), **When** a refresh runs, **Then** all pages are fetched to capture the complete dataset.

---

### Edge Cases

- What happens when the search service is temporarily unavailable? The system returns a clear error message; Alex can retry later.
- What happens when a query is extremely long or contains special characters? The system handles it gracefully, truncating or sanitizing as needed, without crashing.
- What happens when opportunity data changes between Alex's search and her detail request? The system returns whatever is currently stored; minor staleness within a day is acceptable.
- What happens when the daily refresh encounters a partial failure (some pages fetched, some not)? The system either completes the full refresh or rolls back to the previous complete dataset — no partial updates.
- What happens when Alex asks for opportunities in a country with no results? The system returns an empty result set with a clear message, not an error.
- What happens when deadline scraping fails for some opportunities? Those opportunities are still stored and searchable, with deadline displayed as "Rolling/Open".
- What happens when the ESC portal rate-limits deadline scraping (HTTP 429)? The system retries with exponential backoff (up to 3 retries per opportunity). If all retries fail, the opportunity is stored with deadline "Rolling/Open" and ingestion continues with the remaining opportunities.
- What happens when an opportunity has no deadline (has_no_deadline=true) or the deadline field is missing? The opportunity MUST still appear in all search, filter, and stats results. The deadline is displayed as "Rolling/Open". When filtering by deadline (e.g., "closing soon"), these opportunities are excluded from deadline-sorted lists but never hidden from general search or filter results.

## Requirements *(mandatory)*

### Functional Requirements

#### Search & Discovery

- **FR-001**: System MUST accept natural language queries and return opportunities ranked by semantic relevance to the query intent.
- **FR-002**: System MUST support structured filtering by destination country (exact match), topic area (exact match on tags), and date range (start date within range).
- **FR-003**: System MUST allow combining semantic search with structured filters in a single request.
- **FR-004**: System MUST return a configurable number of results per request, defaulting to 10 and capped at a maximum of 50.
- **FR-005**: System MUST return full details for a single opportunity when requested by its unique identifier, including all stored fields and a direct link to the opportunity's page on the ESC portal.
- **FR-006**: System MUST provide summary statistics: total opportunity count, count by destination country, count by topic, and opportunities with approaching deadlines (within 30 days).

#### Data Freshness

- **FR-007**: System MUST fetch all open ESC volunteering opportunities eligible for Netherlands residents from the source, with no truncation of descriptions.
- **FR-008**: System MUST refresh opportunity data at least once every 24 hours via an automated process.
- **FR-009**: System MUST handle paginated source data, fetching all available pages to capture the complete dataset.
- **FR-010**: System MUST extract application deadlines from individual opportunity pages where available. Scraping MUST use a minimum 5-second delay between requests and retry up to 3 times on rate-limit responses (HTTP 429) with exponential backoff (2s, 4s, 8s).
- **FR-010a**: Opportunities with no deadline (rolling admission) or where deadline extraction failed MUST be displayed with deadline shown as "Rolling/Open". These opportunities MUST NOT be excluded from search results, filter results, or statistics. They are only excluded from deadline-specific sorted lists (e.g., "closing soon").
- **FR-011**: System MUST preserve existing data when a refresh fails, ensuring no data loss from transient errors. Failures MUST be logged to a file with sufficient detail to diagnose the issue.
- **FR-012**: System MUST remove opportunities that are no longer present in the source during a successful refresh.

#### Conversational Interface

- **FR-013**: System MUST expose search, filter, detail, and statistics capabilities as discrete tools callable from a conversational assistant.
- **FR-014**: System MUST return results in a structured format that enables the conversational assistant to present them clearly to the user.
- **FR-015**: System MUST return informative messages (not raw errors) when no results are found, when an opportunity ID is invalid, or when the service is unavailable.

#### Data Completeness

- **FR-016**: For each opportunity, the system MUST store: unique identifier, title, full description, town, country, start date, end date, topics, eligible volunteer countries, participant profile, deadline (when available), and a direct link to the opportunity's ESC portal page.
- **FR-017**: System MUST index opportunity data for semantic search using all text fields (title, description, topics, location, and participant profile), enabling queries based on meaning rather than keyword matching alone.

### Key Entities

- **Opportunity**: A volunteering placement offered through the European Solidarity Corps. Attributes: unique identifier (opid), title, full description, town, country, start date, end date, topic tags, eligible volunteer countries, participant profile requirements, application deadline (when available), and a direct link to the ESC portal page.
- **Search Query**: A user's request combining optional natural language text with optional structured filters (country, topics, date range) and a result limit.
- **Search Result**: A ranked list of opportunity summaries (title, location, dates, short description, relevance indicator) returned in response to a query.
- **Opportunity Statistics**: Aggregate counts and breakdowns of available opportunities by country, topic, and deadline proximity, plus the timestamp of the most recent data refresh.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Alex can describe what she's looking for in plain language and receive relevant results within 5 seconds.
- **SC-002**: Semantic search returns opportunities that a human would consider relevant in at least 8 out of 10 test queries (assessed by Alex or project owner).
- **SC-003**: Alex can complete a full search-to-decision workflow (discover, filter, review details) in under 2 minutes of conversation.
- **SC-004**: 100% of currently open ESC opportunities eligible for Netherlands residents are captured in the system after each daily refresh.
- **SC-005**: Data is never more than 25 hours old under normal operating conditions (accounting for refresh duration).
- **SC-006**: Alex reports that the tool is faster and easier to use than the official ESC portal for finding volunteering opportunities.
- **SC-007**: System correctly handles all edge cases (no results, invalid IDs, service unavailable) with clear, non-technical messages — zero unhandled errors visible to Alex.

## Assumptions

- Alex is the sole user; multi-user access, authentication, and authorization are out of scope.
- Alex is a Netherlands resident; opportunity eligibility is filtered to NL-eligible by default and this is not user-configurable.
- Alex uses Claude Desktop with MCP server support already configured and connected.
- The ESC portal API at `POST ``https://youth.europa.eu/api/rest/eyp/v1/search_en` remains available and maintains its current response format (undocumented API — no stability guarantee).
- The ESC portal's individual opportunity pages remain scrapable for deadline extraction; if the page structure changes, deadlines may become temporarily unavailable.
- Opportunity data is refreshed daily; real-time sync is not required and minor staleness (up to 24 hours) is acceptable.
- The system runs on home infrastructure (Proxmox container) with stable network connectivity; high availability and disaster recovery are out of scope.
- The conversational experience (how results are presented, follow-up questions, etc.) is handled by Claude's native capabilities; the system provides tools and structured data, not conversation management.
- Application tracking, bookmark/favorites, and notification of new opportunities are out of scope for this feature.
- The total number of NL-eligible opportunities is expected to be in the low thousands, well within the capacity of the search infrastructure.
