"""ESC opportunity data ingestion pipeline.

Fetches all NL-eligible volunteering opportunities from the ESC portal API,
scrapes deadlines from individual opportunity pages, and writes the complete
dataset to a Databricks Delta table with Vector Search index sync.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import uuid
from datetime import datetime, timezone

import httpx

from esc_opportunity_search import setup_logging
from esc_opportunity_search.models import Opportunity, RefreshLog
from esc_opportunity_search.search import (
    get_index_name,
    get_table_name,
    get_vector_search_client,
    get_workspace_client,
)

log = logging.getLogger("esc_opportunity_search")

ESC_API_URL = "https://youth.europa.eu/api/rest/eyp/v1/search_en"
ESC_OPPORTUNITY_URL = "https://youth.europa.eu/solidarity/opportunity/{opid}_en"
PAGE_SIZE = 500

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

DEADLINE_PATTERN = re.compile(
    r"Application deadline:\s*(\d{2}/\d{2}/\d{4}(?:\s+\d{2}:\d{2})?)"
)

REQUEST_BODY_TEMPLATE: dict = {
    "type": "Opportunity",
    "filters": {
        "status": "open",
        "funding_programme": {"id": [1, 2, 3, 4, 5, 6, 7, 8]},
        "volunteer_countries": ["NL"],
    },
    "fields": [
        "opid", "title", "description", "town", "country",
        "date_start", "date_end", "has_no_deadline", "topics",
        "countries", "volunteer_countries", "participant_profile",
    ],
    "sort": {"created": "desc"},
    "size": PAGE_SIZE,
}


# ---------------------------------------------------------------------------
# T008: ESC API paginated fetch
# ---------------------------------------------------------------------------

async def fetch_all_opportunities(client: httpx.AsyncClient) -> list[dict]:
    """Fetch all NL-eligible open opportunities from the ESC API, paginating through all results."""
    all_hits: list[dict] = []
    offset = 0
    today = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

    while True:
        body = {**REQUEST_BODY_TEMPLATE, "from": offset}
        resp = await client.post(ESC_API_URL, json=body)
        resp.raise_for_status()
        data = resp.json()

        hits = data.get("hits", {}).get("hits", [])
        if not hits:
            break

        for hit in hits:
            source = hit.get("_source", {})
            date_end = source.get("date_end", "")
            date_start = source.get("date_start", "")
            # Filter expired: keep if date_end >= today, or no date_end and date_start >= today
            if date_end and date_end < today:
                continue
            if not date_end and date_start and date_start < today:
                continue
            all_hits.append(source)

        log.info("Fetched page at offset %d: %d hits (%d kept)", offset, len(hits), len(all_hits))

        if len(hits) < PAGE_SIZE:
            break
        offset += PAGE_SIZE

    return all_hits


# ---------------------------------------------------------------------------
# T009: Deadline scraping
# ---------------------------------------------------------------------------

async def scrape_deadline(client: httpx.AsyncClient, opid: str, max_retries: int = 3) -> str | None:
    """Fetch an opportunity page and extract the application deadline.

    Retries with exponential backoff on 429 (Too Many Requests) responses.
    """
    url = ESC_OPPORTUNITY_URL.format(opid=opid)
    for attempt in range(max_retries + 1):
        try:
            resp = await client.get(url)
            if resp.status_code == 429:
                backoff = 2 ** (attempt + 1)  # 2, 4, 8 seconds
                log.warning("Rate limited scraping opid %s (attempt %d/%d), backing off %ds",
                            opid, attempt + 1, max_retries + 1, backoff)
                await asyncio.sleep(backoff)
                continue
            resp.raise_for_status()
            match = DEADLINE_PATTERN.search(resp.text)
            if match:
                return match.group(1)
            return None
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429 and attempt < max_retries:
                backoff = 2 ** (attempt + 1)
                await asyncio.sleep(backoff)
                continue
            log.warning("Failed to scrape deadline for opid %s: %s", opid, exc)
            return None
        except Exception as exc:
            log.warning("Failed to scrape deadline for opid %s: %s", opid, exc)
            return None
    return None


async def scrape_deadlines(
    client: httpx.AsyncClient,
    opportunities: list[dict],
) -> dict[str, str | None]:
    """Scrape deadlines for opportunities that have them.

    Uses 2-second base delay between requests with exponential backoff on 429s.
    """
    deadlines: dict[str, str | None] = {}
    to_scrape = [o for o in opportunities if not o.get("has_no_deadline", False)]
    log.info("Scraping deadlines for %d opportunities (skipping %d with no deadline)",
             len(to_scrape), len(opportunities) - len(to_scrape))

    for i, opp in enumerate(to_scrape):
        opid = str(opp["opid"])
        deadlines[opid] = await scrape_deadline(client, opid)
        if (i + 1) % 100 == 0:
            log.info("Scraped %d/%d deadlines", i + 1, len(to_scrape))
        await asyncio.sleep(5)  # Base rate limit: 1 request per 5 seconds (ESC portal aggressive 429s)

    return deadlines


# ---------------------------------------------------------------------------
# T010: search_text computation + URL construction
# ---------------------------------------------------------------------------

def build_opportunity(source: dict, deadline: str | None) -> Opportunity:
    """Convert a raw API source dict into an Opportunity model with computed fields.

    Per FR-010a: opportunities with has_no_deadline=true or where deadline scraping
    failed get deadline set to "Rolling/Open" (never None).
    """
    opid = str(source.get("opid", ""))
    topics = source.get("topics", [])
    if isinstance(topics, list):
        topics_str = ", ".join(str(t) for t in topics)
    else:
        topics_str = str(topics)

    town = source.get("town", "")
    country = source.get("country", "")
    title = source.get("title", "")
    description = source.get("description", "")
    participant_profile = source.get("participant_profile", "")
    has_no_deadline = source.get("has_no_deadline", False)

    # FR-010a: Rolling/Open for missing or failed deadlines
    if has_no_deadline or deadline is None:
        deadline = "Rolling/Open"

    search_text = " ".join(filter(None, [
        title, description, topics_str, town, country, participant_profile,
    ]))

    return Opportunity(
        opid=opid,
        title=title,
        description=description,
        town=town,
        country=country,
        date_start=source.get("date_start", ""),
        date_end=source.get("date_end", ""),
        has_no_deadline=has_no_deadline,
        deadline=deadline,
        topics=source.get("topics", []),
        countries=source.get("countries", []),
        volunteer_countries=source.get("volunteer_countries", []),
        participant_profile=participant_profile,
        url=ESC_OPPORTUNITY_URL.format(opid=opid),
        search_text=search_text,
        fetched_at=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# T011: Delta table full-replace write
# ---------------------------------------------------------------------------

def write_to_delta_table(opportunities: list[Opportunity], dry_run: bool = False) -> None:
    """Write the complete opportunity dataset to the Delta table (full replace)."""
    table_name = get_table_name()

    if dry_run:
        log.info("[DRY RUN] Would write %d opportunities to %s", len(opportunities), table_name)
        return

    ws = get_workspace_client()

    # Convert to list of dicts for DataFrame creation
    rows = []
    for opp in opportunities:
        row = opp.model_dump(mode="json")
        # Convert list fields to JSON strings for Delta table compatibility
        row["topics"] = json.dumps(row["topics"])
        row["countries"] = json.dumps(row["countries"])
        row["volunteer_countries"] = json.dumps(row["volunteer_countries"])
        rows.append(row)

    log.info("Writing %d opportunities to Delta table %s (overwrite)", len(rows), table_name)

    # Use the Databricks SDK statement execution API to write data
    # First, create/replace the table with the data
    if rows:
        # Build INSERT statement with VALUES
        columns = list(rows[0].keys())
        col_names = ", ".join(columns)

        # Use CTAS pattern: write to a temp view then overwrite the table
        # For simplicity with the SDK, use the SQL statement execution API
        sql_client = ws.statement_execution

        # Truncate and re-insert (atomic within a transaction)
        sql_client.execute_statement(
            warehouse_id=_get_warehouse_id(ws),
            statement=f"CREATE TABLE IF NOT EXISTS {table_name} ("
                      f"opid STRING NOT NULL, title STRING, description STRING, "
                      f"town STRING, country STRING, date_start STRING, date_end STRING, "
                      f"has_no_deadline BOOLEAN, deadline STRING, topics STRING, "
                      f"countries STRING, volunteer_countries STRING, "
                      f"participant_profile STRING, url STRING, search_text STRING, "
                      f"fetched_at STRING"
                      f") USING DELTA",
            wait_timeout="50s",
        )

        # Overwrite with INSERT OVERWRITE
        values_parts = []
        for row in rows:
            vals = []
            for col in columns:
                v = row[col]
                if v is None:
                    vals.append("NULL")
                elif isinstance(v, bool):
                    vals.append("TRUE" if v else "FALSE")
                else:
                    escaped = str(v).replace("'", "''")
                    vals.append(f"'{escaped}'")
            values_parts.append(f"({', '.join(vals)})")

        # Split into batches to avoid SQL statement size limits
        batch_size = 50
        for i in range(0, len(values_parts), batch_size):
            batch = values_parts[i:i + batch_size]
            mode = "INTO" if i > 0 else "OVERWRITE"
            statement = f"INSERT {mode} {table_name} ({col_names}) VALUES {', '.join(batch)}"
            sql_client.execute_statement(
                warehouse_id=_get_warehouse_id(ws),
                statement=statement,
                wait_timeout="50s",
            )
            log.info("Wrote batch %d-%d of %d", i, min(i + batch_size, len(rows)), len(rows))


def _get_warehouse_id(ws: WorkspaceClient) -> str:
    """Get the first available SQL warehouse ID."""
    warehouses = list(ws.warehouses.list())
    if not warehouses:
        raise RuntimeError("No SQL warehouses available. Create one in the Databricks workspace.")
    return warehouses[0].id


# ---------------------------------------------------------------------------
# T012: Vector Search index sync
# ---------------------------------------------------------------------------

def trigger_index_sync(dry_run: bool = False) -> None:
    """Trigger a sync of the Vector Search index after a successful Delta table write."""
    if dry_run:
        log.info("[DRY RUN] Would trigger Vector Search index sync")
        return

    index_name = get_index_name()
    vsc = get_vector_search_client()

    try:
        endpoint_name = _get_vs_endpoint_name(vsc)
        index = vsc.get_index(endpoint_name=endpoint_name, index_name=index_name)
        index.sync()
        log.info("Triggered Vector Search index sync for %s", index_name)
    except Exception as exc:
        log.error("Failed to trigger index sync: %s", exc)
        raise


def _get_vs_endpoint_name(vsc: VectorSearchClient) -> str:
    """Get the first available Vector Search endpoint name."""
    endpoints = vsc.list_endpoints().get("endpoints", [])
    if not endpoints:
        raise RuntimeError("No Vector Search endpoints available.")
    return endpoints[0]["name"]


# ---------------------------------------------------------------------------
# T013: RefreshLog tracking
# ---------------------------------------------------------------------------

def log_refresh(refresh_log: RefreshLog) -> None:
    """Append a structured JSON log entry for the refresh run."""
    log.info(
        "Refresh %s: status=%s fetched=%d added=%d removed=%d deadlines=%d/%d",
        refresh_log.run_id,
        refresh_log.status,
        refresh_log.opportunities_fetched,
        refresh_log.opportunities_added,
        refresh_log.opportunities_removed,
        refresh_log.deadlines_scraped,
        refresh_log.deadlines_failed,
    )
    # Also write structured JSON line to the log
    log.info("REFRESH_LOG: %s", refresh_log.to_log_line())


# ---------------------------------------------------------------------------
# T014: Main entry point
# ---------------------------------------------------------------------------

async def run_ingestion(dry_run: bool = False) -> RefreshLog:
    """Run the full ingestion pipeline."""
    refresh = RefreshLog(
        run_id=str(uuid.uuid4()),
        started_at=datetime.now(timezone.utc),
    )

    try:
        async with httpx.AsyncClient(
            headers={"User-Agent": BROWSER_UA, "Content-Type": "application/json"},
            timeout=60.0,
        ) as client:
            # Fetch all opportunities
            raw_opportunities = await fetch_all_opportunities(client)
            refresh.opportunities_fetched = len(raw_opportunities)
            refresh.pages_fetched = (len(raw_opportunities) // PAGE_SIZE) + 1
            log.info("Fetched %d opportunities total", len(raw_opportunities))

            # Scrape deadlines
            deadlines = await scrape_deadlines(client, raw_opportunities)
            refresh.deadlines_scraped = sum(1 for d in deadlines.values() if d is not None)
            refresh.deadlines_failed = sum(1 for d in deadlines.values() if d is None)

        # Build Opportunity models
        opportunities = [
            build_opportunity(source, deadlines.get(str(source.get("opid", ""))))
            for source in raw_opportunities
        ]

        # Write to Delta table
        write_to_delta_table(opportunities, dry_run=dry_run)
        refresh.opportunities_added = len(opportunities)

        # Trigger index sync
        trigger_index_sync(dry_run=dry_run)

        refresh.status = "success"
        refresh.completed_at = datetime.now(timezone.utc)

    except Exception as exc:
        refresh.status = "failed"
        refresh.error_message = str(exc)
        refresh.completed_at = datetime.now(timezone.utc)
        log.error("Ingestion failed: %s", exc)

    log_refresh(refresh)
    return refresh


def main() -> None:
    """CLI entry point for the ingestion pipeline."""
    parser = argparse.ArgumentParser(description="ESC Opportunity Search - Data Ingestion")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and process data without writing to Databricks")
    args = parser.parse_args()

    setup_logging("ingestion")
    log.info("Starting ESC opportunity ingestion (dry_run=%s)", args.dry_run)

    refresh = asyncio.run(run_ingestion(dry_run=args.dry_run))

    if refresh.status == "success":
        log.info("Ingestion completed successfully: %d opportunities", refresh.opportunities_fetched)
    else:
        log.error("Ingestion failed: %s", refresh.error_message)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
