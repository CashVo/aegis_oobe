# aegis/bus/constants.py
# Implements: Part III, §3.1 — Redis Stream naming conventions and constants.
"""
Constants and naming conventions for the Aegis Redis Message Bus.

All stream and consumer group names are derived from these constants
to ensure consistency across the system.
"""

# --- Stream Naming ---
STREAM_PREFIX: str = "aegis:stream:"
BROADCAST_STREAM: str = "aegis:stream:broadcast"

# --- Consumer Group Naming ---
CONSUMER_GROUP_PREFIX: str = "aegis:group:"

# --- Default Configuration ---
DEFAULT_REDIS_HOST: str = "127.0.0.1"
DEFAULT_REDIS_PORT: int = 6379
DEFAULT_REDIS_DB: int = 0
DEFAULT_BLOCK_MS: int = 5000  # Block for 5s when reading streams
DEFAULT_READ_COUNT: int = 10  # Read up to 10 messages per poll cycle
DEFAULT_CLAIM_MIN_IDLE_MS: int = 30000  # Claim pending messages idle > 30s
DEFAULT_MAX_RETRIES: int = 3  # Max redelivery attempts before dead-lettering


def agent_stream(agent_id: str) -> str:
    """
    Derive the dedicated stream name for a given agent.

    Args:
        agent_id: The unique identifier of the agent.

    Returns:
        The fully qualified Redis stream key (e.g., 'aegis:stream:warden').
    """
    return f"{STREAM_PREFIX}{agent_id}"


def agent_consumer_group(agent_id: str) -> str:
    """
    Derive the consumer group name for a given agent's stream.

    Each agent has a single consumer group on its own stream to enable
    acknowledgment and pending message tracking.

    Args:
        agent_id: The unique identifier of the agent.

    Returns:
        The consumer group name (e.g., 'aegis:group:warden').
    """
    return f"{CONSUMER_GROUP_PREFIX}{agent_id}"


def broadcast_consumer_group(agent_id: str) -> str:
    """
    Derive the consumer group name for an agent subscribing to the broadcast stream.

    Each agent that subscribes to broadcast gets its own consumer group
    so all agents receive all broadcast messages independently.

    Args:
        agent_id: The unique identifier of the subscribing agent.

    Returns:
        The consumer group name for broadcast (e.g., 'aegis:group:broadcast:observer').
    """
    return f"{CONSUMER_GROUP_PREFIX}broadcast:{agent_id}"
