# File: aegis/schemas/message.py
# Purpose: Defines the core communication contract for all agents.

import sys
from datetime import datetime
from enum import Enum
from typing import Any, Optional
from uuid import uuid4

from pydantic import BaseModel, Field, ConfigDict

# Compatibility for Python < 3.12 `utcnow` deprecation
if sys.version_info >= (3, 12):
    from datetime import UTC
    def utcnow():
        return datetime.now(UTC)
else:
    # still available pre-3.12
    utcnow = datetime.utcnow

class MessageType(str, Enum):
    """Defines the intent of the message."""
    REQUEST = "request"
    RESPONSE = "response"
    EVENT = "event"
    ERROR = "error"

class Priority(str, Enum):
    """Defines the message processing priority."""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"

class AegisMessage(BaseModel):
    """
    The canonical message structure for all inter-agent communication.
    Conforms to Genesis Spec Part II, Section 2.2.
    """
    message_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="Unique identifier for the message."
    )
    correlation_id: Optional[str] = Field(
        default=None,
        description="ID of the message this one is responding to or related to."
    )
    source_agent: str = Field(description="The ID of the agent sending the message.")
    target_agent: str = Field(description="The ID of the intended recipient agent.")
    message_type: MessageType = Field(description="The type of the message.")
    tenant_id: str = Field(description="The tenant context for this message.")
    user_id: str = Field(description="The user context for this message.")
    action: str = Field(description="The specific action the target agent should perform.")
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="A flexible payload containing action-specific data."
    )
    priority: Priority = Field(
        default=Priority.NORMAL,
        description="Message processing priority."
    )
    timestamp: datetime = Field(
        default_factory=utcnow,
        description="UTC timestamp of when the message was created."
    )
    ttl_seconds: Optional[int] = Field(
        default=300,
        description="Time-to-live in seconds before the message expires."
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Extra metadata, e.g., for tracing or security."
    )

    model_config = ConfigDict(
        use_enum_values=True,
        from_attributes=True,
    )
