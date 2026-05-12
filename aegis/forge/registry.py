# aegis/forge/registry.py
# Implements: Part VII, §7.1 & §7.2 — Tool & Skill Registration
"""
Registry classes for managing Tool and Skill modules.
Handles discovery, registration, validation, and lookup.
"""

import importlib
import os
import pkgutil
import logging
from typing import Any, Dict, Optional

import structlog

from aegis.forge.tools.base import ToolManifest
from aegis.forge.skills.base import SkillManifest

logger = structlog.get_logger(__name__)


class ToolRegistry:
    """
    Registry for all available Tools.

    Tools are discovered and loaded from the aegis.forge.tools package at startup.
    Each tool module must expose:
        - manifest: ToolManifest
        - async def execute(params: dict) -> ToolResult
    """

    def __init__(self):
        self._tools: Dict[str, Any] = {}  # name -> module
        self._manifests: Dict[str, ToolManifest] = {}  # name -> manifest

    def register(self, module: Any) -> None:
        """
        Register a tool module.

        Args:
            module: A Python module with 'manifest' (ToolManifest) and 'execute' (async callable).

        Raises:
            ValueError: If module does not conform to the tool interface.
        """
        if not hasattr(module, "manifest") or not hasattr(module, "execute"):
            raise ValueError(
                f"Tool module {module.__name__} must expose 'manifest' and 'execute'."
            )

        manifest: ToolManifest = module.manifest
        name = manifest.name

        if name in self._tools:
            logger.warning("tool_registry.duplicate", tool_name=name)

        self._tools[name] = module
        self._manifests[name] = manifest
        logger.info("tool_registry.registered", tool_name=name, version=manifest.version)

    def get_tool(self, name: str) -> Optional[Any]:
        """Retrieve a tool module by name."""
        return self._tools.get(name)

    def get_manifest(self, name: str) -> Optional[ToolManifest]:
        """Retrieve a tool manifest by name."""
        return self._manifests.get(name)

    def list_tools(self) -> list[dict]:
        """Return a list of all registered tool manifests as dicts."""
        return [m.model_dump() for m in self._manifests.values()]

    def has_tool(self, name: str) -> bool:
        """Check if a tool is registered."""
        return name in self._tools

    @property
    def tool_count(self) -> int:
        """Number of registered tools."""
        return len(self._tools)

    def discover_and_load(self, package_path: str = "aegis.forge.tools") -> int:
        """
        Auto-discover and load all tool modules from the specified package.

        Args:
            package_path: Dotted package path to scan for tool modules.

        Returns:
            Number of tools successfully registered.
        """
        loaded = 0
        try:
            package = importlib.import_module(package_path)
        except ImportError as e:
            logger.error("tool_registry.discover.import_error", package=package_path, error=str(e))
            return 0

        package_dir = os.path.dirname(package.__file__)

        for _, module_name, is_pkg in pkgutil.iter_modules([package_dir]):
            if module_name == "base" or module_name.startswith("_"):
                continue
            full_module_name = f"{package_path}.{module_name}"
            try:
                mod = importlib.import_module(full_module_name)
                if hasattr(mod, "manifest") and hasattr(mod, "execute"):
                    self.register(mod)
                    loaded += 1
                else:
                    logger.debug("tool_registry.discover.skip", module=full_module_name,
                                 reason="Missing manifest or execute")
            except Exception as e:
                logger.error("tool_registry.discover.error", module=full_module_name, error=str(e))

        logger.info("tool_registry.discovery_complete", tools_loaded=loaded)
        return loaded


class SkillRegistry:
    """
    Registry for all available Skills.

    Skills are discovered and loaded from the aegis.forge.skills package at startup.
    Each skill module must expose:
        - manifest: SkillManifest
        - async def execute(params: dict, forge_context: ForgeContext) -> SkillResult
    """

    def __init__(self):
        self._skills: Dict[str, Any] = {}  # name -> module
        self._manifests: Dict[str, SkillManifest] = {}  # name -> manifest

    def register(self, module: Any) -> None:
        """
        Register a skill module.

        Args:
            module: A Python module with 'manifest' (SkillManifest) and 'execute' (async callable).

        Raises:
            ValueError: If module does not conform to the skill interface.
        """
        if not hasattr(module, "manifest") or not hasattr(module, "execute"):
            raise ValueError(
                f"Skill module {module.__name__} must expose 'manifest' and 'execute'."
            )

        manifest: SkillManifest = module.manifest
        name = manifest.name

        if name in self._skills:
            logger.warning("skill_registry.duplicate", skill_name=name)

        self._skills[name] = module
        self._manifests[name] = manifest
        logger.info("skill_registry.registered", skill_name=name, version=manifest.version)

    def get_skill(self, name: str) -> Optional[Any]:
        """Retrieve a skill module by name."""
        return self._skills.get(name)

    def get_manifest(self, name: str) -> Optional[SkillManifest]:
        """Retrieve a skill manifest by name."""
        return self._manifests.get(name)

    def list_skills(self) -> list[dict]:
        """Return a list of all registered skill manifests as dicts."""
        return [m.model_dump() for m in self._manifests.values()]

    def has_skill(self, name: str) -> bool:
        """Check if a skill is registered."""
        return name in self._skills

    @property
    def skill_count(self) -> int:
        """Number of registered skills."""
        return len(self._skills)

    def discover_and_load(self, package_path: str = "aegis.forge.skills") -> int:
        """
        Auto-discover and load all skill modules from the specified package.

        Args:
            package_path: Dotted package path to scan for skill modules.

        Returns:
            Number of skills successfully registered.
        """
        loaded = 0
        try:
            package = importlib.import_module(package_path)
        except ImportError as e:
            logger.error("skill_registry.discover.import_error", package=package_path, error=str(e))
            return 0

        package_dir = os.path.dirname(package.__file__)

        for _, module_name, is_pkg in pkgutil.iter_modules([package_dir]):
            if module_name == "base" or module_name.startswith("_"):
                continue
            full_module_name = f"{package_path}.{module_name}"
            try:
                mod = importlib.import_module(full_module_name)
                if hasattr(mod, "manifest") and hasattr(mod, "execute"):
                    self.register(mod)
                    loaded += 1
                else:
                    logger.debug("skill_registry.discover.skip", module=full_module_name,
                                 reason="Missing manifest or execute")
            except Exception as e:
                logger.error("skill_registry.discover.error", module=full_module_name, error=str(e))

        logger.info("skill_registry.discovery_complete", skills_loaded=loaded)
        return loaded
