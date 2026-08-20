# aegis/web/routes/redis_bus/models.py
# Pydantic models for Redis Bus Observability API

from datetime import datetime
from typing import Any, Optional, List, Dict, Literal
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict
from enum import Enum


class MessageType(str, Enum):
    REQUEST = "request"
    RESPONSE = "response"
    EVENT = "event"
    ERROR = "error"


class Priority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class MessageStatus(str, Enum):
    PENDING = "pending"
    ACKNOWLEDGED = "acknowledged"
    CLAIMED = "claimed"
    EXPIRED = "expired"
    DEAD_LETTER = "dead_letter"
    PROCESSING = "processing"


class StreamSummary(BaseModel):
    """Summary of a Redis stream."""
    name: str
    agent_id: str
    is_broadcast: bool = False
    length: int = 0
    consumer_groups: int = 0
    pending_count: int = 0
    oldest_entry_id: Optional[str] = None
    newest_entry_id: Optional[str] = None
    oldest_timestamp: Optional[datetime] = None
    newest_timestamp: Optional[datetime] = None
    msgs_per_sec: float = 0.0
    first_entry_id: Optional[str] = None
    last_entry_id: Optional[str] = None


class StreamDetail(StreamSummary):
    """Detailed stream information including consumer groups."""
    consumer_groups_detail: List["ConsumerGroupInfo"] = []
    recent_messages: List["MessageListItem"] = []


class ConsumerGroupInfo(BaseModel):
    """Consumer group information."""
    name: str
    stream: str
    consumers: int = 0
    pending: int = 0
    lag: int = 0  # messages behind
    oldest_pending_age_ms: Optional[int] = None
    consumers_detail: List["ConsumerInfo"] = []


class ConsumerInfo(BaseModel):
    """Individual consumer information."""
    name: str
    pending: int = 0
    idle_ms: int = 0
    last_delivered_id: Optional[str] = None


class MessageListItem(BaseModel):
    """Lightweight message for list views."""
    entry_id: str
    message_id: str
    correlation_id: Optional[str] = None
    source_agent: str
    target_agent: str
    message_type: MessageType
    priority: Priority
    action: str
    timestamp: datetime
    status: MessageStatus = MessageStatus.PENDING
    delivery_count: int = 1
    size_bytes: int = 0
    token_estimate: int = 0
    age_seconds: float = 0
    has_token_usage: bool = False


class MessageDetail(BaseModel):
    """Full message detail for inspection."""
    entry_id: str
    stream: str
    message_id: str
    correlation_id: Optional[str] = None
    source_agent: str
    target_agent: str
    message_type: MessageType
    priority: Priority
    tenant_id: str
    user_id: str
    action: str
    payload: Dict[str, Any]
    metadata: Dict[str, Any]
    timestamp: datetime
    ttl_seconds: Optional[int] = None
    # Computed fields
    size_bytes: int = 0
    age_seconds: float = 0
    token_estimate: int = 0
    token_usage: Optional["TokenUsage"] = None
    status: MessageStatus = MessageStatus.PENDING
    delivery_count: int = 1
    processing_latency_ms: Optional[float] = None
    retry_count: int = 0
    consumer_group: Optional[str] = None
    consumer: Optional[str] = None


class TokenUsage(BaseModel):
    """Token usage information."""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: Optional[float] = None
    model: Optional[str] = None


class PipelineState(BaseModel):
    """Pipeline health state."""
    in_pipeline: int = 0           # Pending messages across all streams
    done_last_hour: int = 0        # Acknowledged in last hour
    stuck: int = 0                 # Pending > 5 min with retries
    abandoned: int = 0             # Expired or max retries exceeded
    dead_letter: int = 0           # In dead letter queue
    by_agent: Dict[str, "AgentPipelineState"] = {}
    by_stream: Dict[str, "StreamPipelineState"] = {}


class AgentPipelineState(BaseModel):
    """Pipeline state per agent."""
    agent_id: str
    in_pipeline: int = 0
    done_last_hour: int = 0
    stuck: int = 0
    abandoned: int = 0
    avg_latency_ms: float = 0.0
    error_rate: float = 0.0


class StreamPipelineState(BaseModel):
    """Pipeline state per stream."""
    stream: str
    agent_id: str
    in_pipeline: int = 0
    done_last_hour: int = 0
    stuck: int = 0
    abandoned: int = 0
    oldest_pending_age_sec: float = 0


class TokenChartDataPoint(BaseModel):
    """Single data point for token chart."""
    entry_id: str
    message_id: str
    timestamp: datetime
    source_agent: str
    target_agent: str
    action: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    estimated: bool = True


class CumulativeChartDataPoint(BaseModel):
    """Single data point for cumulative chart."""
    timestamp: datetime
    cumulative_tokens: int = 0
    cumulative_requests: int = 0
    by_agent: Dict[str, "AgentCumulativeData"] = {}
    by_type: Dict[str, "TypeCumulativeData"] = {}


class AgentCumulativeData(BaseModel):
    """Cumulative data per agent."""
    tokens: int = 0
    requests: int = 0


class TypeCumulativeData(BaseModel):
    """Cumulative data per message type."""
    tokens: int = 0
    requests: int = 0


class CumulativeChartResponse(BaseModel):
    """Response for cumulative chart endpoint."""
    data_points: List[CumulativeChartDataPoint]
    granularity: str  # minute, hour, day
    date_range: Dict[str, datetime]
    total_tokens: int = 0
    total_requests: int = 0
    agents: List[str] = []
    message_types: List[str] = []


class TokenChartResponse(BaseModel):
    """Response for per-message token chart."""
    stream: str
    data_points: List[TokenChartDataPoint]
    total_messages: int
    total_tokens: int
    avg_tokens_per_message: float


class OverviewStats(BaseModel):
    """Global overview statistics."""
    total_streams: int = 0
    total_messages: int = 0
    total_pending: int = 0
    total_consumer_groups: int = 0
    active_agents: int = 0
    msgs_per_sec: float = 0.0
    avg_latency_ms: float = 0.0
    error_rate: float = 0.0
    total_tokens_24h: int = 0
    total_requests_24h: int = 0


class MessageActionRequest(BaseModel):
    """Request for message actions."""
    action: Literal["delete", "reassign", "move", "retry", "acknowledge"]
    target_agent: Optional[str] = None
    target_stream: Optional[str] = None
    reason: Optional[str] = None


class MessageActionResponse(BaseModel):
    """Response for message actions."""
    success: bool
    message: str
    entry_id: Optional[str] = None
    new_entry_id: Optional[str] = None


class StreamFilters(BaseModel):
    """Filters for stream listing."""
    agent_id: Optional[str] = None
    include_broadcast: bool = True
    min_messages: int = 0
    has_pending: Optional[bool] = None


class MessageFilters(BaseModel):
    """Filters for message listing."""
    message_type: Optional[MessageType] = None
    priority: Optional[Priority] = None
    status: Optional[MessageStatus] = None
    source_agent: Optional[str] = None
    target_agent: Optional[str] = None
    correlation_id: Optional[str] = None
    action: Optional[str] = None
    start: Optional[datetime] = None
    end: Optional[datetime] = None
    min_tokens: Optional[int] = None
    max_tokens: Optional[int] = None
    has_token_usage: Optional[bool] = None
    search: Optional[str] = None  # Search in payload/action


# Forward references
StreamDetail.model_rebuild()
MessageListItem.model_rebuild()
MessageDetail.model_rebuild()