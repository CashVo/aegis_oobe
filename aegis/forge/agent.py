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
