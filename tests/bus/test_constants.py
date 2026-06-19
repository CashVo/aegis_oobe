# tests/bus/test_constants.py
# Unit tests for aegis.bus.constants
"""
Tests for bus naming conventions and constants.
"""

from aegis.bus.constants import (
    agent_stream,
    agent_consumer_group,
    broadcast_consumer_group,
    STREAM_PREFIX,
    BROADCAST_STREAM,
)


class TestConstants:
    """Tests for stream/group naming functions."""

    def test_agent_stream(self):
        """agent_stream produces correct stream key."""
        assert agent_stream("warden") == "aegis:stream:warden"
        assert agent_stream("torchestrator") == "aegis:stream:torchestrator"

    def test_agent_consumer_group(self):
        """agent_consumer_group produces correct group name."""
        assert agent_consumer_group("forge") == "aegis:group:forge"

    def test_broadcast_consumer_group(self):
        """broadcast_consumer_group includes agent id."""
        result = broadcast_consumer_group("observer")
        assert result == "aegis:group:broadcast:observer"

    def test_stream_prefix(self):
        """STREAM_PREFIX is correct."""
        assert STREAM_PREFIX == "aegis:stream:"

    def test_broadcast_stream(self):
        """BROADCAST_STREAM is correct."""
        assert BROADCAST_STREAM == "aegis:stream:broadcast"
