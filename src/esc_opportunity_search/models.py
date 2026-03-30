"""Pydantic models for ESC opportunity data."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, computed_field


class Opportunity(BaseModel):
    """A volunteering placement from the European Solidarity Corps."""

    opid: str
    title: str = ""
    description: str = ""
    town: str = ""
    country: str = ""
    date_start: str = ""
    date_end: str = ""
    has_no_deadline: bool = False
    deadline: str | None = None
    topics: list[str] = Field(default_factory=list)
    countries: list[str] = Field(default_factory=list)
    volunteer_countries: list[str] = Field(default_factory=list)
    participant_profile: str = ""
    url: str = ""
    search_text: str = ""
    fetched_at: datetime | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def description_preview(self) -> str:
        """First 200 characters of description for search result summaries."""
        if len(self.description) <= 200:
            return self.description
        return self.description[:200] + "..."

    def to_search_result(self, relevance_score: float | None = None) -> dict[str, Any]:
        """Format as a search result summary for MCP tool responses."""
        result: dict[str, Any] = {
            "opid": self.opid,
            "title": self.title,
            "town": self.town,
            "country": self.country,
            "date_start": self.date_start,
            "date_end": self.date_end,
            "topics": self.topics,
            "description_preview": self.description_preview,
            "url": self.url,
        }
        if relevance_score is not None:
            result["relevance_score"] = round(relevance_score, 4)
        return result

    def to_filter_result(self) -> dict[str, Any]:
        """Format for filter_opportunities response."""
        return {
            "opid": self.opid,
            "title": self.title,
            "town": self.town,
            "country": self.country,
            "date_start": self.date_start,
            "date_end": self.date_end,
            "topics": self.topics,
            "deadline": self.deadline,
            "description_preview": self.description_preview,
            "url": self.url,
        }

    def to_detail(self) -> dict[str, Any]:
        """Format for get_opportunity_details response (all fields)."""
        return {
            "opid": self.opid,
            "title": self.title,
            "description": self.description,
            "town": self.town,
            "country": self.country,
            "date_start": self.date_start,
            "date_end": self.date_end,
            "topics": self.topics,
            "volunteer_countries": self.volunteer_countries,
            "participant_profile": self.participant_profile,
            "deadline": self.deadline,
            "has_no_deadline": self.has_no_deadline,
            "url": self.url,
        }


class RefreshLog(BaseModel):
    """Tracks a single data refresh run."""

    run_id: str
    started_at: datetime
    completed_at: datetime | None = None
    status: str = "running"  # running, success, failed
    opportunities_fetched: int = 0
    opportunities_added: int = 0
    opportunities_removed: int = 0
    deadlines_scraped: int = 0
    deadlines_failed: int = 0
    pages_fetched: int = 0
    error_message: str | None = None

    def to_log_line(self) -> str:
        """Serialize as a single JSON line for the ingestion log file."""
        return json.dumps(self.model_dump(mode="json"), default=str)
