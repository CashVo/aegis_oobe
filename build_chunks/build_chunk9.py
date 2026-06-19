# build_chunk_009.py
#
# CHUNK-009: The Forge (Execution)
# Implements: Part VI §6.1, Part VII, Part VIII
#
# Dependencies: CHUNK-001 (Base Layout & Schemas), CHUNK-002 (Redis Message Bus),
#               CHUNK-003 (Warden), CHUNK-008 (Oracle LLM Gateway)
#
# Deliverables: Forge agent, Tool registry, Skill registry, ForgeContext,
#               all OOBE tools (§8.1), all OOBE skills (§8.2)
#
# Run from the root of the project-aegis directory.

import os
import textwrap

# --- File Manifest ---
CHUNK_9_FILES = {

    # =========================================================================
    # SCHEMAS — Forge Protocol Contracts
    # =========================================================================

    "aegis/schemas/forge.py": '''
# aegis/schemas/forge.py
# Implements: Part VI, §6.1 — Forge Protocol
"""
Forge protocol schemas defining the request/response contracts
for tool and skill execution via The Forge agent.
"""

from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field


class ForgeAction(str, Enum):
    """Actions supported by The Forge agent."""
    EXECUTE_TOOL = "execute_tool"
    EXECUTE_SKILL = "execute_skill"
    LIST_TOOLS = "list_tools"
    LIST_SKILLS = "list_skills"
    REGISTER_TOOL = "register_tool"
    REGISTER_SKILL = "register_skill"


class ForgeRequest(BaseModel):
    """
    Request payload for Forge operations.

    Attributes:
        action: The Forge action to perform.
        tool_or_skill_name: Name of the tool/skill to execute (required for execute actions).
        parameters: Input parameters for the tool/skill.
        timeout_seconds: Maximum execution time before timeout.
    """
    action: ForgeAction
    tool_or_skill_name: Optional[str] = None
    parameters: dict = {}
    timeout_seconds: int = 60


class ForgeResponse(BaseModel):
    """
    Response payload from Forge operations.

    Attributes:
        success: Whether the operation completed successfully.
        action: The action that was performed.
        result: The output data from the operation.
        error: Error message if success is False.
        execution_time_ms: Time taken to execute in milliseconds.
    """
    success: bool
    action: ForgeAction
    result: Any = None
    error: Optional[str] = None
    execution_time_ms: float = 0.0
''',

    # =========================================================================
    # FORGE CORE — Agent, Registry, Context
    # =========================================================================

    "aegis/forge/__init__.py": '''
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
''',

    "aegis/forge/context.py": '''
# aegis/forge/context.py
# Implements: Part VII, §7.2 — ForgeContext
"""
ForgeContext — Runtime context injected into Skills during execution.
Provides Skills with the ability to invoke Tools and send Oracle requests
without direct bus access.
"""

import logging
from typing import Any, Optional

import structlog

from aegis.forge.tools.base import ToolResult
from aegis.schemas.forge import ForgeAction

logger = structlog.get_logger(__name__)


class ForgeContext:
    """
    Runtime context object injected by The Forge into Skills during execution.

    Provides a controlled interface for Skills to:
    - Invoke Tools (via the local tool registry)
    - Send Oracle (LLM) requests (via the message bus)
    - Request context assembly from Lexicon (via the message bus)

    Skills NEVER get direct bus access. All inter-agent communication
    is mediated through this context object.

    Attributes:
        tenant_id: The tenant scope for this execution.
        user_id: The user scope for this execution.
        session_id: The active session identifier.
    """

    def __init__(
        self,
        tenant_id: str,
        user_id: str,
        session_id: str,
        tool_registry: Any = None,
        bus_publisher: Any = None,
        correlation_id: Optional[str] = None,
    ):
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.session_id = session_id
        self._tool_registry = tool_registry
        self._bus_publisher = bus_publisher
        self._correlation_id = correlation_id
        self._steps_executed: list[str] = []

    @property
    def steps_executed(self) -> list[str]:
        """Returns the audit trail of operations performed during this execution."""
        return self._steps_executed

    async def invoke_tool(self, tool_name: str, params: dict) -> ToolResult:
        """
        Invoke a registered Tool by name.

        Args:
            tool_name: The name of the tool to execute.
            params: Input parameters for the tool.

        Returns:
            ToolResult with success status and data/error.
        """
        logger.info("forge_context.invoke_tool", tool_name=tool_name, tenant_id=self.tenant_id)
        self._steps_executed.append(f"tool:{tool_name}")

        if self._tool_registry is None:
            return ToolResult(success=False, error="Tool registry not available in this context.")

        try:
            tool_module = self._tool_registry.get_tool(tool_name)
            if tool_module is None:
                return ToolResult(success=False, error=f"Tool '{tool_name}' not found in registry.")
            result = await tool_module.execute(params)
            return result
        except Exception as e:
            logger.error("forge_context.invoke_tool.error", tool_name=tool_name, error=str(e))
            return ToolResult(success=False, error=f"Tool execution failed: {str(e)}")

    async def invoke_oracle(self, request: dict) -> dict:
        """
        Send a request to The Oracle (LLM Gateway) via the message bus.

        Args:
            request: Dictionary conforming to OracleRequest schema.
                     Keys: action, prompt, system_prompt, model_preference,
                           temperature, max_tokens, response_format

        Returns:
            Dictionary conforming to OracleResponse schema.
        """
        logger.info("forge_context.invoke_oracle", action=request.get("action", "query"))
        self._steps_executed.append(f"oracle:{request.get('action', 'query')}")

        if self._bus_publisher is None:
            return {
                "success": False,
                "content": "",
                "model_used": "none",
                "tokens_used": {"prompt": 0, "completion": 0, "total": 0},
                "cached": False,
                "latency_ms": 0.0,
                "error": "Bus publisher not available. Cannot reach Oracle.",
            }

        try:
            from aegis.schemas.message import AegisMessage, MessageType, Priority
            from uuid import uuid4

            msg = AegisMessage(
                message_id=str(uuid4()),
                correlation_id=self._correlation_id or str(uuid4()),
                source_agent="forge",
                target_agent="oracle",
                message_type=MessageType.REQUEST,
                tenant_id=self.tenant_id,
                user_id=self.user_id,
                action="oracle.query",
                payload=request,
                priority=Priority.NORMAL,
                metadata={"session_id": self.session_id},
            )

            response = await self._bus_publisher.request(msg, timeout=60)
            if response:
                return response.payload
            else:
                return {
                    "success": False,
                    "content": "",
                    "model_used": "none",
                    "tokens_used": {"prompt": 0, "completion": 0, "total": 0},
                    "cached": False,
                    "latency_ms": 0.0,
                    "error": "Oracle request timed out.",
                }
        except Exception as e:
            logger.error("forge_context.invoke_oracle.error", error=str(e))
            return {
                "success": False,
                "content": "",
                "model_used": "none",
                "tokens_used": {"prompt": 0, "completion": 0, "total": 0},
                "cached": False,
                "latency_ms": 0.0,
                "error": f"Oracle invocation failed: {str(e)}",
            }

    async def get_context(self, query: str, scope: list[str] = None, token_budget: int = 4000) -> dict:
        """
        Request context assembly from Lexicon.

        Args:
            query: The query string for context retrieval.
            scope: Which memory tiers to query (default: L0, L1, L2, L3).
            token_budget: Maximum tokens for the assembled context.

        Returns:
            Dictionary conforming to ContextPacket schema.
        """
        if scope is None:
            scope = ["L0", "L1", "L2", "L3"]

        logger.info("forge_context.get_context", query=query[:50], scope=scope)
        self._steps_executed.append(f"lexicon:assemble_context")

        if self._bus_publisher is None:
            return {
                "tenant_id": self.tenant_id,
                "user_id": self.user_id,
                "fragments": [],
                "total_tokens": 0,
                "tiers_queried": scope,
                "assembly_time_ms": 0.0,
                "error": "Bus publisher not available. Cannot reach Lexicon.",
            }

        try:
            from aegis.schemas.message import AegisMessage, MessageType, Priority
            from uuid import uuid4

            msg = AegisMessage(
                message_id=str(uuid4()),
                correlation_id=self._correlation_id or str(uuid4()),
                source_agent="forge",
                target_agent="lexicon",
                message_type=MessageType.REQUEST,
                tenant_id=self.tenant_id,
                user_id=self.user_id,
                action="lexicon.assemble_context",
                payload={
                    "query": query,
                    "scope": scope,
                    "token_budget": token_budget,
                    "session_id": self.session_id,
                },
                priority=Priority.NORMAL,
                metadata={"session_id": self.session_id},
            )

            response = await self._bus_publisher.request(msg, timeout=30)
            if response:
                return response.payload
            else:
                return {
                    "tenant_id": self.tenant_id,
                    "user_id": self.user_id,
                    "fragments": [],
                    "total_tokens": 0,
                    "tiers_queried": scope,
                    "assembly_time_ms": 0.0,
                    "error": "Lexicon context request timed out.",
                }
        except Exception as e:
            logger.error("forge_context.get_context.error", error=str(e))
            return {
                "tenant_id": self.tenant_id,
                "user_id": self.user_id,
                "fragments": [],
                "total_tokens": 0,
                "tiers_queried": scope,
                "assembly_time_ms": 0.0,
                "error": f"Context assembly failed: {str(e)}",
            }
''',

    "aegis/forge/registry.py": '''
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
''',

    "aegis/forge/agent.py": '''
# aegis/forge/agent.py
# Implements: Part II §2.1 (The Forge), Part VI §6.1, Part VII
"""
The Forge Agent — Centralized, stateless execution service.
Runs all deterministic Tools and composable Skills.
Does not make decisions; only executes what it is told.
"""

import asyncio
import time
from typing import Optional
from uuid import uuid4

import structlog

from aegis.agents.base import BaseAgent
from aegis.schemas.message import AegisMessage, MessageType, Priority
from aegis.schemas.forge import ForgeAction, ForgeRequest, ForgeResponse
from aegis.forge.registry import ToolRegistry, SkillRegistry
from aegis.forge.context import ForgeContext

logger = structlog.get_logger(__name__)


class ForgeAgent(BaseAgent):
    """
    The Forge — Execution Arm of the Aegis Council.

    A centralized, stateless execution service that:
    - Maintains registries of all available Tools and Skills
    - Executes Tools (deterministic, atomic operations)
    - Executes Skills (composable procedures using Tools + Oracle)
    - Reports results back via the message bus

    The Forge does NOT make decisions. It executes what it is told
    after Warden authorization has been confirmed.
    """

    agent_id: str = "forge"
    subscriptions: list[str] = ["aegis:stream:forge"]

    def __init__(self, bus=None, config: dict = None):
        self._bus = bus
        self._config = config or {}
        self._tool_registry = ToolRegistry()
        self._skill_registry = SkillRegistry()
        self._running = False

    @property
    def tool_registry(self) -> ToolRegistry:
        """Access the tool registry."""
        return self._tool_registry

    @property
    def skill_registry(self) -> SkillRegistry:
        """Access the skill registry."""
        return self._skill_registry

    async def startup(self) -> None:
        """
        Initialize The Forge:
        1. Discover and register all Tools from aegis.forge.tools
        2. Discover and register all Skills from aegis.forge.skills
        3. Subscribe to the forge message stream
        """
        logger.info("forge.startup", status="initializing")

        # Discover tools
        tools_loaded = self._tool_registry.discover_and_load("aegis.forge.tools")
        logger.info("forge.startup.tools", count=tools_loaded)

        # Discover skills
        skills_loaded = self._skill_registry.discover_and_load("aegis.forge.skills")
        logger.info("forge.startup.skills", count=skills_loaded)

        # Subscribe to bus
        if self._bus:
            await self._bus.subscribe(self.subscriptions[0], self.agent_id)

        self._running = True
        logger.info("forge.startup.complete",
                    tools=tools_loaded,
                    skills=skills_loaded)

    async def shutdown(self) -> None:
        """Graceful shutdown of The Forge."""
        logger.info("forge.shutdown", status="shutting_down")
        self._running = False
        if self._bus:
            await self._bus.unsubscribe(self.subscriptions[0], self.agent_id)
        logger.info("forge.shutdown.complete")

    async def handle_message(self, message: AegisMessage) -> Optional[AegisMessage]:
        """
        Process an incoming Forge request.

        Routes to the appropriate handler based on ForgeAction:
        - EXECUTE_TOOL: Execute a registered tool
        - EXECUTE_SKILL: Execute a registered skill
        - LIST_TOOLS: Return all registered tool manifests
        - LIST_SKILLS: Return all registered skill manifests

        Args:
            message: Incoming AegisMessage with ForgeRequest payload.

        Returns:
            AegisMessage response with ForgeResponse payload, or None on error.
        """
        logger.info("forge.handle_message",
                    action=message.action,
                    source=message.source_agent,
                    correlation_id=message.correlation_id)

        start_time = time.perf_counter()

        try:
            request = ForgeRequest(**message.payload)
        except Exception as e:
            logger.error("forge.handle_message.invalid_request", error=str(e))
            return self._build_response(
                message=message,
                response=ForgeResponse(
                    success=False,
                    action=ForgeAction.EXECUTE_TOOL,
                    error=f"Invalid ForgeRequest payload: {str(e)}",
                    execution_time_ms=0.0,
                ),
            )

        # Route to handler
        if request.action == ForgeAction.EXECUTE_TOOL:
            response = await self._execute_tool(request, message)
        elif request.action == ForgeAction.EXECUTE_SKILL:
            response = await self._execute_skill(request, message)
        elif request.action == ForgeAction.LIST_TOOLS:
            response = ForgeResponse(
                success=True,
                action=ForgeAction.LIST_TOOLS,
                result=self._tool_registry.list_tools(),
                execution_time_ms=(time.perf_counter() - start_time) * 1000,
            )
        elif request.action == ForgeAction.LIST_SKILLS:
            response = ForgeResponse(
                success=True,
                action=ForgeAction.LIST_SKILLS,
                result=self._skill_registry.list_skills(),
                execution_time_ms=(time.perf_counter() - start_time) * 1000,
            )
        else:
            response = ForgeResponse(
                success=False,
                action=request.action,
                error=f"Unsupported ForgeAction: {request.action}",
                execution_time_ms=(time.perf_counter() - start_time) * 1000,
            )

        return self._build_response(message=message, response=response)

    async def _execute_tool(self, request: ForgeRequest, message: AegisMessage) -> ForgeResponse:
        """
        Execute a registered tool.

        Args:
            request: The ForgeRequest specifying which tool and parameters.
            message: The original message (for context extraction).

        Returns:
            ForgeResponse with the tool execution result.
        """
        start_time = time.perf_counter()
        tool_name = request.tool_or_skill_name

        if not tool_name:
            return ForgeResponse(
                success=False,
                action=ForgeAction.EXECUTE_TOOL,
                error="tool_or_skill_name is required for EXECUTE_TOOL.",
                execution_time_ms=0.0,
            )

        if not self._tool_registry.has_tool(tool_name):
            return ForgeResponse(
                success=False,
                action=ForgeAction.EXECUTE_TOOL,
                error=f"Tool '{tool_name}' not found in registry.",
                execution_time_ms=(time.perf_counter() - start_time) * 1000,
            )

        tool_module = self._tool_registry.get_tool(tool_name)
        logger.info("forge.execute_tool", tool_name=tool_name)

        try:
            result = await asyncio.wait_for(
                tool_module.execute(request.parameters),
                timeout=request.timeout_seconds,
            )
            elapsed_ms = (time.perf_counter() - start_time) * 1000

            return ForgeResponse(
                success=result.success,
                action=ForgeAction.EXECUTE_TOOL,
                result=result.model_dump(),
                error=result.error,
                execution_time_ms=elapsed_ms,
            )
        except asyncio.TimeoutError:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            logger.error("forge.execute_tool.timeout", tool_name=tool_name,
                         timeout=request.timeout_seconds)
            return ForgeResponse(
                success=False,
                action=ForgeAction.EXECUTE_TOOL,
                error=f"Tool '{tool_name}' timed out after {request.timeout_seconds}s.",
                execution_time_ms=elapsed_ms,
            )
        except Exception as e:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            logger.error("forge.execute_tool.error", tool_name=tool_name, error=str(e))
            return ForgeResponse(
                success=False,
                action=ForgeAction.EXECUTE_TOOL,
                error=f"Tool execution failed: {str(e)}",
                execution_time_ms=elapsed_ms,
            )

    async def _execute_skill(self, request: ForgeRequest, message: AegisMessage) -> ForgeResponse:
        """
        Execute a registered skill with injected ForgeContext.

        Args:
            request: The ForgeRequest specifying which skill and parameters.
            message: The original message (for context extraction).

        Returns:
            ForgeResponse with the skill execution result.
        """
        start_time = time.perf_counter()
        skill_name = request.tool_or_skill_name

        if not skill_name:
            return ForgeResponse(
                success=False,
                action=ForgeAction.EXECUTE_SKILL,
                error="tool_or_skill_name is required for EXECUTE_SKILL.",
                execution_time_ms=0.0,
            )

        if not self._skill_registry.has_skill(skill_name):
            return ForgeResponse(
                success=False,
                action=ForgeAction.EXECUTE_SKILL,
                error=f"Skill '{skill_name}' not found in registry.",
                execution_time_ms=(time.perf_counter() - start_time) * 1000,
            )

        skill_module = self._skill_registry.get_skill(skill_name)
        logger.info("forge.execute_skill", skill_name=skill_name)

        # Build ForgeContext for this execution
        forge_context = ForgeContext(
            tenant_id=message.tenant_id,
            user_id=message.user_id,
            session_id=message.metadata.get("session_id", str(uuid4())),
            tool_registry=self._tool_registry,
            bus_publisher=self._bus,
            correlation_id=message.correlation_id,
        )

        try:
            result = await asyncio.wait_for(
                skill_module.execute(request.parameters, forge_context),
                timeout=request.timeout_seconds,
            )
            elapsed_ms = (time.perf_counter() - start_time) * 1000

            return ForgeResponse(
                success=result.success,
                action=ForgeAction.EXECUTE_SKILL,
                result=result.model_dump(),
                error=result.error,
                execution_time_ms=elapsed_ms,
            )
        except asyncio.TimeoutError:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            logger.error("forge.execute_skill.timeout", skill_name=skill_name,
                         timeout=request.timeout_seconds)
            return ForgeResponse(
                success=False,
                action=ForgeAction.EXECUTE_SKILL,
                error=f"Skill '{skill_name}' timed out after {request.timeout_seconds}s.",
                execution_time_ms=elapsed_ms,
            )
        except Exception as e:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            logger.error("forge.execute_skill.error", skill_name=skill_name, error=str(e))
            return ForgeResponse(
                success=False,
                action=ForgeAction.EXECUTE_SKILL,
                error=f"Skill execution failed: {str(e)}",
                execution_time_ms=elapsed_ms,
            )

    def _build_response(self, message: AegisMessage, response: ForgeResponse) -> AegisMessage:
        """Construct an AegisMessage response envelope."""
        return AegisMessage(
            message_id=str(uuid4()),
            correlation_id=message.correlation_id or message.message_id,
            source_agent=self.agent_id,
            target_agent=message.source_agent,
            message_type=MessageType.RESPONSE,
            tenant_id=message.tenant_id,
            user_id=message.user_id,
            action=f"forge.{response.action.value}.response",
            payload=response.model_dump(),
            priority=message.priority,
            metadata=message.metadata,
        )
''',

    # =========================================================================
    # TOOLS — Base + All OOBE Tools (Part VIII §8.1)
    # =========================================================================

    "aegis/forge/tools/__init__.py": '''
# aegis/forge/tools/__init__.py
# Implements: Part VIII, §8.1 — OOBE Tool Suite
"""
OOBE Tool Suite — All minimum tools required for Genesis OOBE exit criteria.
"""
''',

    "aegis/forge/tools/base.py": '''
# aegis/forge/tools/base.py
# Implements: Part VII, §7.1 — Tool Interface
"""
Base classes for the Tool interface.

Every tool module must expose:
    - manifest: ToolManifest
    - async def execute(params: dict) -> ToolResult
"""

from typing import Any, Optional
from pydantic import BaseModel


class ToolManifest(BaseModel):
    """
    Declarative manifest for a Tool.

    Attributes:
        name: Unique tool identifier.
        description: Human-readable description of what this tool does.
        version: Semantic version string.
        parameters_schema: JSON Schema defining valid input parameters.
        permissions_required: List of permission strings required to execute.
        timeout_seconds: Maximum allowed execution time.
    """
    name: str
    description: str
    version: str
    parameters_schema: dict = {}
    permissions_required: list[str] = []
    timeout_seconds: int = 30


class ToolResult(BaseModel):
    """
    Standard result returned by all tool executions.

    Attributes:
        success: Whether the tool executed successfully.
        data: Output data from the tool (type varies by tool).
        error: Error message if success is False.
    """
    success: bool
    data: Any = None
    error: Optional[str] = None
''',

    "aegis/forge/tools/file_read.py": '''
# aegis/forge/tools/file_read.py
# Implements: Part VIII, §8.1 — file_read tool
"""
Tool: file_read
Read the contents of a file at a given path.
"""

import os
import aiofiles

from aegis.forge.tools.base import ToolManifest, ToolResult


manifest = ToolManifest(
    name="file_read",
    description="Read the contents of a file at a given path.",
    version="1.0.0",
    parameters_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute or relative file path to read."},
            "encoding": {"type": "string", "default": "utf-8", "description": "File encoding."},
        },
        "required": ["path"],
    },
    permissions_required=["file.read"],
    timeout_seconds=10,
)


async def execute(params: dict) -> ToolResult:
    """
    Read file contents.

    Args:
        params: {"path": str, "encoding": str (optional, default utf-8)}

    Returns:
        ToolResult with file contents as data, or error message.
    """
    path = params.get("path")
    encoding = params.get("encoding", "utf-8")

    if not path:
        return ToolResult(success=False, error="Parameter 'path' is required.")

    if not os.path.exists(path):
        return ToolResult(success=False, error=f"File not found: {path}")

    if not os.path.isfile(path):
        return ToolResult(success=False, error=f"Path is not a file: {path}")

    try:
        async with aiofiles.open(path, mode="r", encoding=encoding) as f:
            content = await f.read()
        return ToolResult(success=True, data={"content": content, "path": path, "size_bytes": len(content.encode(encoding))})
    except PermissionError:
        return ToolResult(success=False, error=f"Permission denied: {path}")
    except UnicodeDecodeError as e:
        return ToolResult(success=False, error=f"Encoding error reading {path}: {str(e)}")
    except Exception as e:
        return ToolResult(success=False, error=f"Failed to read file: {str(e)}")
''',

    "aegis/forge/tools/file_write.py": '''
# aegis/forge/tools/file_write.py
# Implements: Part VIII, §8.1 — file_write tool
"""
Tool: file_write
Write content to a file (create or overwrite).
"""

import os
import aiofiles

from aegis.forge.tools.base import ToolManifest, ToolResult


manifest = ToolManifest(
    name="file_write",
    description="Write content to a file (create or overwrite).",
    version="1.0.0",
    parameters_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute or relative file path to write."},
            "content": {"type": "string", "description": "Content to write to the file."},
            "encoding": {"type": "string", "default": "utf-8", "description": "File encoding."},
            "create_dirs": {"type": "boolean", "default": True, "description": "Create parent directories if they don't exist."},
        },
        "required": ["path", "content"],
    },
    permissions_required=["file.write"],
    timeout_seconds=10,
)


async def execute(params: dict) -> ToolResult:
    """
    Write content to a file.

    Args:
        params: {"path": str, "content": str, "encoding": str, "create_dirs": bool}

    Returns:
        ToolResult confirming write, or error message.
    """
    path = params.get("path")
    content = params.get("content")
    encoding = params.get("encoding", "utf-8")
    create_dirs = params.get("create_dirs", True)

    if not path:
        return ToolResult(success=False, error="Parameter 'path' is required.")
    if content is None:
        return ToolResult(success=False, error="Parameter 'content' is required.")

    try:
        if create_dirs:
            dir_name = os.path.dirname(path)
            if dir_name:
                os.makedirs(dir_name, exist_ok=True)

        async with aiofiles.open(path, mode="w", encoding=encoding) as f:
            await f.write(content)

        size_bytes = len(content.encode(encoding))
        return ToolResult(success=True, data={"path": path, "size_bytes": size_bytes, "created": True})
    except PermissionError:
        return ToolResult(success=False, error=f"Permission denied: {path}")
    except Exception as e:
        return ToolResult(success=False, error=f"Failed to write file: {str(e)}")
''',

    "aegis/forge/tools/file_delete.py": '''
# aegis/forge/tools/file_delete.py
# Implements: Part VIII, §8.1 — file_delete tool
"""
Tool: file_delete
Delete a file at a given path.
"""

import os

from aegis.forge.tools.base import ToolManifest, ToolResult


manifest = ToolManifest(
    name="file_delete",
    description="Delete a file at a given path.",
    version="1.0.0",
    parameters_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute or relative file path to delete."},
        },
        "required": ["path"],
    },
    permissions_required=["file.delete"],
    timeout_seconds=10,
)


async def execute(params: dict) -> ToolResult:
    """
    Delete a file.

    Args:
        params: {"path": str}

    Returns:
        ToolResult confirming deletion, or error message.
    """
    path = params.get("path")

    if not path:
        return ToolResult(success=False, error="Parameter 'path' is required.")

    if not os.path.exists(path):
        return ToolResult(success=False, error=f"File not found: {path}")

    if not os.path.isfile(path):
        return ToolResult(success=False, error=f"Path is not a file (use caution with directories): {path}")

    try:
        os.remove(path)
        return ToolResult(success=True, data={"path": path, "deleted": True})
    except PermissionError:
        return ToolResult(success=False, error=f"Permission denied: {path}")
    except Exception as e:
        return ToolResult(success=False, error=f"Failed to delete file: {str(e)}")
''',

    "aegis/forge/tools/dir_list.py": '''
# aegis/forge/tools/dir_list.py
# Implements: Part VIII, §8.1 — dir_list tool
"""
Tool: dir_list
List contents of a directory.
"""

import os

from aegis.forge.tools.base import ToolManifest, ToolResult


manifest = ToolManifest(
    name="dir_list",
    description="List contents of a directory.",
    version="1.0.0",
    parameters_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Directory path to list."},
            "recursive": {"type": "boolean", "default": False, "description": "List recursively."},
            "include_hidden": {"type": "boolean", "default": False, "description": "Include hidden files/dirs."},
        },
        "required": ["path"],
    },
    permissions_required=["file.read"],
    timeout_seconds=15,
)


async def execute(params: dict) -> ToolResult:
    """
    List directory contents.

    Args:
        params: {"path": str, "recursive": bool, "include_hidden": bool}

    Returns:
        ToolResult with list of entries, or error message.
    """
    path = params.get("path")
    recursive = params.get("recursive", False)
    include_hidden = params.get("include_hidden", False)

    if not path:
        return ToolResult(success=False, error="Parameter 'path' is required.")

    if not os.path.exists(path):
        return ToolResult(success=False, error=f"Directory not found: {path}")

    if not os.path.isdir(path):
        return ToolResult(success=False, error=f"Path is not a directory: {path}")

    try:
        entries = []

        if recursive:
            for root, dirs, files in os.walk(path):
                if not include_hidden:
                    dirs[:] = [d for d in dirs if not d.startswith(".")]
                    files = [f for f in files if not f.startswith(".")]
                for name in dirs:
                    full_path = os.path.join(root, name)
                    entries.append({"name": name, "path": full_path, "type": "directory"})
                for name in files:
                    full_path = os.path.join(root, name)
                    entries.append({
                        "name": name,
                        "path": full_path,
                        "type": "file",
                        "size_bytes": os.path.getsize(full_path),
                    })
        else:
            for name in sorted(os.listdir(path)):
                if not include_hidden and name.startswith("."):
                    continue
                full_path = os.path.join(path, name)
                entry_type = "directory" if os.path.isdir(full_path) else "file"
                entry = {"name": name, "path": full_path, "type": entry_type}
                if entry_type == "file":
                    entry["size_bytes"] = os.path.getsize(full_path)
                entries.append(entry)

        return ToolResult(success=True, data={"path": path, "entries": entries, "count": len(entries)})
    except PermissionError:
        return ToolResult(success=False, error=f"Permission denied: {path}")
    except Exception as e:
        return ToolResult(success=False, error=f"Failed to list directory: {str(e)}")
''',

    "aegis/forge/tools/dir_create.py": '''
# aegis/forge/tools/dir_create.py
# Implements: Part VIII, §8.1 — dir_create tool
"""
Tool: dir_create
Create a directory (with mkdir -p semantics).
"""

import os

from aegis.forge.tools.base import ToolManifest, ToolResult


manifest = ToolManifest(
    name="dir_create",
    description="Create a directory (with mkdir -p semantics).",
    version="1.0.0",
    parameters_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Directory path to create."},
        },
        "required": ["path"],
    },
    permissions_required=["file.write"],
    timeout_seconds=5,
)


async def execute(params: dict) -> ToolResult:
    """
    Create a directory and all intermediate directories.

    Args:
        params: {"path": str}

    Returns:
        ToolResult confirming creation, or error message.
    """
    path = params.get("path")

    if not path:
        return ToolResult(success=False, error="Parameter 'path' is required.")

    try:
        already_existed = os.path.exists(path)
        os.makedirs(path, exist_ok=True)
        return ToolResult(success=True, data={
            "path": path,
            "created": not already_existed,
            "already_existed": already_existed,
        })
    except PermissionError:
        return ToolResult(success=False, error=f"Permission denied: {path}")
    except Exception as e:
        return ToolResult(success=False, error=f"Failed to create directory: {str(e)}")
''',

    "aegis/forge/tools/execute_shell_command.py": '''
# aegis/forge/tools/execute_shell_command.py
# Implements: Part VIII, §8.1 — execute_shell_command tool
# Security: Part XIII, RT-6 — Warden enforces allowlist
"""
Tool: execute_shell_command
Execute an arbitrary shell command. Warden-gated with explicit allowlist.

SECURITY NOTE: This tool is inherently dangerous. The Warden agent enforces
an allowlist of permitted commands/patterns BEFORE this tool is invoked.
The tool itself performs basic sanity checks but relies on Warden for policy.
"""

import asyncio
import shlex
from typing import Optional

from aegis.forge.tools.base import ToolManifest, ToolResult


# Default allowlist — restrictive. Expansion requires root/admin.
DEFAULT_ALLOWLIST_PREFIXES = [
    "git", "ls", "cat", "echo", "mkdir", "cp", "mv", "rm",
    "find", "grep", "wc", "head", "tail", "sort", "uniq",
    "python", "pip", "pytest", "which", "pwd", "date",
]

manifest = ToolManifest(
    name="execute_shell_command",
    description="Execute an arbitrary shell command. Warden-gated with explicit allowlist.",
    version="1.0.0",
    parameters_schema={
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "The shell command to execute."},
            "cwd": {"type": "string", "description": "Working directory for the command."},
            "timeout": {"type": "integer", "default": 30, "description": "Timeout in seconds."},
            "shell": {"type": "boolean", "default": True, "description": "Execute via shell."},
        },
        "required": ["command"],
    },
    permissions_required=["shell.execute"],
    timeout_seconds=60,
)


def _check_allowlist(command: str) -> Optional[str]:
    """
    Basic local allowlist check. This is a secondary defense —
    Warden performs the primary authorization check.

    Returns None if allowed, or an error string if blocked.
    """
    # Extract the base command
    try:
        parts = shlex.split(command)
        if not parts:
            return "Empty command."
        base_cmd = parts[0].split("/")[-1]  # Handle full paths
    except ValueError:
        # shlex can't parse — let shell handle it but flag
        base_cmd = command.strip().split()[0] if command.strip() else ""

    if not any(base_cmd.startswith(prefix) for prefix in DEFAULT_ALLOWLIST_PREFIXES):
        return (
            f"Command '{base_cmd}' is not in the local allowlist. "
            f"Allowed prefixes: {DEFAULT_ALLOWLIST_PREFIXES}"
        )
    return None


async def execute(params: dict) -> ToolResult:
    """
    Execute a shell command.

    Args:
        params: {"command": str, "cwd": str, "timeout": int, "shell": bool}

    Returns:
        ToolResult with stdout, stderr, and return code.
    """
    command = params.get("command")
    cwd = params.get("cwd")
    timeout = params.get("timeout", 30)
    use_shell = params.get("shell", True)

    if not command:
        return ToolResult(success=False, error="Parameter 'command' is required.")

    # Local allowlist check (secondary defense)
    block_reason = _check_allowlist(command)
    if block_reason:
        return ToolResult(success=False, error=f"Command blocked: {block_reason}")

    try:
        if use_shell:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )
        else:
            args = shlex.split(command)
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )

        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)

        return ToolResult(
            success=(proc.returncode == 0),
            data={
                "stdout": stdout.decode("utf-8", errors="replace").strip(),
                "stderr": stderr.decode("utf-8", errors="replace").strip(),
                "return_code": proc.returncode,
                "command": command,
            },
            error=stderr.decode("utf-8", errors="replace").strip() if proc.returncode != 0 else None,
        )
    except asyncio.TimeoutError:
        return ToolResult(success=False, error=f"Command timed out after {timeout}s: {command}")
    except FileNotFoundError:
        return ToolResult(success=False, error=f"Command not found or cwd does not exist.")
    except Exception as e:
        return ToolResult(success=False, error=f"Shell execution failed: {str(e)}")
''',

    "aegis/forge/tools/git_command.py": '''
# aegis/forge/tools/git_command.py
# Implements: Part VIII, §8.1 — git_command tool
"""
Tool: git_command
Execute a Git command (wrapper around shell for git-specific operations).
"""

import asyncio
import shlex

from aegis.forge.tools.base import ToolManifest, ToolResult


manifest = ToolManifest(
    name="git_command",
    description="Execute a Git command (wrapper around shell for git-specific operations).",
    version="1.0.0",
    parameters_schema={
        "type": "object",
        "properties": {
            "args": {"type": "string", "description": "Git arguments (e.g., 'status', 'commit -m \\"msg\\"')."},
            "cwd": {"type": "string", "description": "Repository working directory."},
            "timeout": {"type": "integer", "default": 30, "description": "Timeout in seconds."},
        },
        "required": ["args"],
    },
    permissions_required=["git.execute"],
    timeout_seconds=60,
)


async def execute(params: dict) -> ToolResult:
    """
    Execute a git command.

    Args:
        params: {"args": str, "cwd": str, "timeout": int}

    Returns:
        ToolResult with git command output.
    """
    args = params.get("args")
    cwd = params.get("cwd", ".")
    timeout = params.get("timeout", 30)

    if not args:
        return ToolResult(success=False, error="Parameter 'args' is required.")

    command = f"git {args}"

    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )

        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)

        stdout_str = stdout.decode("utf-8", errors="replace").strip()
        stderr_str = stderr.decode("utf-8", errors="replace").strip()

        return ToolResult(
            success=(proc.returncode == 0),
            data={
                "stdout": stdout_str,
                "stderr": stderr_str,
                "return_code": proc.returncode,
                "command": command,
            },
            error=stderr_str if proc.returncode != 0 else None,
        )
    except asyncio.TimeoutError:
        return ToolResult(success=False, error=f"Git command timed out after {timeout}s: {command}")
    except Exception as e:
        return ToolResult(success=False, error=f"Git command failed: {str(e)}")
''',

    "aegis/forge/tools/http_get.py": '''
# aegis/forge/tools/http_get.py
# Implements: Part VIII, §8.1 — http_get tool
"""
Tool: http_get
Perform an HTTP GET request and return the response.
"""

import aiohttp

from aegis.forge.tools.base import ToolManifest, ToolResult


manifest = ToolManifest(
    name="http_get",
    description="Perform an HTTP GET request and return the response.",
    version="1.0.0",
    parameters_schema={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "The URL to request."},
            "headers": {"type": "object", "default": {}, "description": "Optional HTTP headers."},
            "timeout": {"type": "integer", "default": 30, "description": "Request timeout in seconds."},
            "max_content_length": {"type": "integer", "default": 1048576, "description": "Max response size in bytes (default 1MB)."},
        },
        "required": ["url"],
    },
    permissions_required=["network.http"],
    timeout_seconds=60,
)


async def execute(params: dict) -> ToolResult:
    """
    Perform an HTTP GET request.

    Args:
        params: {"url": str, "headers": dict, "timeout": int, "max_content_length": int}

    Returns:
        ToolResult with response status, headers, and body.
    """
    url = params.get("url")
    headers = params.get("headers", {})
    timeout = params.get("timeout", 30)
    max_content_length = params.get("max_content_length", 1048576)

    if not url:
        return ToolResult(success=False, error="Parameter 'url' is required.")

    if not url.startswith(("http://", "https://")):
        return ToolResult(success=False, error="URL must start with http:// or https://")

    try:
        client_timeout = aiohttp.ClientTimeout(total=timeout)
        async with aiohttp.ClientSession(timeout=client_timeout) as session:
            async with session.get(url, headers=headers) as response:
                # Check content length before reading
                content_length = response.content_length
                if content_length and content_length > max_content_length:
                    return ToolResult(
                        success=False,
                        error=f"Response too large: {content_length} bytes (max: {max_content_length}).",
                    )

                body = await response.text(encoding="utf-8", errors="replace")
                if len(body) > max_content_length:
                    body = body[:max_content_length] + "\\n... [TRUNCATED]"

                return ToolResult(
                    success=(200 <= response.status < 400),
                    data={
                        "status_code": response.status,
                        "headers": dict(response.headers),
                        "body": body,
                        "url": str(response.url),
                        "content_type": response.content_type,
                    },
                    error=f"HTTP {response.status}" if response.status >= 400 else None,
                )
    except aiohttp.ClientError as e:
        return ToolResult(success=False, error=f"HTTP request failed: {str(e)}")
    except asyncio.TimeoutError:
        return ToolResult(success=False, error=f"HTTP GET timed out after {timeout}s: {url}")
    except Exception as e:
        return ToolResult(success=False, error=f"HTTP GET failed: {str(e)}")
''',

    "aegis/forge/tools/http_post.py": '''
# aegis/forge/tools/http_post.py
# Implements: Part VIII, §8.1 — http_post tool
"""
Tool: http_post
Perform an HTTP POST request.
"""

import asyncio
import json

import aiohttp

from aegis.forge.tools.base import ToolManifest, ToolResult


manifest = ToolManifest(
    name="http_post",
    description="Perform an HTTP POST request.",
    version="1.0.0",
    parameters_schema={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "The URL to POST to."},
            "body": {"type": "object", "default": {}, "description": "JSON body payload."},
            "headers": {"type": "object", "default": {}, "description": "Optional HTTP headers."},
            "timeout": {"type": "integer", "default": 30, "description": "Request timeout in seconds."},
            "content_type": {"type": "string", "default": "application/json", "description": "Content-Type header."},
        },
        "required": ["url"],
    },
    permissions_required=["network.http"],
    timeout_seconds=60,
)


async def execute(params: dict) -> ToolResult:
    """
    Perform an HTTP POST request.

    Args:
        params: {"url": str, "body": dict, "headers": dict, "timeout": int, "content_type": str}

    Returns:
        ToolResult with response status and body.
    """
    url = params.get("url")
    body = params.get("body", {})
    headers = params.get("headers", {})
    timeout = params.get("timeout", 30)
    content_type = params.get("content_type", "application/json")

    if not url:
        return ToolResult(success=False, error="Parameter 'url' is required.")

    if not url.startswith(("http://", "https://")):
        return ToolResult(success=False, error="URL must start with http:// or https://")

    headers.setdefault("Content-Type", content_type)

    try:
        client_timeout = aiohttp.ClientTimeout(total=timeout)
        async with aiohttp.ClientSession(timeout=client_timeout) as session:
            if content_type == "application/json":
                async with session.post(url, json=body, headers=headers) as response:
                    response_body = await response.text(encoding="utf-8", errors="replace")
                    return ToolResult(
                        success=(200 <= response.status < 400),
                        data={
                            "status_code": response.status,
                            "headers": dict(response.headers),
                            "body": response_body,
                            "url": str(response.url),
                        },
                        error=f"HTTP {response.status}" if response.status >= 400 else None,
                    )
            else:
                async with session.post(url, data=json.dumps(body), headers=headers) as response:
                    response_body = await response.text(encoding="utf-8", errors="replace")
                    return ToolResult(
                        success=(200 <= response.status < 400),
                        data={
                            "status_code": response.status,
                            "headers": dict(response.headers),
                            "body": response_body,
                            "url": str(response.url),
                        },
                        error=f"HTTP {response.status}" if response.status >= 400 else None,
                    )
    except aiohttp.ClientError as e:
        return ToolResult(success=False, error=f"HTTP POST failed: {str(e)}")
    except asyncio.TimeoutError:
        return ToolResult(success=False, error=f"HTTP POST timed out after {timeout}s: {url}")
    except Exception as e:
        return ToolResult(success=False, error=f"HTTP POST failed: {str(e)}")
''',

    "aegis/forge/tools/json_parse.py": '''
# aegis/forge/tools/json_parse.py
# Implements: Part VIII, §8.1 — json_parse tool
"""
Tool: json_parse
Parse and extract data from a JSON string/file.
Stateless utility — no permissions required.
"""

import json
from typing import Any

from aegis.forge.tools.base import ToolManifest, ToolResult


manifest = ToolManifest(
    name="json_parse",
    description="Parse and extract data from a JSON string/file.",
    version="1.0.0",
    parameters_schema={
        "type": "object",
        "properties": {
            "data": {"type": "string", "description": "JSON string to parse."},
            "path": {"type": "string", "description": "Optional dot-notation path to extract (e.g., 'results.0.name')."},
        },
        "required": ["data"],
    },
    permissions_required=[],  # Stateless utility
    timeout_seconds=5,
)


def _extract_path(obj: Any, path: str) -> Any:
    """Extract a value from a nested structure using dot notation."""
    parts = path.split(".")
    current = obj
    for part in parts:
        if isinstance(current, dict):
            if part in current:
                current = current[part]
            else:
                raise KeyError(f"Key '{part}' not found in object.")
        elif isinstance(current, (list, tuple)):
            try:
                idx = int(part)
                current = current[idx]
            except (ValueError, IndexError) as e:
                raise KeyError(f"Invalid index '{part}': {str(e)}")
        else:
            raise KeyError(f"Cannot traverse into {type(current).__name__} with key '{part}'.")
    return current


async def execute(params: dict) -> ToolResult:
    """
    Parse JSON and optionally extract a value by path.

    Args:
        params: {"data": str, "path": str (optional)}

    Returns:
        ToolResult with parsed JSON data or extracted value.
    """
    data = params.get("data")
    path = params.get("path")

    if not data:
        return ToolResult(success=False, error="Parameter 'data' is required.")

    try:
        parsed = json.loads(data)
    except json.JSONDecodeError as e:
        return ToolResult(success=False, error=f"Invalid JSON: {str(e)}")

    if path:
        try:
            extracted = _extract_path(parsed, path)
            return ToolResult(success=True, data={"extracted": extracted, "path": path})
        except KeyError as e:
            return ToolResult(success=False, error=f"Path extraction failed: {str(e)}")
    else:
        return ToolResult(success=True, data={"parsed": parsed})
''',

    "aegis/forge/tools/schedule_job.py": '''
# aegis/forge/tools/schedule_job.py
# Implements: Part VIII, §8.1 — schedule_job tool
# Implements: Part XI — Scheduler Protocol
"""
Tool: schedule_job
Register a new job with the Scheduler.
"""

from datetime import datetime, timezone
from uuid import uuid4

from aegis.forge.tools.base import ToolManifest, ToolResult


manifest = ToolManifest(
    name="schedule_job",
    description="Register a new job with the Scheduler.",
    version="1.0.0",
    parameters_schema={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Human-readable job name."},
            "description": {"type": "string", "description": "Job description."},
            "schedule_type": {"type": "string", "enum": ["cron", "interval", "date"], "description": "Scheduling type."},
            "schedule_config": {"type": "object", "description": "Schedule configuration (e.g., {hour: 2, minute: 0})."},
            "action": {"type": "string", "description": "AegisMessage action to dispatch (e.g., 'forge.execute_skill')."},
            "action_payload": {"type": "object", "default": {}, "description": "Payload for the action."},
            "enabled": {"type": "boolean", "default": True, "description": "Whether the job is active."},
        },
        "required": ["name", "schedule_type", "schedule_config", "action"],
    },
    permissions_required=["scheduler.manage"],
    timeout_seconds=10,
)


async def execute(params: dict) -> ToolResult:
    """
    Register a scheduled job.

    This tool creates the job definition and persists it. The actual
    scheduling is handled by the System Manager's Scheduler service (CHUNK-011).

    Args:
        params: ScheduledJob-compatible parameters.

    Returns:
        ToolResult with the created job definition.
    """
    name = params.get("name")
    schedule_type = params.get("schedule_type")
    schedule_config = params.get("schedule_config")
    action = params.get("action")

    if not name:
        return ToolResult(success=False, error="Parameter 'name' is required.")
    if not schedule_type:
        return ToolResult(success=False, error="Parameter 'schedule_type' is required.")
    if schedule_type not in ("cron", "interval", "date"):
        return ToolResult(success=False, error=f"Invalid schedule_type: {schedule_type}. Must be 'cron', 'interval', or 'date'.")
    if not schedule_config:
        return ToolResult(success=False, error="Parameter 'schedule_config' is required.")
    if not action:
        return ToolResult(success=False, error="Parameter 'action' is required.")

    # Build the job definition
    job_id = str(uuid4())
    job_definition = {
        "job_id": job_id,
        "name": name,
        "description": params.get("description", ""),
        "schedule_type": schedule_type,
        "schedule_config": schedule_config,
        "action": action,
        "action_payload": params.get("action_payload", {}),
        "enabled": params.get("enabled", True),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "last_run": None,
        "next_run": None,
    }

    # NOTE: Actual persistence and APScheduler registration is handled by
    # the Scheduler service in CHUNK-011. This tool creates and returns the
    # validated job definition for the Scheduler to consume.

    return ToolResult(
        success=True,
        data={
            "job": job_definition,
            "message": f"Job '{name}' (ID: {job_id}) created. Pending scheduler registration.",
        },
    )
''',

    # =========================================================================
    # SKILLS — Base + All OOBE Skills (Part VIII §8.2)
    # =========================================================================

    "aegis/forge/skills/__init__.py": '''
# aegis/forge/skills/__init__.py
# Implements: Part VIII, §8.2 — OOBE Skill Suite
"""
OOBE Skill Suite — All minimum skills required for Genesis OOBE exit criteria.
"""
''',

    "aegis/forge/skills/base.py": '''
# aegis/forge/skills/base.py
# Implements: Part VII, §7.2 — Skill Interface
"""
Base classes for the Skill interface.

Every skill module must expose:
    - manifest: SkillManifest
    - async def execute(params: dict, forge_context: ForgeContext) -> SkillResult
"""

from typing import Any, Optional
from pydantic import BaseModel


class SkillManifest(BaseModel):
    """
    Declarative manifest for a Skill.

    Attributes:
        name: Unique skill identifier.
        description: Human-readable description.
        version: Semantic version string.
        parameters_schema: JSON Schema defining valid input parameters.
        permissions_required: Permission strings required for execution.
        tools_used: List of tool names this skill depends on.
        requires_oracle: Whether this skill needs LLM access.
        scope: "system" (shared) or "user" (per-user).
        timeout_seconds: Maximum execution time.
    """
    name: str
    description: str
    version: str
    parameters_schema: dict = {}
    permissions_required: list[str] = []
    tools_used: list[str] = []
    requires_oracle: bool = False
    scope: str = "system"
    timeout_seconds: int = 120


class SkillResult(BaseModel):
    """
    Standard result returned by all skill executions.

    Attributes:
        success: Whether the skill completed successfully.
        data: Output data from the skill.
        steps_executed: Audit trail of operations performed.
        error: Error message if success is False.
    """
    success: bool
    data: Any = None
    steps_executed: list[str] = []
    error: Optional[str] = None
''',

    "aegis/forge/skills/web_research.py": '''
# aegis/forge/skills/web_research.py
# Implements: Part VIII, §8.2 — web_research skill
"""
Skill: web_research
Conduct multi-step web research: search → fetch → extract → summarize.
"""

from aegis.forge.skills.base import SkillManifest, SkillResult


manifest = SkillManifest(
    name="web_research",
    description="Conduct multi-step web research: search, fetch, extract, and summarize.",
    version="1.0.0",
    parameters_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The research query/topic."},
            "urls": {"type": "array", "items": {"type": "string"}, "description": "Optional specific URLs to research."},
            "max_sources": {"type": "integer", "default": 3, "description": "Maximum number of sources to fetch."},
            "summary_style": {"type": "string", "default": "concise", "description": "Summary style: concise, detailed, bullet_points."},
        },
        "required": ["query"],
    },
    permissions_required=["network.http", "tool.execute", "skill.execute"],
    tools_used=["http_get"],
    requires_oracle=True,
    scope="system",
    timeout_seconds=120,
)


async def execute(params: dict, forge_context) -> SkillResult:
    """
    Execute multi-step web research.

    Steps:
    1. If URLs provided, use them. Otherwise, construct search URL.
    2. Fetch content from each URL via http_get tool.
    3. Extract relevant text content.
    4. Summarize via Oracle.

    Args:
        params: {"query": str, "urls": list[str], "max_sources": int, "summary_style": str}
        forge_context: ForgeContext with tool/oracle access.

    Returns:
        SkillResult with research summary and sources.
    """
    query = params.get("query")
    urls = params.get("urls", [])
    max_sources = params.get("max_sources", 3)
    summary_style = params.get("summary_style", "concise")

    if not query:
        return SkillResult(success=False, error="Parameter 'query' is required.")

    steps = []
    fetched_content = []

    # Step 1: Determine URLs to fetch
    if not urls:
        # Use a search engine URL as fallback
        search_url = f"https://www.google.com/search?q={query.replace(' ', '+')}"
        urls = [search_url]
        steps.append(f"Generated search URL for: {query}")

    # Step 2: Fetch content from URLs
    for i, url in enumerate(urls[:max_sources]):
        result = await forge_context.invoke_tool("http_get", {"url": url, "timeout": 15})
        if result.success and result.data:
            body = result.data.get("body", "")
            # Truncate to reasonable size for LLM processing
            truncated = body[:10000] if len(body) > 10000 else body
            fetched_content.append({
                "url": url,
                "content": truncated,
                "status": result.data.get("status_code", 0),
            })
            steps.append(f"Fetched: {url} (status: {result.data.get('status_code')})")
        else:
            steps.append(f"Failed to fetch: {url} — {result.error}")

    if not fetched_content:
        return SkillResult(
            success=False,
            data={"query": query, "sources_attempted": len(urls)},
            steps_executed=steps,
            error="Could not fetch any sources.",
        )

    # Step 3 & 4: Summarize via Oracle
    combined_text = "\\n\\n---\\n\\n".join(
        [f"Source: {c['url']}\\n{c['content']}" for c in fetched_content]
    )

    style_instructions = {
        "concise": "Provide a concise 2-3 paragraph summary.",
        "detailed": "Provide a detailed summary covering all key points.",
        "bullet_points": "Provide a summary as structured bullet points.",
    }

    oracle_response = await forge_context.invoke_oracle({
        "action": "query",
        "prompt": f"Based on the following web content, answer this research query: {query}\\n\\n{combined_text}",
        "system_prompt": f"You are a research assistant. {style_instructions.get(summary_style, style_instructions['concise'])} Cite sources where possible.",
        "temperature": 0.3,
        "max_tokens": 2000,
    })

    steps.append("Summarized content via Oracle")

    if oracle_response.get("success"):
        return SkillResult(
            success=True,
            data={
                "query": query,
                "summary": oracle_response.get("content", ""),
                "sources": [{"url": c["url"], "status": c["status"]} for c in fetched_content],
                "sources_fetched": len(fetched_content),
                "model_used": oracle_response.get("model_used", "unknown"),
            },
            steps_executed=steps,
        )
    else:
        return SkillResult(
            success=False,
            data={"query": query, "raw_content": [c["url"] for c in fetched_content]},
            steps_executed=steps,
            error=f"Oracle summarization failed: {oracle_response.get('error', 'Unknown error')}",
        )
''',

    "aegis/forge/skills/summarize_document.py": '''
# aegis/forge/skills/summarize_document.py
# Implements: Part VIII, §8.2 — summarize_document skill
"""
Skill: summarize_document
Read a local file and produce a structured summary.
"""

from aegis.forge.skills.base import SkillManifest, SkillResult


manifest = SkillManifest(
    name="summarize_document",
    description="Read a local file and produce a structured summary.",
    version="1.0.0",
    parameters_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the file to summarize."},
            "summary_type": {"type": "string", "default": "structured", "description": "Summary type: structured, executive, technical."},
            "max_length": {"type": "integer", "default": 500, "description": "Maximum summary length in words."},
        },
        "required": ["path"],
    },
    permissions_required=["file.read", "tool.execute", "skill.execute"],
    tools_used=["file_read"],
    requires_oracle=True,
    scope="system",
    timeout_seconds=60,
)


async def execute(params: dict, forge_context) -> SkillResult:
    """
    Read a file and produce a structured summary.

    Steps:
    1. Read file content via file_read tool.
    2. Send content to Oracle for summarization.

    Args:
        params: {"path": str, "summary_type": str, "max_length": int}
        forge_context: ForgeContext with tool/oracle access.

    Returns:
        SkillResult with structured summary.
    """
    path = params.get("path")
    summary_type = params.get("summary_type", "structured")
    max_length = params.get("max_length", 500)

    if not path:
        return SkillResult(success=False, error="Parameter 'path' is required.")

    steps = []

    # Step 1: Read file
    read_result = await forge_context.invoke_tool("file_read", {"path": path})
    if not read_result.success:
        return SkillResult(
            success=False,
            steps_executed=["tool:file_read (failed)"],
            error=f"Failed to read file: {read_result.error}",
        )

    content = read_result.data.get("content", "")
    size_bytes = read_result.data.get("size_bytes", 0)
    steps.append(f"Read file: {path} ({size_bytes} bytes)")

    if not content.strip():
        return SkillResult(
            success=False,
            steps_executed=steps,
            error="File is empty — nothing to summarize.",
        )

    # Step 2: Summarize via Oracle
    type_instructions = {
        "structured": "Produce a structured summary with sections: Overview, Key Points, Details, Conclusions.",
        "executive": "Produce an executive summary suitable for a busy decision-maker. Lead with the bottom line.",
        "technical": "Produce a technical summary highlighting architecture, implementation details, and dependencies.",
    }

    oracle_response = await forge_context.invoke_oracle({
        "action": "query",
        "prompt": f"Summarize the following document content (max {max_length} words):\\n\\n{content[:15000]}",
        "system_prompt": f"You are a document summarization specialist. {type_instructions.get(summary_type, type_instructions['structured'])}",
        "temperature": 0.3,
        "max_tokens": max_length * 2,  # Rough tokens-to-words ratio
    })

    steps.append(f"Summarized via Oracle ({summary_type} style)")

    if oracle_response.get("success"):
        return SkillResult(
            success=True,
            data={
                "path": path,
                "summary": oracle_response.get("content", ""),
                "summary_type": summary_type,
                "source_size_bytes": size_bytes,
                "model_used": oracle_response.get("model_used", "unknown"),
            },
            steps_executed=steps,
        )
    else:
        return SkillResult(
            success=False,
            steps_executed=steps,
            error=f"Oracle summarization failed: {oracle_response.get('error', 'Unknown error')}",
        )
''',

    "aegis/forge/skills/manage_git_workflow.py": '''
# aegis/forge/skills/manage_git_workflow.py
# Implements: Part VIII, §8.2 — manage_git_workflow skill
# Validates: UC-4 — Git Workflow
"""
Skill: manage_git_workflow
Execute a full feature branch lifecycle:
create branch → stage → commit → push → merge to main → push.
"""

from aegis.forge.skills.base import SkillManifest, SkillResult


manifest = SkillManifest(
    name="manage_git_workflow",
    description="Execute a full feature branch lifecycle: create branch, stage, commit, push, merge to main, push.",
    version="1.0.0",
    parameters_schema={
        "type": "object",
        "properties": {
            "branch_name": {"type": "string", "description": "Name of the feature branch to create."},
            "commit_message": {"type": "string", "description": "Commit message for the staged changes."},
            "cwd": {"type": "string", "default": ".", "description": "Repository working directory."},
            "files_to_stage": {"type": "array", "items": {"type": "string"}, "default": ["."], "description": "Files to stage (default: all)."},
            "push": {"type": "boolean", "default": True, "description": "Whether to push to remote."},
            "merge_to_main": {"type": "boolean", "default": True, "description": "Whether to merge branch into main."},
            "main_branch": {"type": "string", "default": "main", "description": "Name of the main branch."},
        },
        "required": ["branch_name", "commit_message"],
    },
    permissions_required=["git.execute", "shell.execute"],
    tools_used=["git_command", "execute_shell_command"],
    requires_oracle=False,
    scope="system",
    timeout_seconds=120,
)


async def execute(params: dict, forge_context) -> SkillResult:
    """
    Execute a full Git feature branch workflow.

    Steps:
    1. Create and checkout feature branch
    2. Stage specified files
    3. Commit with message
    4. Push feature branch (if enabled)
    5. Checkout main branch
    6. Merge feature branch into main
    7. Push main (if enabled)

    Args:
        params: Git workflow parameters.
        forge_context: ForgeContext with tool access.

    Returns:
        SkillResult with workflow execution details.
    """
    branch_name = params.get("branch_name")
    commit_message = params.get("commit_message")
    cwd = params.get("cwd", ".")
    files_to_stage = params.get("files_to_stage", ["."])
    push = params.get("push", True)
    merge_to_main = params.get("merge_to_main", True)
    main_branch = params.get("main_branch", "main")

    if not branch_name:
        return SkillResult(success=False, error="Parameter 'branch_name' is required.")
    if not commit_message:
        return SkillResult(success=False, error="Parameter 'commit_message' is required.")

    steps = []
    results = {}

    async def git(args: str) -> dict:
        """Helper to run git commands and track steps."""
        result = await forge_context.invoke_tool("git_command", {"args": args, "cwd": cwd})
        return {"success": result.success, "data": result.data, "error": result.error}

    # Step 1: Create and checkout feature branch
    r = await git(f"checkout -b {branch_name}")
    steps.append(f"git checkout -b {branch_name}")
    results["create_branch"] = r
    if not r["success"]:
        # Branch might already exist — try checkout
        r = await git(f"checkout {branch_name}")
        steps.append(f"git checkout {branch_name} (fallback)")
        results["checkout_branch"] = r
        if not r["success"]:
            return SkillResult(
                success=False,
                data=results,
                steps_executed=steps,
                error=f"Failed to create/checkout branch '{branch_name}': {r['error']}",
            )

    # Step 2: Stage files
    stage_args = " ".join(files_to_stage)
    r = await git(f"add {stage_args}")
    steps.append(f"git add {stage_args}")
    results["stage"] = r
    if not r["success"]:
        return SkillResult(
            success=False,
            data=results,
            steps_executed=steps,
            error=f"Failed to stage files: {r['error']}",
        )

    # Step 3: Commit
    r = await git(f'commit -m "{commit_message}"')
    steps.append(f"git commit -m \\"{commit_message}\\"")
    results["commit"] = r
    if not r["success"]:
        # Check if it's "nothing to commit"
        error_msg = r.get("error", "") or ""
        if "nothing to commit" in error_msg.lower():
            steps.append("Nothing to commit — working tree clean")
            results["commit_note"] = "Nothing to commit"
        else:
            return SkillResult(
                success=False,
                data=results,
                steps_executed=steps,
                error=f"Failed to commit: {r['error']}",
            )

    # Step 4: Push feature branch
    if push:
        r = await git(f"push -u origin {branch_name}")
        steps.append(f"git push -u origin {branch_name}")
        results["push_feature"] = r
        if not r["success"]:
            # Gracefully handle no remote
            error_msg = r.get("error", "") or ""
            if "remote" in error_msg.lower() or "not found" in error_msg.lower():
                steps.append("No remote configured — push skipped (graceful)")
                results["push_note"] = "No remote configured"
            else:
                return SkillResult(
                    success=False,
                    data=results,
                    steps_executed=steps,
                    error=f"Failed to push feature branch: {r['error']}",
                )

    # Step 5 & 6: Merge to main
    if merge_to_main:
        # Checkout main
        r = await git(f"checkout {main_branch}")
        steps.append(f"git checkout {main_branch}")
        results["checkout_main"] = r
        if not r["success"]:
            return SkillResult(
                success=False,
                data=results,
                steps_executed=steps,
                error=f"Failed to checkout {main_branch}: {r['error']}",
            )

        # Merge feature branch
        r = await git(f"merge {branch_name}")
        steps.append(f"git merge {branch_name}")
        results["merge"] = r
        if not r["success"]:
            return SkillResult(
                success=False,
                data=results,
                steps_executed=steps,
                error=f"Merge failed: {r['error']}",
            )

        # Step 7: Push main
        if push:
            r = await git(f"push origin {main_branch}")
            steps.append(f"git push origin {main_branch}")
            results["push_main"] = r
            if not r["success"]:
                error_msg = r.get("error", "") or ""
                if "remote" in error_msg.lower() or "not found" in error_msg.lower():
                    steps.append("No remote configured — push main skipped (graceful)")
                    results["push_main_note"] = "No remote configured"
                else:
                    return SkillResult(
                        success=False,
                        data=results,
                        steps_executed=steps,
                        error=f"Failed to push main: {r['error']}",
                    )

    return SkillResult(
        success=True,
        data={
            "branch": branch_name,
            "main_branch": main_branch,
            "commit_message": commit_message,
            "merged": merge_to_main,
            "pushed": push,
            "results": results,
        },
        steps_executed=steps,
    )
''',

    "aegis/forge/skills/red_team_analysis.py": '''
# aegis/forge/skills/red_team_analysis.py
# Implements: Part VIII, §8.2 — red_team_analysis skill
"""
Skill: red_team_analysis
Analyze a given specification/plan for risks, blind spots, and failure modes.
"""

from aegis.forge.skills.base import SkillManifest, SkillResult


manifest = SkillManifest(
    name="red_team_analysis",
    description="Analyze a given specification/plan for risks, blind spots, and failure modes.",
    version="1.0.0",
    parameters_schema={
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "The specification, plan, or document content to analyze."},
            "focus_areas": {"type": "array", "items": {"type": "string"}, "description": "Optional specific areas to focus on (e.g., 'security', 'scalability')."},
            "severity_threshold": {"type": "string", "default": "medium", "description": "Minimum severity to report: low, medium, high, critical."},
        },
        "required": ["content"],
    },
    permissions_required=["skill.execute"],
    tools_used=[],
    requires_oracle=True,
    scope="system",
    timeout_seconds=90,
)


async def execute(params: dict, forge_context) -> SkillResult:
    """
    Perform red team analysis on provided content.

    Steps:
    1. Construct a red-team analysis prompt.
    2. Send to Oracle for analysis.
    3. Structure and return findings.

    Args:
        params: {"content": str, "focus_areas": list[str], "severity_threshold": str}
        forge_context: ForgeContext with oracle access.

    Returns:
        SkillResult with structured risk analysis.
    """
    content = params.get("content")
    focus_areas = params.get("focus_areas", [])
    severity_threshold = params.get("severity_threshold", "medium")

    if not content:
        return SkillResult(success=False, error="Parameter 'content' is required.")

    steps = []

    # Build focus area instructions
    focus_instruction = ""
    if focus_areas:
        focus_instruction = f"\\nFocus especially on these areas: {', '.join(focus_areas)}."

    system_prompt = (
        "You are a senior security and systems architect performing a Red Team analysis. "
        "Your job is to find risks, blind spots, failure modes, and vulnerabilities in the "
        "provided specification or plan. Be thorough, adversarial, and constructive.\\n\\n"
        "For each finding, provide:\\n"
        "1. Risk ID (RT-XXX)\\n"
        "2. Severity (critical/high/medium/low)\\n"
        "3. Category (security/reliability/scalability/design/operational)\\n"
        "4. Description of the risk\\n"
        "5. Attack vector or failure scenario\\n"
        "6. Recommended mitigation\\n\\n"
        f"Minimum severity to report: {severity_threshold}.{focus_instruction}\\n\\n"
        "Output as structured JSON with a 'findings' array."
    )

    oracle_response = await forge_context.invoke_oracle({
        "action": "structured",
        "prompt": f"Perform a Red Team analysis on the following:\\n\\n{content[:15000]}",
        "system_prompt": system_prompt,
        "temperature": 0.4,
        "max_tokens": 3000,
        "response_format": "json",
    })

    steps.append("Red team analysis via Oracle")

    if oracle_response.get("success"):
        return SkillResult(
            success=True,
            data={
                "analysis": oracle_response.get("content", ""),
                "focus_areas": focus_areas,
                "severity_threshold": severity_threshold,
                "content_length": len(content),
                "model_used": oracle_response.get("model_used", "unknown"),
            },
            steps_executed=steps,
        )
    else:
        return SkillResult(
            success=False,
            steps_executed=steps,
            error=f"Oracle analysis failed: {oracle_response.get('error', 'Unknown error')}",
        )
''',

    "aegis/forge/skills/rlm_protocol.py": '''
# aegis/forge/skills/rlm_protocol.py
# Implements: Part VIII, §8.2 — RLM_protocol skill
"""
Skill: rlm_protocol
Reflective Learning Memory — after completing a task, extract lessons learned
and promote them to Lexicon (L1/L2).
"""

from aegis.forge.skills.base import SkillManifest, SkillResult


manifest = SkillManifest(
    name="rlm_protocol",
    description="Reflective Learning Memory — extract lessons learned from a completed task and promote to Lexicon memory.",
    version="1.0.0",
    parameters_schema={
        "type": "object",
        "properties": {
            "task_description": {"type": "string", "description": "Description of the completed task."},
            "task_outcome": {"type": "string", "description": "What happened — outcome, results, observations."},
            "context": {"type": "string", "description": "Additional context about the task environment."},
            "domain": {"type": "string", "description": "Knowledge domain for categorization (e.g., 'python', 'architecture')."},
        },
        "required": ["task_description", "task_outcome"],
    },
    permissions_required=["skill.execute", "memory.write"],
    tools_used=[],
    requires_oracle=True,
    scope="system",
    timeout_seconds=60,
)


async def execute(params: dict, forge_context) -> SkillResult:
    """
    Execute Reflective Learning Memory protocol.

    Steps:
    1. Send task description + outcome to Oracle for reflection.
    2. Oracle extracts: lessons learned, patterns, knowledge to retain.
    3. Store extracted knowledge in Lexicon via context store.
    4. Promote to appropriate tier (L1 for facts, L2 for procedures).

    Args:
        params: {"task_description": str, "task_outcome": str, "context": str, "domain": str}
        forge_context: ForgeContext with oracle and lexicon access.

    Returns:
        SkillResult with extracted lessons and promotion status.
    """
    task_description = params.get("task_description")
    task_outcome = params.get("task_outcome")
    context = params.get("context", "")
    domain = params.get("domain", "general")

    if not task_description:
        return SkillResult(success=False, error="Parameter 'task_description' is required.")
    if not task_outcome:
        return SkillResult(success=False, error="Parameter 'task_outcome' is required.")

    steps = []

    # Step 1: Reflect via Oracle
    system_prompt = (
        "You are a learning extraction system. Analyze the completed task and extract:\\n"
        "1. **Factual Knowledge** (L1): New facts, tools, libraries, APIs, or domain knowledge learned.\\n"
        "2. **Procedural Knowledge** (L2): Patterns, workflows, conventions, or processes that worked well.\\n"
        "3. **Anti-Patterns**: Things that didn't work or should be avoided.\\n"
        "4. **Connections**: How this relates to existing knowledge.\\n\\n"
        "Output as JSON with keys: factual_knowledge (array), procedural_knowledge (array), "
        "anti_patterns (array), connections (array). Each item should have 'content' and 'confidence' (0-1) fields."
    )

    prompt = (
        f"Task: {task_description}\\n\\n"
        f"Outcome: {task_outcome}\\n\\n"
        f"Context: {context}\\n\\n"
        f"Domain: {domain}\\n\\n"
        "Extract all reusable knowledge from this experience."
    )

    oracle_response = await forge_context.invoke_oracle({
        "action": "structured",
        "prompt": prompt,
        "system_prompt": system_prompt,
        "temperature": 0.3,
        "max_tokens": 2000,
        "response_format": "json",
    })

    steps.append("Reflective analysis via Oracle")

    if not oracle_response.get("success"):
        return SkillResult(
            success=False,
            steps_executed=steps,
            error=f"Oracle reflection failed: {oracle_response.get('error', 'Unknown error')}",
        )

    extracted = oracle_response.get("content", {})
    steps.append(f"Extracted knowledge for domain: {domain}")

    # Step 2: Store in Lexicon (via bus)
    # Store as episodic memory (L3) first, then promote
    store_response = await forge_context.get_context(
        query=f"RLM: {task_description}",
        scope=["L1", "L2"],
        token_budget=500,
    )
    steps.append("Queried existing Lexicon context for deduplication")

    # NOTE: Actual Lexicon STORE_MEMORY and PROMOTE_MEMORY would be done via
    # bus messages to the Lexicon agent. In OOBE, we structure the data
    # for Lexicon consumption and return it for the orchestrator to route.

    return SkillResult(
        success=True,
        data={
            "task_description": task_description,
            "domain": domain,
            "extracted_knowledge": extracted,
            "promotion_targets": {
                "L1_factual": "factual_knowledge items with confidence > 0.7",
                "L2_procedural": "procedural_knowledge items with confidence > 0.7",
            },
            "model_used": oracle_response.get("model_used", "unknown"),
            "existing_context_checked": bool(store_response.get("fragments")),
        },
        steps_executed=steps,
    )
''',

    "aegis/forge/skills/onboard_user.py": '''
# aegis/forge/skills/onboard_user.py
# Implements: Part VIII, §8.2 — onboard_user skill
# Validates: UC-5 — User Onboarding
"""
Skill: onboard_user
Interactive skill to create a new user:
gather info → call Identity Agent → initialize Lexicon memory tiers.
"""

from aegis.forge.skills.base import SkillManifest, SkillResult


manifest = SkillManifest(
    name="onboard_user",
    description="Create a new user: validate input, create via Identity Agent, initialize Lexicon memory tiers.",
    version="1.0.0",
    parameters_schema={
        "type": "object",
        "properties": {
            "username": {"type": "string", "description": "Username for the new user."},
            "display_name": {"type": "string", "description": "Display name for the new user."},
            "email": {"type": "string", "description": "Optional email address."},
            "role": {"type": "string", "default": "member", "description": "Role to assign: member, admin, observer."},
            "tenant_id": {"type": "string", "description": "Tenant to create the user in (uses context tenant if not provided)."},
        },
        "required": ["username"],
    },
    permissions_required=["user.create", "memory.write"],
    tools_used=[],
    requires_oracle=False,
    scope="system",
    timeout_seconds=30,
)


async def execute(params: dict, forge_context) -> SkillResult:
    """
    Onboard a new user.

    Steps:
    1. Validate input parameters.
    2. Send CREATE_USER request to Identity Agent (via bus).
    3. Initialize Lexicon memory tiers for the new user.
    4. Return confirmation.

    NOTE: In full implementation, steps 2 & 3 are routed via the message bus
    to Identity and Lexicon agents respectively. For OOBE, we structure
    the requests and return them for the orchestrator to dispatch.

    Args:
        params: {"username": str, "display_name": str, "email": str, "role": str, "tenant_id": str}
        forge_context: ForgeContext.

    Returns:
        SkillResult with user creation details.
    """
    username = params.get("username")
    display_name = params.get("display_name", username)
    email = params.get("email")
    role = params.get("role", "member")
    tenant_id = params.get("tenant_id", forge_context.tenant_id)

    if not username:
        return SkillResult(success=False, error="Parameter 'username' is required.")

    # Validate role
    valid_roles = ["member", "admin", "observer"]
    if role not in valid_roles:
        return SkillResult(
            success=False,
            error=f"Invalid role '{role}'. Must be one of: {valid_roles}",
        )

    # Validate username format
    if len(username) < 2 or len(username) > 64:
        return SkillResult(success=False, error="Username must be 2-64 characters.")
    if not username.replace("_", "").replace("-", "").isalnum():
        return SkillResult(success=False, error="Username must be alphanumeric (underscores and hyphens allowed).")

    steps = []

    # Step 1: Construct Identity Agent request
    identity_request = {
        "action": "create_user",
        "tenant_id": tenant_id,
        "payload": {
            "username": username,
            "display_name": display_name,
            "email": email,
            "role": role,
            "is_root": False,
        },
    }
    steps.append(f"Prepared Identity CREATE_USER request for '{username}'")

    # Step 2: Construct Lexicon initialization request
    lexicon_init_request = {
        "action": "initialize_user_memory",
        "tenant_id": tenant_id,
        "payload": {
            "username": username,
            "tiers_to_initialize": ["L0", "L1", "L2", "L3", "L4"],
            "l0_defaults": {
                "display_name": display_name,
                "role": role,
                "created_via": "onboard_user skill",
            },
        },
    }
    steps.append(f"Prepared Lexicon memory initialization for '{username}'")

    # In full OOBE, these would be dispatched via the bus.
    # For now, return structured requests for the orchestrator.

    return SkillResult(
        success=True,
        data={
            "username": username,
            "display_name": display_name,
            "email": email,
            "role": role,
            "tenant_id": tenant_id,
            "identity_request": identity_request,
            "lexicon_init_request": lexicon_init_request,
            "message": f"User '{username}' onboarding prepared. Dispatch to Identity and Lexicon agents.",
        },
        steps_executed=steps,
    )
''',

    # =========================================================================
    # TESTS
    # =========================================================================

    "tests/test_forge/__init__.py": '''
# tests/test_forge/__init__.py
''',

    "tests/test_forge/test_tools.py": '''
# tests/test_forge/test_tools.py
# Unit tests for OOBE tools
"""
Tests for all OOBE tools in aegis.forge.tools.
"""

import asyncio
import json
import os
import tempfile
import pytest

from aegis.forge.tools.base import ToolManifest, ToolResult


# ─── file_read ───────────────────────────────────────────────────────────────

class TestFileRead:
    """Tests for the file_read tool."""

    @pytest.fixture
    def temp_file(self):
        """Create a temporary file with known content."""
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False)
        f.write("Hello Aegis")
        f.close()
        yield f.name
        if os.path.exists(f.name):
            os.remove(f.name)

    @pytest.mark.asyncio
    async def test_read_existing_file(self, temp_file):
        from aegis.forge.tools import file_read
        result = await file_read.execute({"path": temp_file})
        assert result.success is True
        assert result.data["content"] == "Hello Aegis"
        assert result.data["path"] == temp_file

    @pytest.mark.asyncio
    async def test_read_nonexistent_file(self):
        from aegis.forge.tools import file_read
        result = await file_read.execute({"path": "/nonexistent/path/file.txt"})
        assert result.success is False
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_read_missing_path_param(self):
        from aegis.forge.tools import file_read
        result = await file_read.execute({})
        assert result.success is False
        assert "required" in result.error.lower()

    def test_manifest_valid(self):
        from aegis.forge.tools import file_read
        assert isinstance(file_read.manifest, ToolManifest)
        assert file_read.manifest.name == "file_read"
        assert "file.read" in file_read.manifest.permissions_required


# ─── file_write ──────────────────────────────────────────────────────────────

class TestFileWrite:
    """Tests for the file_write tool."""

    @pytest.mark.asyncio
    async def test_write_creates_file(self):
        from aegis.forge.tools import file_write
        path = tempfile.mktemp(suffix=".txt")
        try:
            result = await file_write.execute({"path": path, "content": "Test content"})
            assert result.success is True
            assert os.path.exists(path)
            with open(path) as f:
                assert f.read() == "Test content"
        finally:
            if os.path.exists(path):
                os.remove(path)

    @pytest.mark.asyncio
    async def test_write_creates_dirs(self):
        from aegis.forge.tools import file_write
        tmpdir = tempfile.mkdtemp()
        path = os.path.join(tmpdir, "sub", "dir", "file.txt")
        try:
            result = await file_write.execute({"path": path, "content": "nested"})
            assert result.success is True
            assert os.path.exists(path)
        finally:
            import shutil
            shutil.rmtree(tmpdir)

    @pytest.mark.asyncio
    async def test_write_missing_content(self):
        from aegis.forge.tools import file_write
        result = await file_write.execute({"path": "/tmp/test.txt"})
        assert result.success is False


# ─── file_delete ─────────────────────────────────────────────────────────────

class TestFileDelete:
    """Tests for the file_delete tool."""

    @pytest.mark.asyncio
    async def test_delete_existing_file(self):
        from aegis.forge.tools import file_delete
        f = tempfile.NamedTemporaryFile(delete=False)
        f.close()
        result = await file_delete.execute({"path": f.name})
        assert result.success is True
        assert not os.path.exists(f.name)

    @pytest.mark.asyncio
    async def test_delete_nonexistent_file(self):
        from aegis.forge.tools import file_delete
        result = await file_delete.execute({"path": "/nonexistent/file.txt"})
        assert result.success is False


# ─── dir_list ────────────────────────────────────────────────────────────────

class TestDirList:
    """Tests for the dir_list tool."""

    @pytest.mark.asyncio
    async def test_list_directory(self):
        from aegis.forge.tools import dir_list
        tmpdir = tempfile.mkdtemp()
        # Create some files
        open(os.path.join(tmpdir, "a.txt"), "w").close()
        open(os.path.join(tmpdir, "b.txt"), "w").close()
        try:
            result = await dir_list.execute({"path": tmpdir})
            assert result.success is True
            assert result.data["count"] == 2
        finally:
            import shutil
            shutil.rmtree(tmpdir)

    @pytest.mark.asyncio
    async def test_list_nonexistent_dir(self):
        from aegis.forge.tools import dir_list
        result = await dir_list.execute({"path": "/nonexistent/directory"})
        assert result.success is False


# ─── dir_create ──────────────────────────────────────────────────────────────

class TestDirCreate:
    """Tests for the dir_create tool."""

    @pytest.mark.asyncio
    async def test_create_directory(self):
        from aegis.forge.tools import dir_create
        tmpdir = tempfile.mkdtemp()
        path = os.path.join(tmpdir, "new", "nested", "dir")
        try:
            result = await dir_create.execute({"path": path})
            assert result.success is True
            assert os.path.isdir(path)
            assert result.data["created"] is True
        finally:
            import shutil
            shutil.rmtree(tmpdir)

    @pytest.mark.asyncio
    async def test_create_existing_directory(self):
        from aegis.forge.tools import dir_create
        tmpdir = tempfile.mkdtemp()
        result = await dir_create.execute({"path": tmpdir})
        assert result.success is True
        assert result.data["already_existed"] is True
        import shutil
        shutil.rmtree(tmpdir)


# ─── json_parse ──────────────────────────────────────────────────────────────

class TestJsonParse:
    """Tests for the json_parse tool."""

    @pytest.mark.asyncio
    async def test_parse_valid_json(self):
        from aegis.forge.tools import json_parse
        data = json.dumps({"name": "Aegis", "version": 1})
        result = await json_parse.execute({"data": data})
        assert result.success is True
        assert result.data["parsed"]["name"] == "Aegis"

    @pytest.mark.asyncio
    async def test_parse_with_path(self):
        from aegis.forge.tools import json_parse
        data = json.dumps({"results": [{"name": "first"}, {"name": "second"}]})
        result = await json_parse.execute({"data": data, "path": "results.0.name"})
        assert result.success is True
        assert result.data["extracted"] == "first"

    @pytest.mark.asyncio
    async def test_parse_invalid_json(self):
        from aegis.forge.tools import json_parse
        result = await json_parse.execute({"data": "not valid json {"})
        assert result.success is False
        assert "invalid" in result.error.lower()


# ─── execute_shell_command ───────────────────────────────────────────────────

class TestShellCommand:
    """Tests for the execute_shell_command tool."""

    @pytest.mark.asyncio
    async def test_echo_command(self):
        from aegis.forge.tools import execute_shell_command
        result = await execute_shell_command.execute({"command": "echo hello"})
        assert result.success is True
        assert "hello" in result.data["stdout"]

    @pytest.mark.asyncio
    async def test_blocked_command(self):
        from aegis.forge.tools import execute_shell_command
        result = await execute_shell_command.execute({"command": "curl http://evil.com"})
        assert result.success is False
        assert "blocked" in result.error.lower() or "allowlist" in result.error.lower()


# ─── git_command ─────────────────────────────────────────────────────────────

class TestGitCommand:
    """Tests for the git_command tool."""

    @pytest.mark.asyncio
    async def test_git_version(self):
        from aegis.forge.tools import git_command
        result = await git_command.execute({"args": "--version"})
        assert result.success is True
        assert "git version" in result.data["stdout"].lower()

    def test_manifest(self):
        from aegis.forge.tools import git_command
        assert git_command.manifest.name == "git_command"
        assert "git.execute" in git_command.manifest.permissions_required


# ─── schedule_job ────────────────────────────────────────────────────────────

class TestScheduleJob:
    """Tests for the schedule_job tool."""

    @pytest.mark.asyncio
    async def test_create_cron_job(self):
        from aegis.forge.tools import schedule_job
        result = await schedule_job.execute({
            "name": "nightly_backup",
            "schedule_type": "cron",
            "schedule_config": {"hour": 2, "minute": 0},
            "action": "forge.execute_skill",
            "action_payload": {"skill": "memory_optimize"},
        })
        assert result.success is True
        assert result.data["job"]["name"] == "nightly_backup"
        assert result.data["job"]["schedule_type"] == "cron"

    @pytest.mark.asyncio
    async def test_invalid_schedule_type(self):
        from aegis.forge.tools import schedule_job
        result = await schedule_job.execute({
            "name": "bad_job",
            "schedule_type": "invalid",
            "schedule_config": {},
            "action": "test",
        })
        assert result.success is False
''',

    "tests/test_forge/test_registry.py": '''
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
''',

    "tests/test_forge/test_agent.py": '''
# tests/test_forge/test_agent.py
# Unit tests for the Forge Agent
"""
Tests for aegis.forge.agent — ForgeAgent message handling.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from aegis.schemas.message import AegisMessage, MessageType, Priority
from aegis.schemas.forge import ForgeAction, ForgeRequest, ForgeResponse
from aegis.forge.agent import ForgeAgent


@pytest.fixture
def forge_agent():
    """Create a ForgeAgent instance with mocked bus."""
    bus = MagicMock()
    bus.subscribe = AsyncMock()
    bus.unsubscribe = AsyncMock()
    agent = ForgeAgent(bus=bus)
    return agent


@pytest.fixture
def sample_message():
    """Create a sample AegisMessage targeting forge."""
    return AegisMessage(
        message_id=str(uuid4()),
        correlation_id=str(uuid4()),
        source_agent="torchestrator",
        target_agent="forge",
        message_type=MessageType.REQUEST,
        tenant_id="test-tenant",
        user_id="test-user",
        action="forge.execute_tool",
        payload={
            "action": "execute_tool",
            "tool_or_skill_name": "json_parse",
            "parameters": {"data": "{\\"key\\": \\"value\\"}"},
        },
        priority=Priority.NORMAL,
        metadata={"session_id": "test-session"},
    )


class TestForgeAgent:
    """Tests for ForgeAgent."""

    @pytest.mark.asyncio
    async def test_startup(self, forge_agent):
        await forge_agent.startup()
        assert forge_agent._running is True
        # Should have discovered tools and skills
        assert forge_agent.tool_registry.tool_count > 0

    @pytest.mark.asyncio
    async def test_shutdown(self, forge_agent):
        await forge_agent.startup()
        await forge_agent.shutdown()
        assert forge_agent._running is False

    @pytest.mark.asyncio
    async def test_handle_execute_tool(self, forge_agent, sample_message):
        await forge_agent.startup()
        response = await forge_agent.handle_message(sample_message)
        assert response is not None
        assert response.message_type == MessageType.RESPONSE
        payload = response.payload
        assert payload["success"] is True
        assert payload["action"] == ForgeAction.EXECUTE_TOOL

    @pytest.mark.asyncio
    async def test_handle_list_tools(self, forge_agent):
        await forge_agent.startup()
        msg = AegisMessage(
            source_agent="torchestrator",
            target_agent="forge",
            message_type=MessageType.REQUEST,
            tenant_id="test-tenant",
            user_id="test-user",
            action="forge.list_tools",
            payload={"action": "list_tools"},
        )
        response = await forge_agent.handle_message(msg)
        assert response is not None
        payload = response.payload
        assert payload["success"] is True
        assert isinstance(payload["result"], list)
        assert len(payload["result"]) > 0

    @pytest.mark.asyncio
    async def test_handle_nonexistent_tool(self, forge_agent):
        await forge_agent.startup()
        msg = AegisMessage(
            source_agent="torchestrator",
            target_agent="forge",
            message_type=MessageType.REQUEST,
            tenant_id="test-tenant",
            user_id="test-user",
            action="forge.execute_tool",
            payload={
                "action": "execute_tool",
                "tool_or_skill_name": "nonexistent_tool",
                "parameters": {},
            },
        )
        response = await forge_agent.handle_message(msg)
        payload = response.payload
        assert payload["success"] is False
        assert "not found" in payload["error"].lower()

    @pytest.mark.asyncio
    async def test_handle_invalid_payload(self, forge_agent):
        await forge_agent.startup()
        msg = AegisMessage(
            source_agent="torchestrator",
            target_agent="forge",
            message_type=MessageType.REQUEST,
            tenant_id="test-tenant",
            user_id="test-user",
            action="forge.execute_tool",
            payload={"invalid": "data"},
        )
        response = await forge_agent.handle_message(msg)
        payload = response.payload
        assert payload["success"] is False

    @pytest.mark.asyncio
    async def test_handle_list_skills(self, forge_agent):
        await forge_agent.startup()
        msg = AegisMessage(
            source_agent="torchestrator",
            target_agent="forge",
            message_type=MessageType.REQUEST,
            tenant_id="test-tenant",
            user_id="test-user",
            action="forge.list_skills",
            payload={"action": "list_skills"},
        )
        response = await forge_agent.handle_message(msg)
        payload = response.payload
        assert payload["success"] is True
        assert isinstance(payload["result"], list)
''',

    "tests/test_forge/test_context.py": '''
# tests/test_forge/test_context.py
# Unit tests for ForgeContext
"""
Tests for aegis.forge.context — ForgeContext tool/oracle invocation.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock
from types import ModuleType

from aegis.forge.context import ForgeContext
from aegis.forge.registry import ToolRegistry
from aegis.forge.tools.base import ToolManifest, ToolResult


@pytest.fixture
def mock_tool_registry():
    """Create a registry with a mock tool."""
    registry = ToolRegistry()
    mod = ModuleType("aegis.forge.tools.mock")
    mod.manifest = ToolManifest(
        name="mock_tool",
        description="A mock tool",
        version="1.0.0",
    )
    mod.execute = AsyncMock(return_value=ToolResult(success=True, data={"result": "ok"}))
    registry.register(mod)
    return registry


@pytest.fixture
def forge_context(mock_tool_registry):
    """Create a ForgeContext with mocked dependencies."""
    return ForgeContext(
        tenant_id="test-tenant",
        user_id="test-user",
        session_id="test-session",
        tool_registry=mock_tool_registry,
        bus_publisher=None,
        correlation_id="test-correlation",
    )


class TestForgeContext:
    """Tests for ForgeContext."""

    @pytest.mark.asyncio
    async def test_invoke_tool_success(self, forge_context):
        result = await forge_context.invoke_tool("mock_tool", {"key": "value"})
        assert result.success is True
        assert result.data == {"result": "ok"}
        assert "tool:mock_tool" in forge_context.steps_executed

    @pytest.mark.asyncio
    async def test_invoke_tool_not_found(self, forge_context):
        result = await forge_context.invoke_tool("nonexistent", {})
        assert result.success is False
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_invoke_oracle_no_bus(self, forge_context):
        result = await forge_context.invoke_oracle({"action": "query", "prompt": "test"})
        assert result["success"] is False
        assert "not available" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_get_context_no_bus(self, forge_context):
        result = await forge_context.get_context("test query")
        assert "error" in result
        assert "not available" in result["error"].lower()

    def test_steps_tracking(self, forge_context):
        assert forge_context.steps_executed == []

    @pytest.mark.asyncio
    async def test_invoke_tool_no_registry(self):
        ctx = ForgeContext(
            tenant_id="t",
            user_id="u",
            session_id="s",
            tool_registry=None,
        )
        result = await ctx.invoke_tool("any_tool", {})
        assert result.success is False
        assert "not available" in result.error.lower()
''',

}


def create_package_init_files(path):
    """Create __init__.py files in parent directories if they don't exist."""
    dir_name = os.path.dirname(path)
    if dir_name and (dir_name.startswith("") or dir_name.startswith("tests/")):
        parts = dir_name.split("/")
        for i in range(2, len(parts) + 1):
            pkg_path = "/".join(parts[:i])
            init_file = os.path.join(pkg_path, "__init__.py")
            if not os.path.exists(init_file):
                os.makedirs(pkg_path, exist_ok=True)
                print(f"  [Created] {init_file} (empty package marker)")
                with open(init_file, "w") as f:
                    pass


def main():
    """Main function to write all files for CHUNK-009."""
    print("=" * 60)
    print("  Assembling CHUNK-009: The Forge (Execution)")
    print("  Implements: Part VI §6.1, Part VII, Part VIII")
    print("=" * 60)
    print()

    files_written = 0

    for path, content in CHUNK_9_FILES.items():
        # Ensure the directory exists
        dir_name = os.path.dirname(path)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)

        create_package_init_files(path)

        print(f"  [Writing] {path}")
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(textwrap.dedent(content).strip() + "\n")
        files_written += 1

    print()
    print("-" * 60)
    print(f"  Assembly Complete: {files_written} files written")
    print()
    print("  Files created:")
    print("    Schemas:  aegis/schemas/forge.py")
    print("    Core:     aegis/forge/{__init__, agent, registry, context}.py")
    print("    Tools:    aegis/forge/tools/ (11 OOBE tools)")
    print("    Skills:   aegis/forge/skills/ (6 OOBE skills)")
    print("    Tests:    tests/test_forge/ (4 test modules)")
    print()
    print("  New dependencies to add to requirements.txt:")
    print("    aiofiles>=23.0")
    print("    aiohttp>=3.9")
    print("-" * 60)


if __name__ == "__main__":
    main()
