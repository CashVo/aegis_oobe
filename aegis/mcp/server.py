# aegis/mcp/server.py
# Implements: Part IV, §4.5 — MCP Server (Model Context Protocol)
"""
MCP Server for Aegis Lexicon memory.

Exposed tools:
    - memory_search: Search across memory tiers
    - memory_store: Store a new memory entry
    - context_assemble: Assemble a context packet for LLM use
    - tier_query: Query a specific memory tier

Transport: stdio (default) or SSE
Authorization: All requests validated via Warden (tenant_id + user_id + API key)
"""

import asyncio
import json
import logging
import uuid
from typing import Any, Optional

logger = logging.getLogger(__name__)

try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool, TextContent
    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False
    Server = object
    stdio_server = None
    Tool = object
    TextContent = object
    logger.warning("MCP SDK not installed. MCP server will not be available. Install with: pip install mcp")


class AegisMCPServer:
    """
    MCP Server that exposes Lexicon memory capabilities to external clients.

    Usage:
        server = AegisMCPServer(config=cfg)
        await server.run()  # Blocks on stdio transport
    """

    def __init__(self, config: Any = None) -> None:
        self.config = config
        self._bus = None
        self._server: Optional[Any] = None

    async def _get_bus(self):
        """Lazy-initialize bus connection."""
        if self._bus is None:
            from aegis.config import load_config
            from aegis.bus.redis_bus import RedisBus
            cfg = self.config or load_config("aegis_config.yaml")
            self._bus = RedisBus(config=cfg)
            await self._bus.connect()
        return self._bus

    async def _bus_request(self, target_agent: str, action: str, payload: dict) -> dict:
        """Generic helper to send a request on the bus and await a response."""
        from aegis.schemas.message import AegisMessage, MessageType
        bus = await self._get_bus()
        correlation_id = str(uuid.uuid4())
        response_channel = f"aegis:stream:mcp:{target_agent}:{correlation_id}"
        consumer_group = f"mcp-{target_agent}-{correlation_id}"

        try:
            await bus.create_consumer_group(response_channel, consumer_group)
        except Exception:
            pass

        msg = AegisMessage(
            correlation_id=correlation_id,
            source_agent="mcp_server",
            target_agent=target_agent,
            message_type=MessageType.REQUEST,
            action=action,
            payload=payload,
            metadata={"response_channel": response_channel},
        )
        await bus.publish(f"aegis:stream:{target_agent}", msg)

        deadline = asyncio.get_event_loop().time() + 10
        while asyncio.get_event_loop().time() < deadline:
            messages = await bus.consume(response_channel, consumer_group, "mcp", count=1, block_ms=500)
            if messages:
                for _, data in messages:
                    return AegisMessage.model_validate(data).payload
        return {"success": False, "error": "timeout"}

    async def _validate_auth(self, tenant_id: str, user_id: str, api_key: str) -> bool:
        """Validate request through Warden."""
        payload = {"action": "mcp.access", "resource": "lexicon", "api_key": api_key, "tenant_id": tenant_id, "user_id": user_id}
        result = await self._bus_request("warden", "warden.authorize", payload)
        return result.get("verdict") == "allow"

    async def _lexicon_call(self, action: str, payload: dict) -> dict:
        """Send a request to Lexicon via the bus."""
        import uuid
        from aegis.schemas.message import AegisMessage, MessageType

        bus = await self._get_bus()
        correlation_id = str(uuid.uuid4())
        response_channel = f"aegis:stream:mcp:lexicon:{correlation_id}"
        consumer_group = f"mcp-lex-{correlation_id}"
        try:
            await bus.create_consumer_group(response_channel, consumer_group)
        except Exception:
            pass

        msg = AegisMessage(
            correlation_id=correlation_id,
            source_agent="mcp_server",
            target_agent="lexicon",
            message_type=MessageType.REQUEST,
            tenant_id=payload.get("tenant_id", "default"),
            user_id=payload.get("user_id", "root"),
            action=f"lexicon.{action}",
            payload=payload,
            metadata={"response_channel": response_channel},
        )
        await bus.publish("aegis:stream:lexicon", msg)

        deadline = asyncio.get_event_loop().time() + 15
        result = {"success": False, "error": "timeout"}
        while asyncio.get_event_loop().time() < deadline:
            messages = await bus.consume(
                response_channel, consumer_group, "mcp",
                count=1, block_ms=500,
            )
            if messages:
                for _, data in messages:
                    parsed = AegisMessage.model_validate(data)
                    result = parsed.payload
                break
        return result

    def _build_server(self) -> Any:
        """Construct the MCP Server with registered tools."""
        if not MCP_AVAILABLE:
            raise RuntimeError("MCP SDK not installed.")

        server = Server("aegis-memory")

        @server.list_tools()
        async def list_tools():
            return [
                Tool(
                    name="memory_search",
                    description="Search across Aegis Lexicon memory tiers. Returns relevant memory fragments.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Search query"},
                            "tenant_id": {"type": "string", "description": "Tenant ID"},
                            "user_id": {"type": "string", "description": "User ID"},
                            "api_key": {"type": "string", "description": "API key for authentication"},
                            "tiers": {"type": "array", "items": {"type": "string"}, "description": "Memory tiers to search (e.g. ['L1','L2','L3'])"},
                            "limit": {"type": "integer", "description": "Max results", "default": 20},
                        },
                        "required": ["query", "tenant_id", "user_id", "api_key"],
                    },
                ),
                Tool(
                    name="memory_store",
                    description="Store a new entry in Aegis Lexicon memory.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "tier": {"type": "string", "description": "Target tier (L1, L2, L3)"},
                            "content": {"type": "string", "description": "Memory content to store"},
                            "tenant_id": {"type": "string"},
                            "user_id": {"type": "string"},
                            "api_key": {"type": "string"},
                            "metadata": {"type": "object", "description": "Optional metadata"},
                        },
                        "required": ["tier", "content", "tenant_id", "user_id", "api_key"],
                    },
                ),
                Tool(
                    name="context_assemble",
                    description="Assemble a context packet from Lexicon memory for LLM use.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Context query"},
                            "tenant_id": {"type": "string"},
                            "user_id": {"type": "string"},
                            "api_key": {"type": "string"},
                            "scope": {"type": "array", "items": {"type": "string"}, "description": "Tiers to include"},
                            "token_budget": {"type": "integer", "default": 4000},
                        },
                        "required": ["query", "tenant_id", "user_id", "api_key"],
                    },
                ),
                Tool(
                    name="tier_query",
                    description="Query a specific Lexicon memory tier directly.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "tier": {"type": "string", "description": "Tier to query (L0-L5)"},
                            "tenant_id": {"type": "string"},
                            "user_id": {"type": "string"},
                            "api_key": {"type": "string"},
                            "filter": {"type": "object", "description": "Optional filter criteria"},
                        },
                        "required": ["tier", "tenant_id", "user_id", "api_key"],
                    },
                ),
            ]

        @server.call_tool()
        async def call_tool(name: str, arguments: dict) -> list:
            # Extract auth fields
            tenant_id = arguments.get("tenant_id", "")
            user_id = arguments.get("user_id", "")
            api_key = arguments.get("api_key", "")

            # Validate auth
            authorized = await self._validate_auth(tenant_id, user_id, api_key)
            if not authorized:
                return [TextContent(type="text", text=json.dumps({"error": "Unauthorized"}))]

            # Route to appropriate Lexicon action
            tool_to_action = {
                "memory_search": "search_memory",
                "memory_store": "store_memory",
                "context_assemble": "assemble_context",
                "tier_query": "query_tier",
            }
            action = tool_to_action.get(name)
            if not action:
                return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]

            # Remove auth fields from payload sent to Lexicon
            payload = {k: v for k, v in arguments.items() if k != "api_key"}
            result = await self._lexicon_call(action, payload)
            return [TextContent(type="text", text=json.dumps(result, default=str))]

        self._server = server
        return server

    async def run(self) -> None:
        """Run the MCP server on stdio transport (blocking)."""
        if not MCP_AVAILABLE:
            logger.error("Cannot start MCP server: mcp SDK not installed.")
            return

        server = self._build_server()
        logger.info("Aegis MCP Server starting on stdio transport…")
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())

    async def shutdown(self) -> None:
        """Clean up resources."""
        if self._bus:
            try:
                await self._bus.disconnect()
            except Exception:
                pass


def main() -> None:
    """CLI entry point for running the MCP server standalone."""
    import sys
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    server = AegisMCPServer()
    asyncio.run(server.run())


if __name__ == "__main__":
    main()
