"""Databricks Vector Search and Delta table query functions."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from databricks.sdk import WorkspaceClient
from databricks.vector_search.client import VectorSearchClient

from esc_opportunity_search.models import Opportunity

log = logging.getLogger("esc_opportunity_search")


def _get_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Required environment variable {name} is not set")
    return value


def get_table_name() -> str:
    """Full three-level Delta table name: catalog.schema.esc_opportunities."""
    catalog = _get_env("DATABRICKS_CATALOG")
    schema = _get_env("DATABRICKS_SCHEMA")
    return f"{catalog}.{schema}.esc_opportunities"


def get_index_name() -> str:
    """Full three-level Vector Search index name."""
    return os.environ.get(
        "DATABRICKS_VS_INDEX",
        f"{_get_env('DATABRICKS_CATALOG')}.{_get_env('DATABRICKS_SCHEMA')}.esc_search",
    )


def get_vector_search_client() -> VectorSearchClient:
    """Create a VectorSearchClient using DATABRICKS_HOST + DATABRICKS_TOKEN env vars."""
    return VectorSearchClient(
        workspace_url=_get_env("DATABRICKS_HOST"),
        personal_access_token=_get_env("DATABRICKS_TOKEN"),
    )


def get_workspace_client() -> WorkspaceClient:
    """Create a Databricks WorkspaceClient for Delta table operations."""
    return WorkspaceClient(
        host=_get_env("DATABRICKS_HOST"),
        token=_get_env("DATABRICKS_TOKEN"),
    )


def _get_warehouse_id(ws: WorkspaceClient) -> str:
    """Get the first available SQL warehouse ID."""
    warehouses = list(ws.warehouses.list())
    if not warehouses:
        raise RuntimeError("No SQL warehouses available.")
    return warehouses[0].id


def _get_vs_endpoint_name(vsc: VectorSearchClient) -> str:
    """Get the Vector Search endpoint name."""
    return os.environ.get("DATABRICKS_VS_ENDPOINT", "esc-search-endpoint")


def _parse_json_field(value: Any) -> list[str]:
    """Parse a JSON-encoded list field from Delta table string storage."""
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else [str(parsed)]
        except (json.JSONDecodeError, TypeError):
            return [value] if value else []
    return []


def _row_to_opportunity(row: dict[str, Any]) -> Opportunity:
    """Convert a raw Delta table row dict to an Opportunity model."""
    return Opportunity(
        opid=str(row.get("opid", "")),
        title=row.get("title", ""),
        description=row.get("description", ""),
        town=row.get("town", ""),
        country=row.get("country", ""),
        date_start=row.get("date_start", ""),
        date_end=row.get("date_end", ""),
        has_no_deadline=bool(row.get("has_no_deadline", False)),
        deadline=row.get("deadline"),
        topics=_parse_json_field(row.get("topics", "[]")),
        countries=_parse_json_field(row.get("countries", "[]")),
        volunteer_countries=_parse_json_field(row.get("volunteer_countries", "[]")),
        participant_profile=row.get("participant_profile", ""),
        url=row.get("url", ""),
        search_text=row.get("search_text", ""),
    )


# Columns returned in search/filter results
SUMMARY_COLUMNS = [
    "opid", "title", "description", "town", "country",
    "date_start", "date_end", "topics", "url",
]

ALL_COLUMNS = [
    "opid", "title", "description", "town", "country",
    "date_start", "date_end", "has_no_deadline", "deadline",
    "topics", "countries", "volunteer_countries", "participant_profile",
    "url", "search_text", "fetched_at",
]


# ---------------------------------------------------------------------------
# T016: Semantic search (US1)
# ---------------------------------------------------------------------------

def semantic_search(
    query: str,
    limit: int = 10,
    country: str | None = None,
    topics: list[str] | None = None,
    date_start_after: str | None = None,
    date_start_before: str | None = None,
) -> tuple[list[tuple[Opportunity, float]], int]:
    """Semantic search over opportunities via Databricks Vector Search.

    Returns (results, total_available) where results is a list of (Opportunity, score) tuples.
    """
    limit = max(1, min(50, limit))
    vsc = get_vector_search_client()
    endpoint_name = _get_vs_endpoint_name(vsc)
    index = vsc.get_index(endpoint_name=endpoint_name, index_name=get_index_name())

    # Build filter dict for Databricks Vector Search filter pushdown
    filters: dict[str, Any] = {}
    if country:
        filters["country"] = country
    # Note: topic and date filtering via VS filter pushdown is limited;
    # we do post-filtering for these below.

    result = index.similarity_search(
        query_text=query,
        columns=ALL_COLUMNS,
        num_results=min(limit * 3, 150),  # Over-fetch to allow post-filtering
        filters=filters if filters else None,
    )

    # VS SDK response: {"manifest": {"columns": [...]}, "result": {"data_array": [...], "row_count": N}}
    rows = result.get("result", {}).get("data_array", [])
    column_names = [c["name"] for c in result.get("manifest", {}).get("columns", [])]

    opportunities: list[tuple[Opportunity, float]] = []
    for row in rows:
        row_dict = dict(zip(column_names, row))
        score = row_dict.pop("score", 0.0)
        opp = _row_to_opportunity(row_dict)

        # Post-filter by topics
        if topics:
            opp_topics_lower = [t.lower() for t in opp.topics]
            if not any(t.lower() in opp_topics_lower for t in topics):
                continue

        # Post-filter by date range
        if date_start_after and opp.date_start < date_start_after:
            continue
        if date_start_before and opp.date_start > date_start_before:
            continue

        opportunities.append((opp, float(score)))
        if len(opportunities) >= limit:
            break

    total = result.get("result", {}).get("row_count", len(opportunities))
    return opportunities, total


# ---------------------------------------------------------------------------
# T020: Structured filtering (US2)
# ---------------------------------------------------------------------------

def filter_query(
    country: str | None = None,
    topics: list[str] | None = None,
    date_start_after: str | None = None,
    date_start_before: str | None = None,
    deadline_before: str | None = None,
    limit: int = 20,
    sort_by: str = "date_start",
) -> tuple[list[Opportunity], int]:
    """Structured filter query against the Delta table.

    Returns (results, total_matching).
    """
    limit = max(1, min(50, limit))
    table = get_table_name()
    ws = get_workspace_client()
    warehouse_id = _get_warehouse_id(ws)

    # Build WHERE clauses
    conditions: list[str] = []
    if country:
        conditions.append(f"country = '{country}'")
    if topics:
        # topics is stored as JSON string; use LIKE for matching
        topic_conditions = [f"topics LIKE '%{t}%'" for t in topics]
        conditions.append(f"({' OR '.join(topic_conditions)})")
    if date_start_after:
        conditions.append(f"date_start >= '{date_start_after}'")
    if date_start_before:
        conditions.append(f"date_start <= '{date_start_before}'")
    if deadline_before:
        # FR-010a: Only filter by deadline for opportunities with actual dates,
        # not "Rolling/Open". Rolling/Open opportunities are never excluded by deadline filters.
        conditions.append(f"deadline IS NOT NULL AND deadline != 'Rolling/Open' AND deadline <= '{deadline_before}'")

    where_clause = " AND ".join(conditions) if conditions else "1=1"

    # Validate sort_by
    valid_sorts = {"date_start", "deadline", "title"}
    if sort_by not in valid_sorts:
        sort_by = "date_start"

    # Count query
    count_stmt = f"SELECT COUNT(*) as cnt FROM {table} WHERE {where_clause}"
    count_result = ws.statement_execution.execute_statement(
        warehouse_id=warehouse_id,
        statement=count_stmt,
        wait_timeout="50s",
    )
    total = 0
    if count_result.result and count_result.result.data_array:
        total = int(count_result.result.data_array[0][0])

    # Data query
    cols = ", ".join(ALL_COLUMNS)
    data_stmt = f"SELECT {cols} FROM {table} WHERE {where_clause} ORDER BY {sort_by} LIMIT {limit}"
    data_result = ws.statement_execution.execute_statement(
        warehouse_id=warehouse_id,
        statement=data_stmt,
        wait_timeout="50s",
    )

    opportunities: list[Opportunity] = []
    if data_result.result and data_result.result.data_array:
        for row in data_result.result.data_array:
            row_dict = dict(zip(ALL_COLUMNS, row))
            opportunities.append(_row_to_opportunity(row_dict))

    return opportunities, total


# ---------------------------------------------------------------------------
# T024: Single opportunity lookup (US3)
# ---------------------------------------------------------------------------

def get_opportunity_by_opid(opid: str) -> Opportunity | None:
    """Look up a single opportunity by its opid."""
    table = get_table_name()
    ws = get_workspace_client()
    warehouse_id = _get_warehouse_id(ws)

    cols = ", ".join(ALL_COLUMNS)
    escaped_opid = opid.replace("'", "''")
    stmt = f"SELECT {cols} FROM {table} WHERE opid = '{escaped_opid}' LIMIT 1"

    result = ws.statement_execution.execute_statement(
        warehouse_id=warehouse_id,
        statement=stmt,
        wait_timeout="50s",
    )

    if result.result and result.result.data_array:
        row = result.result.data_array[0]
        row_dict = dict(zip(ALL_COLUMNS, row))
        return _row_to_opportunity(row_dict)

    return None


# ---------------------------------------------------------------------------
# T027: Aggregate statistics (US4)
# ---------------------------------------------------------------------------

def get_aggregate_stats() -> dict[str, Any]:
    """Get summary statistics about all available opportunities."""
    table = get_table_name()
    ws = get_workspace_client()
    warehouse_id = _get_warehouse_id(ws)

    def _execute(stmt: str) -> list[list]:
        r = ws.statement_execution.execute_statement(
            warehouse_id=warehouse_id,
            statement=stmt,
            wait_timeout="50s",
        )
        if r.result and r.result.data_array:
            return r.result.data_array
        return []

    # Total count
    total_rows = _execute(f"SELECT COUNT(*) FROM {table}")
    total = int(total_rows[0][0]) if total_rows else 0

    # By country
    country_rows = _execute(
        f"SELECT country, COUNT(*) as cnt FROM {table} GROUP BY country ORDER BY cnt DESC"
    )
    by_country = {row[0]: int(row[1]) for row in country_rows}

    # By topic (topics is a JSON array stored as string)
    # Explode the JSON array and count
    topic_rows = _execute(
        f"SELECT topic, COUNT(*) as cnt FROM ("
        f"  SELECT explode(from_json(topics, 'ARRAY<STRING>')) as topic FROM {table}"
        f") GROUP BY topic ORDER BY cnt DESC"
    )
    by_topic = {row[0]: int(row[1]) for row in topic_rows}

    # Closing soon (deadline within 30 days)
    cutoff = (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%d/%m/%Y")
    # FR-010a: Exclude "Rolling/Open" from closing_soon — only show real deadlines
    closing_rows = _execute(
        f"SELECT opid, title, deadline, url FROM {table} "
        f"WHERE deadline IS NOT NULL AND deadline != 'Rolling/Open' AND has_no_deadline = FALSE "
        f"ORDER BY deadline ASC LIMIT 20"
    )
    closing_soon = []
    now = datetime.now(timezone.utc)
    for row in closing_rows:
        deadline_str = row[2]
        try:
            deadline_date = datetime.strptime(deadline_str[:10], "%d/%m/%Y").replace(tzinfo=timezone.utc)
            days_remaining = (deadline_date - now).days
            if days_remaining <= 30:
                closing_soon.append({
                    "opid": row[0],
                    "title": row[1],
                    "deadline": deadline_str,
                    "days_remaining": max(0, days_remaining),
                    "url": row[3],
                })
        except (ValueError, TypeError):
            continue

    # Last refreshed
    refresh_rows = _execute(f"SELECT MAX(fetched_at) FROM {table}")
    last_refreshed = refresh_rows[0][0] if refresh_rows and refresh_rows[0][0] else None

    return {
        "total_opportunities": total,
        "by_country": by_country,
        "by_topic": by_topic,
        "closing_soon": closing_soon,
        "last_refreshed": last_refreshed,
    }
