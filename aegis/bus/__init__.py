# aegis/bus/__init__.py
# Implements: Part III, §3.1 — Message Bus package exports.
"""
Aegis Message Bus — Redis Streams-based inter-agent communication.

This package provides the core messaging infrastructure for all
inter-agent communication in Project Aegis.

Components:
    - RedisConnectionManager: Connection pool and lifecycle management.
    - MessagePublisher: Publish AegisMessage to agent streams.
    - MessageSubscriber: Consume messages with consumer groups and XACK.

Constants:
    - agent_stream(): Derive stream name for an agent.
    - agent_consumer_group(): Derive consumer group for an agent.
    - broadcast_consumer_group(): Derive broadcast group for an agent.
    - BROADCAST_STREAM: The system-wide broadcast stream key.
"""

from aegis.bus.redis_bus import RedisBus
from aegis.bus.connection import RedisConnectionManager
from aegis.bus.publisher import MessagePublisher
from aegis.bus.subscriber import MessageSubscriber
from aegis.bus.constants import (
    agent_stream,
    agent_consumer_group,
    broadcast_consumer_group,
    BROADCAST_STREAM,
    STREAM_PREFIX,
)

__all__ = [
    "RedisConnectionManager",
    "MessagePublisher",
    "MessageSubscriber",
    "agent_stream",
    "agent_consumer_group",
    "broadcast_consumer_group",
    "BROADCAST_STREAM",
    "STREAM_PREFIX",
]
