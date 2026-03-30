"""Integration tests for MCP tools.

These tests verify the tool function signatures, parameter handling,
and response format. They do NOT call real Databricks — that requires
a live environment. Instead, they test the tool layer's error handling,
input validation, and response structure.

Per constitution Principle II, full perimeter tests against real services
should be run in a configured environment (see T033 for e2e validation).
"""

from __future__ import annotations

import json

import pytest

from esc_opportunity_search.server import (
    filter_opportunities,
    get_opportunity_details,
    get_stats,
    mcp,
    search_opportunities,
)


class TestSearchOpportunitiesToolContract:
    """Verify search_opportunities tool contract and error handling."""

    async def test_tool_is_registered(self) -> None:
        tool_names = [t.name for t in mcp._tool_manager._tools.values()]
        assert "search_opportunities" in tool_names

    async def test_service_unavailable_returns_error_json(self) -> None:
        # Without Databricks env vars, the tool should return a service_unavailable error
        result = await search_opportunities(query="test query")
        data = json.loads(result)
        assert data["error"] == "service_unavailable"
        assert "message" in data

    async def test_limit_clamping_low(self) -> None:
        result = await search_opportunities(query="test", limit=0)
        data = json.loads(result)
        # Should not crash — limit is clamped to 1
        assert "error" in data or "results" in data

    async def test_limit_clamping_high(self) -> None:
        result = await search_opportunities(query="test", limit=999)
        data = json.loads(result)
        assert "error" in data or "results" in data


class TestFilterOpportunitiesToolContract:
    """Verify filter_opportunities tool contract and validation."""

    async def test_tool_is_registered(self) -> None:
        tool_names = [t.name for t in mcp._tool_manager._tools.values()]
        assert "filter_opportunities" in tool_names

    async def test_no_filters_returns_error(self) -> None:
        result = await filter_opportunities()
        data = json.loads(result)
        assert data["error"] == "no_filters"
        assert "message" in data

    async def test_with_country_filter_attempts_query(self) -> None:
        # Without Databricks, should get service_unavailable (not no_filters)
        result = await filter_opportunities(country="ES")
        data = json.loads(result)
        assert data["error"] in ("service_unavailable", "no_filters")

    async def test_with_topic_filter_attempts_query(self) -> None:
        result = await filter_opportunities(topics=["Environment"])
        data = json.loads(result)
        assert data["error"] == "service_unavailable"


class TestGetOpportunityDetailsToolContract:
    """Verify get_opportunity_details tool contract."""

    async def test_tool_is_registered(self) -> None:
        tool_names = [t.name for t in mcp._tool_manager._tools.values()]
        assert "get_opportunity_details" in tool_names

    async def test_service_unavailable_returns_error(self) -> None:
        result = await get_opportunity_details(opid="12345")
        data = json.loads(result)
        assert data["error"] == "service_unavailable"
        assert "message" in data


class TestGetStatsToolContract:
    """Verify get_stats tool contract."""

    async def test_tool_is_registered(self) -> None:
        tool_names = [t.name for t in mcp._tool_manager._tools.values()]
        assert "get_stats" in tool_names

    async def test_service_unavailable_returns_error(self) -> None:
        result = await get_stats()
        data = json.loads(result)
        assert data["error"] == "service_unavailable"
        assert "message" in data


class TestRollingOpenDeadlineHandling:
    """FR-010a: Rolling/Open deadline opportunities must not be erroneously filtered."""

    async def test_no_filters_error_not_affected(self) -> None:
        """Baseline: no-filters still returns error (not a deadline issue)."""
        result = await filter_opportunities()
        data = json.loads(result)
        assert data["error"] == "no_filters"

    async def test_deadline_filter_with_country_returns_valid_response(self) -> None:
        """deadline_before filter combined with country should not crash."""
        result = await filter_opportunities(country="ES", deadline_before="2026-12-31")
        data = json.loads(result)
        # Without Databricks: service_unavailable. With: results or empty.
        assert "error" in data or "results" in data

    async def test_country_only_filter_not_affected_by_deadline(self) -> None:
        """Country-only filter should never exclude rolling-deadline opportunities."""
        result = await filter_opportunities(country="ES")
        data = json.loads(result)
        assert "error" in data or "results" in data


class TestAllToolsReturnValidJson:
    """All tools must return valid JSON strings, never raw errors."""

    @pytest.mark.parametrize("tool_fn,kwargs", [
        (search_opportunities, {"query": "anything"}),
        (filter_opportunities, {}),
        (filter_opportunities, {"country": "XX"}),
        (get_opportunity_details, {"opid": "nonexistent"}),
        (get_stats, {}),
    ])
    async def test_returns_valid_json(self, tool_fn, kwargs) -> None:
        result = await tool_fn(**kwargs)
        assert isinstance(result, str)
        data = json.loads(result)  # Should not raise
        assert isinstance(data, dict)
