# aegis/agents/janus/__init__.py
"""
Janus — The Governance Engine.

Implements: Part II, §2.1 — Janus agent role.
A policy and rules engine that stores and evaluates system-wide governance rules,
ethical guardrails, and operational policies.
"""

from aegis.agents.janus.agent import JanusAgent
from aegis.agents.janus.engine import PolicyEngine
from aegis.agents.janus.storage import PolicyStore

__all__ = ["JanusAgent", "PolicyEngine", "PolicyStore"]
