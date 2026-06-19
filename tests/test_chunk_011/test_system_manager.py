# tests/test_chunk_011/test_system_manager.py
# Tests for: Part III §3.3 — System Manager
"""
Unit and integration tests for the Aegis System Manager.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aegis.manager.agent_registry import (
    AGENT_REGISTRY,
    AgentEntry,
    get_shutdown_order,
    get_startup_order,
)
from aegis.manager.system_manager import (
    AgentState,
    SystemManager,
    _deep_merge,
    _load_config,
)


# ---------------------------------------------------------------------------
# Agent Registry Tests
# ---------------------------------------------------------------------------

class TestAgentRegistry:
    """Tests for agent_registry.py."""

    def test_registry_is_not_empty(self):
        """Registry contains all 8 council agents + services."""
        assert len(AGENT_REGISTRY) >= 7

    def test_startup_order_ascending(self):
        """Startup order has ascending priority values."""
        order = get_startup_order()
        priorities = [e.priority for e in order]
        assert priorities == sorted(priorities)

    def test_shutdown_order_descending(self):
        """Shutdown order is reverse of startup order."""
        startup = get_startup_order()
        shutdown = get_shutdown_order()
        assert [e.agent_id for e in shutdown] == [
            e.agent_id for e in reversed(startup)
        ]

    def test_observer_starts_first(self):
        """Observer has the lowest priority (starts first)."""
        order = get_startup_order()
        assert order[0].agent_id == "observer"

    def test_warden_starts_before_others(self):
        """Warden starts before Identity, Lexicon, etc."""
        order = get_startup_order()
        ids = [e.agent_id for e in order]
        assert ids.index("warden") < ids.index("identity")
        assert ids.index("warden") < ids.index("lexicon")

    def test_torchestrator_starts_last(self):
        """TOrchestrator has the highest priority (starts last)."""
        order = get_startup_order()
        assert order[-1].agent_id == "torchestrator"

    def test_warden_is_required(self):
        """Warden is marked as required (RT-4)."""
        from aegis.manager.agent_registry import get_agent_entry
        warden = get_agent_entry("warden")
        assert warden is not None
        assert warden.required is True

    def test_observer_is_optional(self):
        """Observer is optional — system can run with degraded logging (RT-3)."""
        from aegis.manager.agent_registry import get_agent_entry
        observer = get_agent_entry("observer")
        assert observer is not None
        assert observer.required is False

    def test_warden_has_highest_restart_attempts(self):
        """Warden should have elevated restart attempts (RT-4)."""
        from aegis.manager.agent_registry import get_agent_entry
        warden = get_agent_entry("warden")
        assert warden is not None
        assert warden.restart_max >= 5

    def test_agent_entry_import_nonexistent(self):
        """Importing a nonexistent module returns None."""
        entry = AgentEntry(
            agent_id="fake",
            display_name="Fake",
            module_path="aegis.agents.nonexistent",
            class_name="FakeAgent",
            priority=999,
        )
        assert entry.import_class() is None


# ---------------------------------------------------------------------------
# Config Tests
# ---------------------------------------------------------------------------

class TestConfig:
    """Tests for configuration loading."""

    def test_deep_merge_basic(self):
        base = {"a": 1, "b": {"c": 2, "d": 3}}
        override = {"b": {"c": 99}, "e": 5}
        _deep_merge(base, override)
        assert base == {"a": 1, "b": {"c": 99, "d": 3}, "e": 5}

    def test_load_config_defaults(self):
        """Config loads with sane defaults even without a config file."""
        config = _load_config("nonexistent.yaml")
        assert "redis" in config
        assert "system_manager" in config
        assert "scheduler" in config
        assert config["redis"]["port"] == 6379

    @patch.dict("os.environ", {"AEGIS_REDIS_PORT": "7777"})
    def test_env_var_override(self):
        """Environment variables override config file values."""
        config = _load_config("nonexistent.yaml")
        assert config["redis"]["port"] == 7777


# ---------------------------------------------------------------------------
# Agent State Tests
# ---------------------------------------------------------------------------

class TestAgentState:
    """Tests for AgentState lifecycle tracking."""

    def test_initial_state(self):
        entry = AgentEntry(
            agent_id="test",
            display_name="Test",
            module_path="test.module",
            class_name="TestAgent",
            priority=50,
        )
        state = AgentState(entry)
        assert state.status == "stopped"
        assert state.restart_count == 0
        assert state.instance is None

    def test_reset(self):
        entry = AgentEntry(
            agent_id="test",
            display_name="Test",
            module_path="test.module",
            class_name="TestAgent",
            priority=50,
        )
        state = AgentState(entry)
        state.status = "failed"
        state.restart_count = 5
        state.error = "Something broke"
        state.reset()
        assert state.status == "stopped"
        assert state.restart_count == 0
        assert state.error is None


# ---------------------------------------------------------------------------
# System Manager Tests
# ---------------------------------------------------------------------------

class TestSystemManager:
    """Tests for SystemManager core logic."""

    def test_instantiation(self):
        """SystemManager can be created with default config."""
        with patch.dict("os.environ", {}, clear=False):
            manager = SystemManager(config_path="nonexistent.yaml")
            assert manager.is_running is False
            assert manager.scheduler is None

    def test_get_system_status(self):
        """get_system_status returns expected structure."""
        manager = SystemManager(config_path="nonexistent.yaml")
        status = manager.get_system_status()
        assert "system" in status
        assert "redis" in status
        assert "scheduler" in status
        assert "agents" in status
        assert isinstance(status["agents"], dict)

    def test_agents_initialized(self):
        """All registry agents have corresponding AgentState."""
        manager = SystemManager(config_path="nonexistent.yaml")
        for entry in AGENT_REGISTRY:
            assert entry.agent_id in manager._agents

    def test_get_agent_status_known(self):
        """Can retrieve status for a known agent."""
        manager = SystemManager(config_path="nonexistent.yaml")
        status = manager.get_agent_status("warden")
        assert status is not None
        assert status["agent_id"] == "warden"
        assert status["status"] == "stopped"

    def test_get_agent_status_unknown(self):
        """Unknown agent returns None."""
        manager = SystemManager(config_path="nonexistent.yaml")
        assert manager.get_agent_status("nonexistent") is None
