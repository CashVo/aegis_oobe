# aegis/manager/__init__.py
# Implements: Part III §3.3 — System Manager Package
"""
Aegis Manager package.

Exports:
    SystemManager  — Full lifecycle manager for all agents and services.
    AegisScheduler — APScheduler-backed job scheduler service.
    AgentEntry     — Registry entry for a managed agent.
    AGENT_REGISTRY — Ordered registry of all council agents.
"""

from aegis.manager.agent_registry import AgentEntry, AGENT_REGISTRY
from aegis.manager.scheduler import AegisScheduler
from aegis.manager.system_manager import SystemManager

__all__ = [
    "SystemManager",
    "AegisScheduler",
    "AgentEntry",
    "AGENT_REGISTRY",
]
