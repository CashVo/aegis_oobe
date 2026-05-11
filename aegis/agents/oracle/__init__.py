# aegis/agents/oracle/__init__.py
"""
Oracle — The LLM Gateway Agent.
Implements: Part II §2.1

A singleton gateway for all non-deterministic (LLM) requests. Every agent
requiring LLM inference must route through The Oracle. Manages model selection,
prompt templating, token budgets, rate limiting, and response caching.
"""

from aegis.agents.oracle.agent import OracleAgent

__all__ = ["OracleAgent"]
