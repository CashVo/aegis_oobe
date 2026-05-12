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
