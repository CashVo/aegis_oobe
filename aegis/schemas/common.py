# File: aegis/schemas/common.py
# Purpose: Shared enums and helper functions used across the system.

from enum import Enum
from pathlib import Path

class AgentID(str, Enum):
    """
    Canonical identifiers for all agents in the Aegis Council, plus the observer.
    Conforms to Genesis Spec Part II, Section 2.1.
    """
    # Council Members
    ORCHESTRATOR = "t_orchestrator"
    FORGE = "forge"
    ORACLE = "oracle"
    WARDEN = "warden"
    LEXICON = "lexicon"
    JANUS = "janus"
    IDENTITY = "identity"
    # Non-council
    OBSERVER = "observer"

class TierName(str, Enum):
    """
    Defines the hierarchy of memory and identity storage.
    Conforms to Genesis Spec Part IV, Section 4.2 (naming implied).
    """
    L0 = "l0_identity.yaml"
    L1 = "l1_context"
    L2 = "l2_episodic"
    L3 = "l3_semantic"
    L4 = "l4_procedural"
    L5 = "l5_archive"

def stream_name(agent_id: AgentID | str) -> str:
    """
    Generates the canonical Redis stream key for an agent's inbound channel.

    Args:
        agent_id: The ID of the agent.

    Returns:
        The formatted Redis stream key string.
    """
    id_val = agent_id.value if isinstance(agent_id, AgentID) else agent_id
    return f"aegis:stream:{id_val}"

def tenant_path(data_dir: str | Path, tenant_id: str, user_id: str) -> Path:
    """
    Constructs the standardized data path for a given user within a tenant.
    Conforms to Genesis Spec Part IV, Section 4.2.

    Args:
        data_dir: The root data directory from AegisConfig.
        tenant_id: The tenant's unique identifier.
        user_id: The user's unique identifier.

    Returns:
        A Path object to the user's data directory.
    """
    return Path(data_dir) / tenant_id / user_id
