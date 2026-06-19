# tests/test_forge/test_registry.py
# Unit tests for Tool and Skill registries
"""
Tests for aegis.forge.registry — ToolRegistry and SkillRegistry.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock
from types import ModuleType

from aegis.forge.registry import ToolRegistry, SkillRegistry
from aegis.forge.tools.base import ToolManifest, ToolResult
from aegis.forge.skills.base import SkillManifest, SkillResult


class TestToolRegistry:
    """Tests for ToolRegistry."""

    def _make_mock_tool(self, name: str = "mock_tool") -> ModuleType:
        """Create a mock tool module."""
        mod = ModuleType(f"aegis.forge.tools.{name}")
        mod.manifest = ToolManifest(
            name=name,
            description=f"Mock tool: {name}",
            version="1.0.0",
            permissions_required=["test.execute"],
        )
        mod.execute = AsyncMock(return_value=ToolResult(success=True, data={"mock": True}))
        return mod

    def test_register_tool(self):
        registry = ToolRegistry()
        mod = self._make_mock_tool("test_tool")
        registry.register(mod)
        assert registry.has_tool("test_tool")
        assert registry.tool_count == 1

    def test_get_tool(self):
        registry = ToolRegistry()
        mod = self._make_mock_tool("test_tool")
        registry.register(mod)
        retrieved = registry.get_tool("test_tool")
        assert retrieved is mod

    def test_get_nonexistent_tool(self):
        registry = ToolRegistry()
        assert registry.get_tool("nonexistent") is None

    def test_list_tools(self):
        registry = ToolRegistry()
        registry.register(self._make_mock_tool("tool_a"))
        registry.register(self._make_mock_tool("tool_b"))
        tools = registry.list_tools()
        assert len(tools) == 2
        names = [t["name"] for t in tools]
        assert "tool_a" in names
        assert "tool_b" in names

    def test_register_invalid_module(self):
        registry = ToolRegistry()
        mod = ModuleType("bad_module")  # No manifest or execute
        with pytest.raises(ValueError):
            registry.register(mod)

    def test_discover_and_load(self):
        """Integration test: discover tools from the actual package."""
        registry = ToolRegistry()
        loaded = registry.discover_and_load("aegis.forge.tools")
        # Should load all OOBE tools (11 tools)
        assert loaded >= 10  # At least 10 OOBE tools


class TestSkillRegistry:
    """Tests for SkillRegistry."""

    def _make_mock_skill(self, name: str = "mock_skill") -> ModuleType:
        """Create a mock skill module."""
        mod = ModuleType(f"aegis.forge.skills.{name}")
        mod.manifest = SkillManifest(
            name=name,
            description=f"Mock skill: {name}",
            version="1.0.0",
            tools_used=["file_read"],
            requires_oracle=True,
        )
        mod.execute = AsyncMock(return_value=SkillResult(success=True, data={"mock": True}))
        return mod

    def test_register_skill(self):
        registry = SkillRegistry()
        mod = self._make_mock_skill("test_skill")
        registry.register(mod)
        assert registry.has_skill("test_skill")
        assert registry.skill_count == 1

    def test_list_skills(self):
        registry = SkillRegistry()
        registry.register(self._make_mock_skill("skill_a"))
        registry.register(self._make_mock_skill("skill_b"))
        skills = registry.list_skills()
        assert len(skills) == 2

    def test_discover_and_load(self):
        """Integration test: discover skills from the actual package."""
        registry = SkillRegistry()
        loaded = registry.discover_and_load("aegis.forge.skills")
        # Should load all OOBE skills (6 skills)
        assert loaded >= 5  # At least 5 OOBE skills
