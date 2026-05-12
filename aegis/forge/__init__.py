# aegis/forge/__init__.py
# Implements: Part VII — The Forge Protocol
"""
The Forge — Centralized, stateless execution service.
Runs all deterministic Tools and composable Skills.
"""

from aegis.forge.agent import ForgeAgent
from aegis.forge.registry import ToolRegistry, SkillRegistry
from aegis.forge.context import ForgeContext

__all__ = ["ForgeAgent", "ToolRegistry", "SkillRegistry", "ForgeContext"]
