# aegis/web/core/filters.py
# Filter parameter parsing for Mission Control APIs

from typing import Any, Optional, List, Dict
from datetime import datetime, timezone
from pydantic import BaseModel, Field, field_validator
from fastapi import Query


class FilterParams(BaseModel):
    """Common filter parameters for list endpoints."""

    # Text search
    q: Optional[str] = Field(default=None, description="Full-text search query")

    # Agent filters
    source_agent: Optional[str] = Field(default=None, description="Filter by source agent")
    target_agent: Optional[str] = Field(default=None, description="Filter by target agent")
    agent: Optional[str] = Field(default=None, description="Filter by either source or target agent")

    # Message type filter
    message_type: Optional[str] = Field(default=None, description="Filter by message type (request, response, event, error)")

    # Priority filter
    priority: Optional[str] = Field(default=None, description="Filter by priority (low, normal, high, critical)")

    # Status filter (for messages in consumer groups)
    status: Optional[str] = Field(default=None, description="Filter by status (pending, acked, claimed, expired, dead_letter)")

    # Correlation ID filter
    correlation_id: Optional[str] = Field(default=None, description="Filter by correlation ID")

    # Date range filters
    start: Optional[datetime] = Field(default=None, description="Start timestamp (ISO 8601)")
    end: Optional[datetime] = Field(default=None, description="End timestamp (ISO 8601)")

    # Stream filter
    stream: Optional[str] = Field(default=None, description="Filter by stream name")

    # Pagination (handled separately but included for completeness)
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=500)

    @field_validator("start", "end", mode="before")
    @classmethod
    def parse_datetime(cls, v: Any) -> Optional[datetime]:
        if v is None or v == "":
            return None
        if isinstance(v, datetime):
            return v
        if isinstance(v, str):
            # Try parsing ISO format, add UTC if naive
            dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        raise ValueError(f"Invalid datetime: {v}")

    def to_redis_filters(self) -> Dict[str, Any]:
        """Convert to dict for Redis query building."""
        filters = {}
        if self.q:
            filters["q"] = self.q
        if self.source_agent:
            filters["source_agent"] = self.source_agent
        if self.target_agent:
            filters["target_agent"] = self.target_agent
        if self.agent:
            filters["agent"] = self.agent
        if self.message_type:
            filters["message_type"] = self.message_type
        if self.priority:
            filters["priority"] = self.priority
        if self.status:
            filters["status"] = self.status
        if self.correlation_id:
            filters["correlation_id"] = self.correlation_id
        if self.start:
            filters["start"] = self.start
        if self.end:
            filters["end"] = self.end
        if self.stream:
            filters["stream"] = self.stream
        return filters

    def to_query_params(self) -> Dict[str, str]:
        """Convert to URL query parameters for HTMX links."""
        params = {}
        for key, value in self.model_dump(exclude_none=True).items():
            if key in ("page", "page_size"):
                continue
            if isinstance(value, datetime):
                params[key] = value.isoformat()
            elif value is not None:
                params[key] = str(value)
        return params


def get_filter_params(
    q: Optional[str] = Query(None, description="Search query"),
    source_agent: Optional[str] = Query(None, description="Source agent filter"),
    target_agent: Optional[str] = Query(None, description="Target agent filter"),
    agent: Optional[str] = Query(None, description="Any agent filter"),
    message_type: Optional[str] = Query(None, description="Message type filter"),
    priority: Optional[str] = Query(None, description="Priority filter"),
    status: Optional[str] = Query(None, description="Status filter"),
    correlation_id: Optional[str] = Query(None, description="Correlation ID filter"),
    start: Optional[str] = Query(None, description="Start date (ISO 8601)"),
    end: Optional[str] = Query(None, description="End date (ISO 8601)"),
    stream: Optional[str] = Query(None, description="Stream filter"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
) -> FilterParams:
    """FastAPI dependency for filter parameters."""
    return FilterParams(
        q=q,
        source_agent=source_agent,
        target_agent=target_agent,
        agent=agent,
        message_type=message_type,
        priority=priority,
        status=status,
        correlation_id=correlation_id,
        start=start,
        end=end,
        stream=stream,
        page=page,
        page_size=page_size,
    )


def parse_filters(params: Dict[str, Any]) -> FilterParams:
    """Parse filter dict into FilterParams model."""
    return FilterParams(**params)