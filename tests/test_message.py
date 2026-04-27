# File: tests/test_message.py
# Purpose: Unit tests for AegisMessage serialization and defaults.

import pytest
from uuid import UUID
from datetime import datetime, timedelta, timezone

from aegis.schemas import AegisMessage, MessageType, Priority

# Helper for consistent UTC timestamps
def get_utc_now():
    if hasattr(timezone, 'utc'):
        return datetime.now(timezone.utc)
    else:
        return datetime.utcnow()

def test_aegis_message_creation_with_required_fields():
    """Verify that a message can be created with only the required fields."""
    msg = AegisMessage(
        source_agent="test_source",
        target_agent="test_target",
        message_type=MessageType.REQUEST,
        tenant_id="t-1",
        user_id="u-1",
        action="test.action",
    )
    assert msg.source_agent == "test_source"
    assert msg.action == "test.action"
    assert msg.priority == Priority.NORMAL # Default value
    assert msg.payload == {} # Default value

def test_aegis_message_auto_generates_fields():
    """Check that message_id and timestamp are auto-generated."""
    msg1 = AegisMessage(
        source_agent="test", target_agent="test", message_type="request",
        tenant_id="t", user_id="u", action="a"
    )
    msg2 = AegisMessage(
        source_agent="test", target_agent="test", message_type="request",
        tenant_id="t", user_id="u", action="a"
    )

    # Verify message_id is a valid UUID string
    assert isinstance(UUID(msg1.message_id), UUID)
    assert msg1.message_id != msg2.message_id

    # Verify timestamp is a recent datetime object
    assert isinstance(msg1.timestamp, datetime)
    assert get_utc_now() - msg1.timestamp < timedelta(seconds=2)

def test_aegis_message_serialization_deserialization_roundtrip():
    """Ensure a message can be serialized to JSON and back without data loss."""
    original_msg = AegisMessage(
        source_agent="forge",
        target_agent="oracle",
        message_type=MessageType.REQUEST,
        tenant_id="tenant-abc",
        user_id="user-123",
        action="generate.code",
        payload={"language": "python", "spec": "create a function"},
        priority=Priority.HIGH,
        correlation_id="corr-456"
    )

    # Pydantic v2 serialization
    json_str = original_msg.model_dump_json()

    # Pydantic v2 deserialization
    rehydrated_msg = AegisMessage.model_validate_json(json_str)

    assert original_msg == rehydrated_msg
    assert rehydrated_msg.priority == Priority.HIGH
    assert rehydrated_msg.payload["language"] == "python"

def test_invalid_message_type_raises_error():
    """Verify that an invalid message_type fails validation."""
    with pytest.raises(ValueError):
        AegisMessage(
            source_agent="test", target_agent="test", message_type="INVALID_TYPE",
            tenant_id="t", user_id="u", action="a"
        )
