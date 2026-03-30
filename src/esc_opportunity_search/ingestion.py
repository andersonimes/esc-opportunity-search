"""ESC opportunity data ingestion pipeline.

Fetches all NL-eligible volunteering opportunities from the ESC portal API,
scrapes deadlines from individual opportunity pages, and upserts the dataset
into a Databricks Delta table with Vector Search index sync.

Design principles:
- **Incremental**: Only scrapes deadlines for opportunities that don't already
  have a real (non-Rolling/Open) deadline stored.
- **Idempotent**: Running twice produces the same result. Existing data is
  preserved and updated, not replaced.
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
    ALL_COLUMNS,
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
# Step 1: Fetch all opportunities from ESC API
# ---------------------------------------------------------------------------

async def fetch_all_opportunities(client: httpx.AsyncClient) -> list[dict]:
    """Fetch all NL-eligible open opportunities, paginating through all results."""
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
# Step 2: Load existing deadlines from Delta table
# ---------------------------------------------------------------------------

def load_existing_deadlines(dry_run: bool = False) -> dict[str, str]:
    """Load opid -> deadline mapping for all opportunities already in the table.

    Returns only real deadlines (not 'Rolling/Open'), so we know which opids
    still need scraping.
    """
    if dry_run:
        return {}

    table = get_table_name()
    ws = get_workspace_client()
    warehouse_id = _get_warehouse_id(ws)

    try:
        result = ws.statement_execution.execute_statement(
            warehouse_id=warehouse_id,
            statement=f"SELECT opid, deadline FROM {table} WHERE deadline IS NOT NULL AND deadline != 'Rolling/Open'",
            wait_timeout="50s",
        )
        if result.result and result.result.data_array:
            return {row[0]: row[1] for row in result.result.data_array}
    except Exception as exc:
        log.warning("Could not load existing deadlines (table may not exist yet): %s", exc)

    return {}


# ---------------------------------------------------------------------------
# Step 3: Scrape deadlines (incremental — skip already-known)
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
                backoff = 2 ** (attempt + 1)
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


async def scrape_deadlines_incremental(
    client: httpx.AsyncClient,
    opportunities: list[dict],
    existing_deadlines: dict[str, str],
) -> dict[str, str | None]:
    """Scrape deadlines only for opportunities that need it.

    Skips:
    - Opportunities with has_no_deadline=true (they're Rolling/Open by definition)
    - Opportunities whose opid already has a real deadline in existing_deadlines
    """
    deadlines: dict[str, str | None] = {}

    # Carry forward existing real deadlines
    for opid, deadline in existing_deadlines.items():
        deadlines[opid] = deadline

    # Determine which opids need scraping
    to_scrape = []
    skipped_no_deadline = 0
    skipped_already_known = 0
    for opp in opportunities:
        opid = str(opp.get("opid", ""))
        if opp.get("has_no_deadline", False):
            skipped_no_deadline += 1
            continue
        if opid in existing_deadlines:
            skipped_already_known += 1
            continue
        to_scrape.append(opp)

    log.info(
        "Deadline scraping: %d to scrape, %d skipped (no deadline), %d skipped (already known)",
        len(to_scrape), skipped_no_deadline, skipped_already_known,
    )

    for i, opp in enumerate(to_scrape):
        opid = str(opp["opid"])
        deadlines[opid] = await scrape_deadline(client, opid)
        if (i + 1) % 100 == 0:
            log.info("Scraped %d/%d deadlines", i + 1, len(to_scrape))
        await asyncio.sleep(5)  # Base rate limit: 5s between requests

    return deadlines


# ---------------------------------------------------------------------------
# Step 4: Build Opportunity models
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
# Step 5: Upsert to Delta table (idempotent)
# ---------------------------------------------------------------------------

def _get_warehouse_id(ws) -> str:
    """Get the first available SQL warehouse ID."""
    warehouses = list(ws.warehouses.list())
    if not warehouses:
        raise RuntimeError("No SQL warehouses available.")
    return warehouses[0].id


def _sql_value(v) -> str:
    """Convert a Python value to a SQL literal."""
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    escaped = str(v).replace("'", "''")
    return f"'{escaped}'"


def _opp_to_row(opp: Opportunity) -> dict:
    """Convert an Opportunity to a Delta-table-compatible row dict."""
    row = opp.model_dump(mode="json")
    row["topics"] = json.dumps(row["topics"])
    row["countries"] = json.dumps(row["countries"])
    row["volunteer_countries"] = json.dumps(row["volunteer_countries"])
    # Exclude computed fields not in the table schema
    row.pop("description_preview", None)
    return row


def upsert_opportunities(opportunities: list[Opportunity], dry_run: bool = False) -> tuple[int, int]:
    """Upsert opportunities into the Delta table using MERGE.

    Returns (upserted_count, removed_count).
    """
    table = get_table_name()

    if dry_run:
        log.info("[DRY RUN] Would upsert %d opportunities to %s", len(opportunities), table)
        return len(opportunities), 0

    ws = get_workspace_client()
    wh_id = _get_warehouse_id(ws)

    def _execute(stmt: str) -> None:
        r = ws.statement_execution.execute_statement(
            warehouse_id=wh_id, statement=stmt, wait_timeout="50s",
        )
        if r.status.error:
            raise RuntimeError(f"SQL error: {r.status.error.message}")

    # Ensure table exists
    _execute(
        f"CREATE TABLE IF NOT EXISTS {table} ("
        f"opid STRING NOT NULL, title STRING, description STRING, "
        f"town STRING, country STRING, date_start STRING, date_end STRING, "
        f"has_no_deadline BOOLEAN, deadline STRING, topics STRING, "
        f"countries STRING, volunteer_countries STRING, "
        f"participant_profile STRING, url STRING, search_text STRING, "
        f"fetched_at STRING"
        f") USING DELTA"
    )

    # Upsert in batches using a temp view + MERGE
    batch_size = 50
    upserted = 0
    for i in range(0, len(opportunities), batch_size):
        batch = opportunities[i:i + batch_size]
        rows = [_opp_to_row(opp) for opp in batch]
        columns = [c for c in ALL_COLUMNS]

        # Build VALUES clause
        values_parts = []
        for row in rows:
            vals = [_sql_value(row.get(col)) for col in columns]
            values_parts.append(f"({', '.join(vals)})")

        col_names = ", ".join(columns)
        col_defs = ", ".join(f"{c} STRING" for c in columns)

        # MERGE: update if exists, insert if not
        update_set = ", ".join(
            f"target.{c} = source.{c}" for c in columns if c != "opid"
        )
        insert_cols = ", ".join(columns)
        insert_vals = ", ".join(f"source.{c}" for c in columns)

        merge_sql = f"""
            MERGE INTO {table} AS target
            USING (
                SELECT * FROM VALUES {', '.join(values_parts)}
                AS t({col_names})
            ) AS source
            ON target.opid = source.opid
            WHEN MATCHED THEN UPDATE SET {update_set}
            WHEN NOT MATCHED THEN INSERT ({insert_cols}) VALUES ({insert_vals})
        """
        _execute(merge_sql)
        upserted += len(batch)
        log.info("Upserted batch %d-%d of %d", i + 1, min(i + batch_size, len(opportunities)), len(opportunities))

    return upserted, 0


def remove_stale_opportunities(current_opportunities: list[Opportunity], dry_run: bool = False) -> tuple[int, int]:
    """Remove opportunities from Delta table that are no longer in the API response.

    Returns (0, removed_count).
    """
    if dry_run:
        return 0, 0

    table = get_table_name()
    ws = get_workspace_client()
    wh_id = _get_warehouse_id(ws)

    api_opids = {opp.opid for opp in current_opportunities}
    if not api_opids:
        return 0, 0

    opid_list = ", ".join(f"'{opid}'" for opid in api_opids)
    count_r = ws.statement_execution.execute_statement(
        warehouse_id=wh_id,
        statement=f"SELECT COUNT(*) FROM {table} WHERE opid NOT IN ({opid_list})",
        wait_timeout="50s",
    )
    removed = 0
    if count_r.result and count_r.result.data_array:
        removed = int(count_r.result.data_array[0][0])

    if removed > 0:
        def _execute(stmt: str) -> None:
            r = ws.statement_execution.execute_statement(
                warehouse_id=wh_id, statement=stmt, wait_timeout="50s",
            )
            if r.status.error:
                raise RuntimeError(f"SQL error: {r.status.error.message}")
        _execute(f"DELETE FROM {table} WHERE opid NOT IN ({opid_list})")
        log.info("Removed %d stale opportunities", removed)

    return 0, removed


# ---------------------------------------------------------------------------
# Step 6: Vector Search index sync
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
        # Non-fatal: data is in Delta table even if sync fails
        log.warning("Failed to trigger index sync (sync manually from Databricks UI): %s", exc)


def _get_vs_endpoint_name(vsc) -> str:
    """Get the Vector Search endpoint name."""
    import os
    return os.environ.get("DATABRICKS_VS_ENDPOINT", "esc-search-endpoint")


# ---------------------------------------------------------------------------
# Step 7: RefreshLog tracking
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
    log.info("REFRESH_LOG: %s", refresh_log.to_log_line())


# ---------------------------------------------------------------------------
# Main pipeline (incremental + idempotent)
# ---------------------------------------------------------------------------

async def run_ingestion(dry_run: bool = False) -> RefreshLog:
    """Run the incremental ingestion pipeline with streaming upserts.

    1. Fetch all opportunities from ESC API (always full fetch — it's fast)
    2. Immediately upsert all opportunities (with Rolling/Open deadlines for unknown)
    3. Load existing deadlines from Delta table (skip re-scraping known ones)
    4. Scrape deadlines incrementally, upserting every 100 scrapes
    5. Remove stale opportunities no longer in API
    6. Trigger Vector Search index sync

    Data is queryable from step 2 onward — scraping just enriches deadlines.
    """
    refresh = RefreshLog(
        run_id=str(uuid.uuid4()),
        started_at=datetime.now(timezone.utc),
    )

    try:
        # Step 1: Fetch from API
        async with httpx.AsyncClient(
            headers={"User-Agent": BROWSER_UA, "Content-Type": "application/json"},
            timeout=60.0,
        ) as client:
            raw_opportunities = await fetch_all_opportunities(client)
            refresh.opportunities_fetched = len(raw_opportunities)
            refresh.pages_fetched = (len(raw_opportunities) // PAGE_SIZE) + 1
            log.info("Fetched %d opportunities total", len(raw_opportunities))

            # Step 2: Upsert all opportunities immediately (deadlines as Rolling/Open)
            # This makes all data queryable right away
            initial_opportunities = [
                build_opportunity(source, None)
                for source in raw_opportunities
            ]
            upserted, _ = upsert_opportunities(initial_opportunities, dry_run=dry_run)
            refresh.opportunities_added = upserted
            log.info("Initial upsert complete — all %d opportunities now queryable", upserted)

            # Step 3: Load existing deadlines
            existing_deadlines = load_existing_deadlines(dry_run=dry_run)
            log.info("Loaded %d existing deadlines from Delta table", len(existing_deadlines))

            # Step 4: Scrape deadlines incrementally, upserting as we go
            # Build a lookup from opid -> raw source for re-building opportunities
            source_by_opid = {str(s.get("opid", "")): s for s in raw_opportunities}

            deadlines = dict(existing_deadlines)  # Start with known deadlines
            scrape_batch: list[Opportunity] = []
            new_scraped = 0

            to_scrape = [
                opp for opp in raw_opportunities
                if not opp.get("has_no_deadline", False)
                and str(opp.get("opid", "")) not in existing_deadlines
            ]
            skipped_no_deadline = sum(1 for o in raw_opportunities if o.get("has_no_deadline", False))
            skipped_known = sum(
                1 for o in raw_opportunities
                if not o.get("has_no_deadline", False)
                and str(o.get("opid", "")) in existing_deadlines
            )
            log.info(
                "Deadline scraping: %d to scrape, %d skipped (no deadline), %d skipped (already known)",
                len(to_scrape), skipped_no_deadline, skipped_known,
            )

            for i, opp in enumerate(to_scrape):
                opid = str(opp["opid"])
                deadline = await scrape_deadline(client, opid)
                deadlines[opid] = deadline

                if deadline is not None:
                    new_scraped += 1

                # Re-build opportunity with the scraped deadline and queue for upsert
                scrape_batch.append(build_opportunity(opp, deadline))

                # Upsert every 100 scrapes
                if len(scrape_batch) >= 100:
                    upsert_opportunities(scrape_batch, dry_run=dry_run)
                    log.info("Scraped and upserted %d/%d deadlines", i + 1, len(to_scrape))
                    scrape_batch = []

                await asyncio.sleep(5)

            # Upsert remaining batch
            if scrape_batch:
                upsert_opportunities(scrape_batch, dry_run=dry_run)
                log.info("Scraped and upserted final batch (%d/%d deadlines)", len(to_scrape), len(to_scrape))

            refresh.deadlines_scraped = new_scraped + len(existing_deadlines)
            refresh.deadlines_failed = sum(1 for d in deadlines.values() if d is None)

        # Step 5: Remove stale opportunities
        all_opportunities = [
            build_opportunity(source, deadlines.get(str(source.get("opid", ""))))
            for source in raw_opportunities
        ]
        _, removed = remove_stale_opportunities(all_opportunities, dry_run=dry_run)
        refresh.opportunities_removed = removed

        # Step 6: Trigger index sync
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
    parser.add_argument("--dry-run", action="store_true",
                        help="Fetch and process data without writing to Databricks")
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
