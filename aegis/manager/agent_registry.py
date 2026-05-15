# aegis/manager/agent_registry.py
# Implements: Part III §3.3 — Ordered startup of agents
"""
Agent Registry for the Aegis System Manager.

Provides an ordered manifest of all council agents so the System Manager
can start, stop, and restart them in the correct dependency sequence.

Startup order (from spec §3.3):
    Redis → Observer → Warden → Identity → Lexicon → Janus → Oracle → Forge → TOrchestrator

Note: Redis is infrastructure, not an agent — it is verified separately.
The Observer is a non-council service started first for logging coverage.
"""

from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Type

logger = logging.getLogger(__name__)


@dataclass
class AgentEntry:
    """
    Descriptor for a single managed agent.

    Attributes:
        agent_id:     Unique identifier matching the agent's ``agent_id`` attribute.
        display_name: Human-readable name for logs and UI.
        module_path:  Dotted Python module path containing the agent class.
        class_name:   Name of the agent class within the module.
        priority:     Startup priority (lower = earlier). Shutdown is reverse.
        required:     If True, system cannot proceed without this agent.
        config_key:   Optional key in aegis_config.yaml for agent-specific config.
        restart_max:  Maximum restart attempts before declaring failure.
        tags:         Arbitrary metadata tags (e.g., "council", "service").
    """

    agent_id: str
    display_name: str
    module_path: str
    class_name: str
    priority: int
    required: bool = True
    config_key: Optional[str] = None
    restart_max: int = 3
    tags: List[str] = field(default_factory=list)

    def import_class(self) -> Optional[Type[Any]]:
        """
        Dynamically import and return the agent class.

        Returns:
            The agent class, or None if the module/class cannot be imported.
        """
        try:
            module = importlib.import_module(self.module_path)
            cls = getattr(module, self.class_name)
            logger.debug(
                "Imported agent class: %s.%s", self.module_path, self.class_name
            )
            return cls
        except (ImportError, AttributeError) as exc:
            logger.warning(
                "Failed to import agent '%s' from %s.%s: %s",
                self.agent_id,
                self.module_path,
                self.class_name,
                exc,
            )
            return None


# ---------------------------------------------------------------------------
# Canonical Agent Registry — ordered by startup priority
# Implements: Part III §3.3 startup sequence
# ---------------------------------------------------------------------------

AGENT_REGISTRY: List[AgentEntry] = [
    AgentEntry(
        agent_id="observer",
        display_name="Observer Service",
        module_path="aegis.agents.observer",
        class_name="ObserverAgent",
        priority=10,
        required=False,  # System can run with degraded logging (RT-3)
        config_key="observer",
        restart_max=5,
        tags=["service", "monitoring"],
    ),
    AgentEntry(
        agent_id="warden",
        display_name="Warden (Security)",
        module_path="aegis.agents.warden",
        class_name="WardenAgent",
        priority=20,
        required=True,  # Security is non-negotiable
        config_key="warden",
        restart_max=5,  # Highest restart priority (RT-4)
        tags=["council", "security"],
    ),
    AgentEntry(
        agent_id="identity",
        display_name="Identity Agent",
        module_path="aegis.agents.identity",
        class_name="IdentityAgent",
        priority=30,
        required=True,
        config_key="identity",
        tags=["council", "iam"],
    ),
    AgentEntry(
        agent_id="lexicon",
        display_name="Lexicon (Memory)",
        module_path="aegis.agents.lexicon",
        class_name="LexiconAgent",
        priority=40,
        required=True,
        config_key="lexicon",
        tags=["council", "memory"],
    ),
    AgentEntry(
        agent_id="janus",
        display_name="Janus (Governance)",
        module_path="aegis.agents.janus",
        class_name="JanusAgent",
        priority=50,
        required=True,
        config_key="janus",
        tags=["council", "governance"],
    ),
    AgentEntry(
        agent_id="oracle",
        display_name="Oracle (LLM Gateway)",
        module_path="aegis.agents.oracle",
        class_name="OracleAgent",
        priority=60,
        required=True,
        config_key="oracle",
        tags=["council", "llm"],
    ),
    AgentEntry(
        agent_id="forge",
        display_name="The Forge (Execution)",
        module_path="aegis.agents.forge",
        class_name="ForgeAgent",
        priority=70,
        required=True,
        config_key="forge",
        tags=["council", "execution"],
    ),
    AgentEntry(
        agent_id="torchestrator",
        display_name="TOrchestrator (Council Lead)",
        module_path="aegis.agents.torchestrator",
        class_name="TorchestratorAgent",
        priority=80,
        required=True,
        config_key="torchestrator",
        tags=["council", "orchestration"],
    ),
]


def get_startup_order() -> List[AgentEntry]:
    """Return agents sorted by ascending priority (startup order)."""
    return sorted(AGENT_REGISTRY, key=lambda e: e.priority)


def get_shutdown_order() -> List[AgentEntry]:
    """Return agents sorted by descending priority (reverse startup)."""
    return sorted(AGENT_REGISTRY, key=lambda e: e.priority, reverse=True)


def get_agent_entry(agent_id: str) -> Optional[AgentEntry]:
    """Look up an AgentEntry by agent_id."""
    for entry in AGENT_REGISTRY:
        if entry.agent_id == agent_id:
            return entry
    return None
