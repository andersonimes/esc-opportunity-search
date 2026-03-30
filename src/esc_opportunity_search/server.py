"""MCP server exposing ESC opportunity search tools to Claude."""

from __future__ import annotations

import json
import logging
import os

from mcp.server.fastmcp import FastMCP

from esc_opportunity_search import setup_logging
from esc_opportunity_search.search import (
    filter_query,
    get_aggregate_stats,
    get_opportunity_by_opid,
    semantic_search,
)

setup_logging("server")
log = logging.getLogger("esc_opportunity_search")

mcp = FastMCP("esc-opportunity-search")


# ---------------------------------------------------------------------------
# T017 + T018: search_opportunities (US1)
# ---------------------------------------------------------------------------

@mcp.tool()
async def search_opportunities(
    query: str,
    limit: int = 10,
    country: str | None = None,
    topics: list[str] | None = None,
    date_start_after: str | None = None,
    date_start_before: str | None = None,
) -> str:
    """Search ESC volunteering opportunities using natural language.

    Args:
        query: Natural language search query (e.g., "environmental volunteering in Spain")
        limit: Maximum number of results to return (1-50, default 10)
        country: Filter by destination country code (e.g., "ES", "IT")
        topics: Filter by topic tags (e.g., ["Environment", "Digital"])
        date_start_after: Only opportunities starting on or after this date (YYYY-MM-DD)
        date_start_before: Only opportunities starting on or before this date (YYYY-MM-DD)
    """
    limit = max(1, min(50, limit))

    try:
        results, total = semantic_search(
            query=query,
            limit=limit,
            country=country,
            topics=topics,
            date_start_after=date_start_after,
            date_start_before=date_start_before,
        )
    except Exception as exc:
        log.error("Search failed: %s", exc)
        return json.dumps({
            "error": "service_unavailable",
            "message": "The search service is temporarily unavailable. Please try again later.",
        })

    if not results:
        filters_desc = []
        if country:
            filters_desc.append(f"country={country}")
        if topics:
            filters_desc.append(f"topics={topics}")
        if date_start_after:
            filters_desc.append(f"starting after {date_start_after}")
        filter_msg = f" with filters: {', '.join(filters_desc)}" if filters_desc else ""
        return json.dumps({
            "results": [],
            "total_available": 0,
            "query": query,
            "filters_applied": {k: v for k, v in [("country", country), ("topics", topics), ("date_start_after", date_start_after), ("date_start_before", date_start_before)] if v},
            "message": f"No opportunities found matching '{query}'{filter_msg}. Try broadening your search.",
        })

    return json.dumps({
        "results": [opp.to_search_result(score) for opp, score in results],
        "total_available": total,
        "query": query,
        "filters_applied": {k: v for k, v in [("country", country), ("topics", topics), ("date_start_after", date_start_after), ("date_start_before", date_start_before)] if v},
    })


# ---------------------------------------------------------------------------
# T021 + T022: filter_opportunities (US2)
# ---------------------------------------------------------------------------

@mcp.tool()
async def filter_opportunities(
    country: str | None = None,
    topics: list[str] | None = None,
    date_start_after: str | None = None,
    date_start_before: str | None = None,
    deadline_before: str | None = None,
    limit: int = 20,
    sort_by: str = "date_start",
) -> str:
    """Filter ESC volunteering opportunities by specific criteria. At least one filter must be provided.

    Args:
        country: Destination country code (e.g., "ES", "IT")
        topics: Topic tags to match (e.g., ["Environment", "Digital"])
        date_start_after: Opportunities starting on or after (YYYY-MM-DD)
        date_start_before: Opportunities starting on or before (YYYY-MM-DD)
        deadline_before: Opportunities with deadline before this date (YYYY-MM-DD)
        limit: Maximum results (1-50, default 20)
        sort_by: Sort field: "date_start", "deadline", or "title"
    """
    if not any([country, topics, date_start_after, date_start_before, deadline_before]):
        return json.dumps({
            "error": "no_filters",
            "message": "At least one filter parameter must be provided. Try specifying a country, topic, date range, or deadline.",
        })

    limit = max(1, min(50, limit))

    try:
        results, total = filter_query(
            country=country,
            topics=topics,
            date_start_after=date_start_after,
            date_start_before=date_start_before,
            deadline_before=deadline_before,
            limit=limit,
            sort_by=sort_by,
        )
    except Exception as exc:
        log.error("Filter query failed: %s", exc)
        return json.dumps({
            "error": "service_unavailable",
            "message": "The search service is temporarily unavailable. Please try again later.",
        })

    filters_applied = {k: v for k, v in [
        ("country", country), ("topics", topics),
        ("date_start_after", date_start_after), ("date_start_before", date_start_before),
        ("deadline_before", deadline_before),
    ] if v}

    if not results:
        return json.dumps({
            "results": [],
            "total_matching": 0,
            "filters_applied": filters_applied,
            "message": "No opportunities match the specified filters. Try broadening your criteria.",
        })

    return json.dumps({
        "results": [opp.to_filter_result() for opp in results],
        "total_matching": total,
        "filters_applied": filters_applied,
    })


# ---------------------------------------------------------------------------
# T025: get_opportunity_details (US3)
# ---------------------------------------------------------------------------

@mcp.tool()
async def get_opportunity_details(opid: str) -> str:
    """Get full details for a specific ESC volunteering opportunity.

    Args:
        opid: Unique opportunity identifier
    """
    try:
        opp = get_opportunity_by_opid(opid)
    except Exception as exc:
        log.error("Detail lookup failed for opid %s: %s", opid, exc)
        return json.dumps({
            "error": "service_unavailable",
            "message": "The search service is temporarily unavailable. Please try again later.",
        })

    if opp is None:
        return json.dumps({
            "error": "not_found",
            "message": f"No opportunity found with ID '{opid}'. It may have been removed or the ID may be incorrect.",
        })

    return json.dumps(opp.to_detail())


# ---------------------------------------------------------------------------
# T028: get_stats (US4)
# ---------------------------------------------------------------------------

@mcp.tool()
async def get_stats() -> str:
    """Get summary statistics about all available ESC volunteering opportunities.

    Returns total count, breakdown by country and topic, opportunities with approaching deadlines, and when the data was last refreshed.
    """
    try:
        stats = get_aggregate_stats()
    except Exception as exc:
        log.error("Stats query failed: %s", exc)
        return json.dumps({
            "error": "service_unavailable",
            "message": "The search service is temporarily unavailable. Please try again later.",
        })

    return json.dumps(stats)


# ---------------------------------------------------------------------------
# API key auth middleware for remote access
# ---------------------------------------------------------------------------

def _check_api_key(request) -> bool:
    """Validate the API key from the Authorization header."""
    api_key = os.environ.get("ESC_API_KEY")
    if not api_key:
        return True  # No key configured = no auth required (local dev)
    auth_header = request.headers.get("Authorization", "")
    return auth_header == f"Bearer {api_key}"


def main() -> None:
    """Entry point for the MCP server.

    Transport is selected via ESC_TRANSPORT env var:
    - "stdio" (default): For local use / Claude Desktop subprocess
    - "sse": For remote access over HTTP (set ESC_PORT for port, default 8080)
    """
    transport = os.environ.get("ESC_TRANSPORT", "stdio")

    if transport == "sse":
        port = int(os.environ.get("ESC_PORT", "8080"))
        log.info("Starting MCP server on port %d (SSE transport)", port)
        mcp.run(transport="sse", host="0.0.0.0", port=port)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
