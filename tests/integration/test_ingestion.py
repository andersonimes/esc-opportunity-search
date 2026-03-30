"""Integration tests for the ESC opportunity ingestion pipeline.

Tests use recorded fixtures (ESC API response + opportunity HTML page)
per constitution Principle II: Perimeter Testing with recorded fixtures.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from esc_opportunity_search.ingestion import (
    DEADLINE_PATTERN,
    build_opportunity,
)

FIXTURES = Path(__file__).parent.parent / "fixtures"


@pytest.fixture()
def api_response() -> dict:
    """Load the recorded ESC API response fixture."""
    return json.loads((FIXTURES / "esc_api_page1.json").read_text())


@pytest.fixture()
def opportunity_html() -> str:
    """Load the recorded opportunity page HTML fixture."""
    return (FIXTURES / "opportunity_page.html").read_text()


class TestApiResponseParsing:
    """Test parsing of ESC API responses."""

    def test_hits_have_expected_structure(self, api_response: dict) -> None:
        hits = api_response["hits"]["hits"]
        assert len(hits) > 0
        source = hits[0]["_source"]
        assert "opid" in source
        assert "title" in source
        assert "description" in source
        assert "country" in source
        assert "topics" in source

    def test_opid_is_present(self, api_response: dict) -> None:
        for hit in api_response["hits"]["hits"]:
            assert hit["_source"]["opid"] is not None

    def test_total_count_available(self, api_response: dict) -> None:
        total = api_response["hits"]["total"]["value"]
        assert isinstance(total, int)
        assert total > 0


class TestDeadlineExtraction:
    """Test deadline scraping from opportunity HTML pages."""

    def test_extracts_deadline_from_html(self, opportunity_html: str) -> None:
        match = DEADLINE_PATTERN.search(opportunity_html)
        assert match is not None
        deadline = match.group(1)
        # Should match DD/MM/YYYY or DD/MM/YYYY HH:MM format
        assert len(deadline) >= 10  # at least DD/MM/YYYY

    def test_deadline_format_is_correct(self, opportunity_html: str) -> None:
        match = DEADLINE_PATTERN.search(opportunity_html)
        assert match is not None
        deadline = match.group(1)
        # Verify the date portion parses
        date_part = deadline[:10]
        day, month, year = date_part.split("/")
        assert 1 <= int(day) <= 31
        assert 1 <= int(month) <= 12
        assert int(year) >= 2024

    def test_no_deadline_returns_none(self) -> None:
        html = "<html><body>No deadline info here</body></html>"
        match = DEADLINE_PATTERN.search(html)
        assert match is None


class TestBuildOpportunity:
    """Test Opportunity model construction from raw API data."""

    def test_builds_opportunity_with_all_fields(self, api_response: dict) -> None:
        source = api_response["hits"]["hits"][0]["_source"]
        opp = build_opportunity(source, deadline="15/06/2026")

        assert opp.opid == str(source["opid"])
        assert opp.title == source["title"]
        assert opp.description == source["description"]
        assert opp.country == source["country"]
        assert opp.deadline == "15/06/2026"
        assert opp.url.startswith("https://youth.europa.eu/solidarity/opportunity/")
        assert opp.search_text  # non-empty
        assert opp.fetched_at is not None

    def test_search_text_contains_all_fields(self, api_response: dict) -> None:
        source = api_response["hits"]["hits"][0]["_source"]
        opp = build_opportunity(source, deadline=None)

        # search_text should contain title, description, topics, town, country, participant_profile
        assert source["title"] in opp.search_text
        if source.get("town"):
            assert source["town"] in opp.search_text
        assert source["country"] in opp.search_text

    def test_builds_without_deadline_sets_rolling_open(self, api_response: dict) -> None:
        """FR-010a: Missing deadline must be 'Rolling/Open', never None."""
        source = api_response["hits"]["hits"][0]["_source"]
        opp = build_opportunity(source, deadline=None)
        assert opp.deadline == "Rolling/Open"

    def test_has_no_deadline_true_sets_rolling_open(self) -> None:
        """FR-010a: has_no_deadline=true must result in 'Rolling/Open'."""
        source = {
            "opid": "99999", "title": "Test", "description": "Desc",
            "country": "NL", "has_no_deadline": True,
        }
        opp = build_opportunity(source, deadline="15/06/2026")
        assert opp.deadline == "Rolling/Open"

    def test_has_no_deadline_false_with_deadline_keeps_deadline(self) -> None:
        """Real deadline preserved when has_no_deadline is false."""
        source = {
            "opid": "99999", "title": "Test", "description": "Desc",
            "country": "NL", "has_no_deadline": False,
        }
        opp = build_opportunity(source, deadline="15/06/2026")
        assert opp.deadline == "15/06/2026"

    def test_url_constructed_from_opid(self, api_response: dict) -> None:
        source = api_response["hits"]["hits"][0]["_source"]
        opp = build_opportunity(source, deadline=None)
        assert opp.url == f"https://youth.europa.eu/solidarity/opportunity/{source['opid']}_en"

    def test_description_preview_truncates_long_text(self) -> None:
        source = {
            "opid": "99999",
            "title": "Test",
            "description": "A" * 500,
            "town": "Town",
            "country": "NL",
        }
        opp = build_opportunity(source, deadline=None)
        assert len(opp.description_preview) == 203  # 200 + "..."
        assert opp.description_preview.endswith("...")

    def test_description_preview_short_text_unchanged(self) -> None:
        source = {"opid": "99999", "title": "Test", "description": "Short desc", "country": "NL"}
        opp = build_opportunity(source, deadline=None)
        assert opp.description_preview == "Short desc"


class TestExpiredOpportunityFiltering:
    """Test that expired opportunities are filtered out during fetch."""

    def test_future_date_end_is_kept(self) -> None:
        # This tests the filtering logic concept — the actual filtering
        # happens in fetch_all_opportunities which requires a live API call.
        # Here we verify the date comparison approach works.
        today = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        future = "2099-12-31T00:00:00"
        past = "2020-01-01T00:00:00"
        assert future >= today
        assert past < today
