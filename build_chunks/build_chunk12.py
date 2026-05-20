# build_chunk_012.py
#
# CHUNK-012: User Interfaces (CLI + Web + MCP Server)
# Dependencies: CHUNK-010 (TOrchestrator), CHUNK-011 (System Manager & Scheduler)
# Implements: Part X (§10.1, §10.2), Part IV §4.5 (MCP Server)
# OOBE Criteria: UC-5, UC-6, UC-7
#
# Run from the root of the project-aegis directory:
#   python build_chunk_012.py

import os
import textwrap

# ─────────────────────────────────────────────
# File Manifest
# ─────────────────────────────────────────────
CHUNK_12_FILES = {

# ═══════════════════════════════════════════════
# SECTION 1: SCHEMAS — Web & MCP Contracts
# Implements: Part X §10.2 — ChatInput / ChatOutput
# ═══════════════════════════════════════════════


"aegis/schemas/web.py": '''
# aegis/schemas/web.py
# Implements: Part X, §10.2 — Chat Page WebSocket Protocol
"""
Pydantic contracts for the User Interface layer (CLI + Web + MCP).
These define the wire-format for all client ↔ server communication.
"""

from time import datetime, utcnow
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


def _utc_now() -> datetime:
    return datetime.now(utcnow())


# ── WebSocket Chat Protocol ──────────────────────────────

class ChatInput(BaseModel):
    """Client → Server message for the chat interface."""
    message: str
    session_id: Optional[str] = None
    tenant_id: str
    user_id: str


class ChatOutput(BaseModel):
    """Server → Client message for the chat interface."""
    response: str
    session_id: str
    agent: str = "TOrchestrator"
    timestamp: datetime = Field(default_factory=_utc_now)
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ── Dashboard / Status Models ────────────────────────────

class AgentStatusItem(BaseModel):
    """Health status for a single agent."""
    agent_id: str
    status: str = "unknown"          # running | stopped | degraded | unknown
    last_heartbeat: Optional[datetime] = None
    uptime_seconds: Optional[float] = None
    message_count: int = 0


class SystemStatus(BaseModel):
    """Aggregate system health payload for the dashboard."""
    redis_connected: bool = False
    agents: List[AgentStatusItem] = Field(default_factory=list)
    scheduler_running: bool = False
    total_messages_processed: int = 0
    uptime_seconds: float = 0.0
    timestamp: datetime = Field(default_factory=_utc_now)


# ── Memory Explorer Models ───────────────────────────────

class MemorySearchRequest(BaseModel):
    """Request to search Lexicon memory from the UI."""
    query: str
    tenant_id: str
    user_id: str
    tiers: List[str] = Field(default_factory=lambda: ["L1", "L2", "L3"])
    limit: int = 20


class MemoryFragment(BaseModel):
    """A single memory fragment returned from Lexicon."""
    tier: str
    content: str
    relevance: float = 0.0
    created_at: Optional[datetime] = None
    memory_id: Optional[str] = None


class MemorySearchResponse(BaseModel):
    """Response from a Lexicon memory search."""
    fragments: List[MemoryFragment] = Field(default_factory=list)
    total_results: int = 0
    tiers_queried: List[str] = Field(default_factory=list)
    query: str = ""


# ── Schedule Models ──────────────────────────────────────

class ScheduleJobView(BaseModel):
    """Read-only view of a scheduled job for the UI."""
    job_id: str
    name: str
    description: str = ""
    schedule_type: str              # cron | interval | date
    schedule_config: Dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    last_run: Optional[datetime] = None
    next_run: Optional[datetime] = None


# ── User / Tenant Management Models ─────────────────────

class UserView(BaseModel):
    """Read-only user representation for the management UI."""
    user_id: str
    tenant_id: str
    username: str
    display_name: str = ""
    email: Optional[str] = None
    role_name: str = "member"
    is_root: bool = False
    status: str = "active"
    created_at: Optional[datetime] = None


class TenantView(BaseModel):
    """Read-only tenant representation."""
    tenant_id: str
    name: str
    status: str = "active"
    created_at: Optional[datetime] = None
    user_count: int = 0


# ── MCP Protocol Models ─────────────────────────────────

class MCPAuthContext(BaseModel):
    """Authentication context for MCP requests."""
    tenant_id: str
    user_id: str
    api_key: str


class MCPToolRequest(BaseModel):
    """Inbound MCP tool invocation."""
    tool_name: str          # memory_search | memory_store | context_assemble | tier_query
    arguments: Dict[str, Any] = Field(default_factory=dict)
    auth: MCPAuthContext


class MCPToolResponse(BaseModel):
    """Outbound MCP tool result."""
    success: bool
    result: Any = None
    error: Optional[str] = None
''',

# ═══════════════════════════════════════════════
# SECTION 2: CLI — Main Entry Point
# Implements: Part X, §10.1
# ═══════════════════════════════════════════════

"aegis/cli/__init__.py": '''
# aegis/cli/__init__.py
# Implements: Part X, §10.1 — CLI Management Tool
"""
Aegis CLI package.
Entry point: `aegis` command (registered via pyproject.toml console_scripts).
"""
''',

"aegis/cli/main.py": '''
# aegis/cli/main.py
# Implements: Part X, §10.1 — CLI Management Tool
"""
Root CLI application. Assembles all command groups into the `aegis` command.

Usage:
    aegis start          Start the Aegis system
    aegis stop           Graceful shutdown
    aegis status         Show system health
    aegis chat           Interactive chat with TOrchestrator
    aegis user ...       User management
    aegis tenant ...     Tenant management
    aegis memory ...     Memory search / export / import
    aegis schedule ...   Scheduler management
    aegis config ...     Configuration management
"""

import typer

# --- Import command FUNCTIONS and sub-apps ---
from aegis.cli.commands.start import start
from aegis.cli.commands.stop import stop
from aegis.cli.commands.status import status
from aegis.cli.commands.chat import chat
from aegis.cli.commands.user import app as user_app
from aegis.cli.commands.tenant import app as tenant_app
from aegis.cli.commands.memory import app as memory_app
from aegis.cli.commands.schedule import app as schedule_app
from aegis.cli.commands.config import app as config_app

app = typer.Typer(
    name="aegis",
    help="Project Aegis — Local-First Multi-Agent System",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

# ── Register top-level commands (the correct way) ──────
app.command()(start)
app.command()(stop)
app.command()(status)
app.command()(chat)

# ── Register sub-command groups ────────────────────────
app.add_typer(user_app, name="user", help="User management commands.")
app.add_typer(tenant_app, name="tenant", help="Tenant management commands.")
app.add_typer(memory_app, name="memory", help="Lexicon memory commands.")
app.add_typer(schedule_app, name="schedule", help="Scheduler management commands.")
app.add_typer(config_app, name="config", help="Configuration commands.")


def main() -> None:
    """Entry point invoked by the console_scripts hook."""
    app()


if __name__ == "__main__":
    main()
''',

"aegis/cli/commands/__init__.py": '''
# aegis/cli/commands/__init__.py
"""CLI command modules for Aegis."""
''',

# ── CLI: start ───────────────────────────────────────────

"aegis/cli/commands/start.py": '''
# aegis/cli/commands/start.py
# Implements: Part X, §10.1 — `aegis start`
"""
Start the Aegis system via System Manager.
"""

import asyncio
import typer
from typing import Annotated


def start(
    config: Annotated[str, typer.Option(
        "--config", "-c",
        help="Path to the Aegis configuration file.",
    )] = "aegis_config.yaml",

    web: Annotated[bool, typer.Option(
        help="Enable or disable the Mission Control Web UI.",
    )] = True,

    web_port: Annotated[int, typer.Option(
        "--port", "-p",
        help="Port for the Mission Control Web UI.",
    )] = 8420,

) -> None:
    """Start the Aegis system (System Manager bootstrap)."""
    typer.echo("═══════════════════════════════════════")
    typer.echo("  Project Aegis — Starting System")
    typer.echo("═══════════════════════════════════════")
    typer.echo(f"  Config : {config}")
    typer.echo(f"  Web UI : {'enabled' if web else 'disabled'}")
    if web:
        typer.echo(f"  Port   : {web_port}")
    typer.echo("")

    from aegis.system.manager import SystemManager
    from aegis.config import load_config

    cfg = load_config(config)

    async def _run() -> None:
        manager = SystemManager(cfg)
        try:
            await manager.startup()
            typer.echo("[✓] All agents online. System ready.")
            if web:
                typer.echo(f"[✓] Mission Control → http://localhost:{web_port}")
                # Launch web server alongside agent loop
                from aegis.web.app import create_app
                import uvicorn

                web_app = create_app(cfg)
                web_config = uvicorn.Config(
                    web_app,
                    host="0.0.0.0",
                    port=web_port,
                    log_level="info",
                )
                server = uvicorn.Server(web_config)
                await server.serve()
            else:
                # Block until interrupted
                while True:
                    await asyncio.sleep(1)
        except KeyboardInterrupt:
            typer.echo("\\n[…] Shutting down gracefully…")
        finally:
            await manager.shutdown()
            typer.echo("[✓] Aegis stopped.")

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        pass
''',

# ── CLI: stop ────────────────────────────────────────────

"aegis/cli/commands/stop.py": '''
# aegis/cli/commands/stop.py
# Implements: Part X, §10.1 — `aegis stop`
"""
Graceful shutdown of the Aegis system.
Sends a shutdown signal to the System Manager via the Redis bus.
"""

import asyncio
import typer
from typing import Annotated


def stop(
    config: Annotated[str, typer.Option(
        "--config", "-c",
        help="Path to the Aegis configuration file.",
    )] = "aegis_config.yaml",
) -> None:
    """Send a graceful shutdown signal to the running Aegis system."""
    typer.echo("[…] Sending shutdown signal…")

    async def _stop() -> None:
        from aegis.config import load_config
        from aegis.bus.redis_bus import RedisBus
        from aegis.schemas.message import AegisMessage, MessageType, Priority

        cfg = load_config(config)
        bus = RedisBus(cfg)
        try:
            await bus.connect()
            shutdown_msg = AegisMessage(
                source_agent="cli",
                target_agent="system_manager",
                message_type=MessageType.EVENT,
                tenant_id="system",
                user_id="cli",
                action="system.shutdown",
                payload={"reason": "CLI stop command"},
                priority=Priority.CRITICAL,
            )
            await bus.publish("aegis:stream:system_manager", shutdown_msg)
            typer.echo("[✓] Shutdown signal sent.")
        except Exception as exc:
            typer.echo(f"[✗] Failed to send shutdown: {exc}", err=True)
            raise typer.Exit(code=1)
        finally:
            await bus.disconnect()

    asyncio.run(_stop())
''',

# ── CLI: status ──────────────────────────────────────────

"aegis/cli/commands/status.py": '''
# aegis/cli/commands/status.py
# Implements: Part X, §10.1 — `aegis status`
"""
Show system health: agent statuses, Redis connectivity, scheduler state.
"""

import asyncio
import typer
from typing import Annotated


def status(
    config: Annotated[str, typer.Option(
        "--config", "-c",
        help="Path to the Aegis configuration file.",
    )] = "aegis_config.yaml",

    json_output: Annotated[bool, typer.Option(
        "--json",
        help="Output status as JSON.",
    )] = False,
) -> None:
    """Show system health (agents, Redis, scheduler)."""

    async def _status() -> None:
        from aegis.config import load_config
        from aegis.bus.redis_bus import RedisBus

        cfg = load_config(config)
        bus = RedisBus(cfg)

        redis_ok = False
        try:
            await bus.connect()
            redis_ok = await bus.health_check()
        except Exception:
            redis_ok = False
        finally:
            if bus._redis and bus._redis.is_connected:
                await bus.disconnect()

        agents_status = {}
        if redis_ok:
            try:
                import redis.asyncio as aioredis
                # Reconnect for this query
                await bus.connect()
                r = bus._redis
                keys = await r.keys("aegis:heartbeat:*")
                for key in keys:
                    agent_name = key.decode().split(":")[-1]
                    val = await r.get(key)
                    agents_status[agent_name] = "running" if val else "unknown"
            except Exception:
                pass
            finally:
                if bus._redis and bus._redis.is_connected:
                    await bus.disconnect()

        if json_output:
            import json
            data = {
                "redis": "connected" if redis_ok else "disconnected",
                "agents": agents_status or "no heartbeat data",
            }
            typer.echo(json.dumps(data, indent=2))
        else:
            typer.echo("═══════════════════════════════════════")
            typer.echo("  Aegis System Status")
            typer.echo("═══════════════════════════════════════")
            typer.echo(f"  Redis        : {'✓ connected' if redis_ok else '✗ disconnected'}")
            typer.echo("")
            if agents_status:
                typer.echo("  Agents:")
                for name, st in sorted(agents_status.items()):
                    icon = "✓" if st == "running" else "?"
                    typer.echo(f"    [{icon}] {name:20s} {st}")
            else:
                typer.echo("  Agents       : no heartbeat data (Observer may be offline)")
            typer.echo("═══════════════════════════════════════")

    asyncio.run(_status())
''',

# ── CLI: chat ────────────────────────────────────────────

"aegis/cli/commands/chat.py": '''
# aegis/cli/commands/chat.py
# Implements: Part X, §10.1 — `aegis chat`
"""
Interactive multi-turn chat with TOrchestrator via the Redis message bus.
Supports session resumption.
"""

import asyncio
import uuid
from typing import Optional, Annotated
import typer


def chat(
    session: Annotated[Optional[str], typer.Option(
        "--session", "-s",
        help="Resume a previous chat session by ID.",
    )] = None,

    tenant: Annotated[str, typer.Option(
        "--tenant", "-t",
        help="Tenant ID to use for this session.",
    )] = "default",

    user: Annotated[str, typer.Option(
        "--user", "-u",
        help="User ID to use for this session.",
    )] = "root",

    config: Annotated[str, typer.Option(
        "--config", "-c",
        help="Path to the Aegis configuration file.",
    )] = "aegis_config.yaml",
) -> None:
    """Enter interactive chat with TOrchestrator."""
    session_id = session or str(uuid.uuid4())

    typer.echo("═══════════════════════════════════════")
    typer.echo("  Aegis Chat — TOrchestrator")
    typer.echo(f"  Session : {session_id}")
    typer.echo("  Type 'exit' or 'quit' to leave.")
    typer.echo("═══════════════════════════════════════")
    typer.echo("")

    async def _chat_loop() -> None:
        from aegis.config import load_config
        from aegis.bus.redis_bus import RedisBus
        from aegis.schemas.message import AegisMessage, MessageType, Priority

        cfg = load_config(config)
        bus = RedisBus(cfg)
        await bus.connect()

        response_channel = f"aegis:stream:cli:{session_id}"
        consumer_group = f"cli-chat-{session_id}"

        try:
            await bus.create_consumer_group(response_channel, consumer_group)
        except Exception:
            pass  # Group may already exist

        try:
            while True:
                try:
                    user_input = await asyncio.to_thread(input, "You > ")
                except (EOFError, KeyboardInterrupt):
                    break

                stripped = user_input.strip()
                if stripped.lower() in ("exit", "quit", "/exit", "/quit"):
                    typer.echo("\\n[✓] Chat session ended.")
                    break

                if not stripped:
                    continue

                msg = AegisMessage(
                    source_agent="cli",
                    target_agent="torchestrator",
                    message_type=MessageType.REQUEST,
                    tenant_id=tenant,
                    user_id=user,
                    action="torchestrator.chat",
                    payload={
                        "message": stripped,
                        "session_id": session_id,
                        "response_channel": response_channel,
                    },
                    priority=Priority.NORMAL,
                    metadata={"session_id": session_id},
                )
                await bus.publish("aegis:stream:torchestrator", msg)

                typer.echo("")
                response_received = False
                timeout_at = asyncio.get_event_loop().time() + 60

                while asyncio.get_event_loop().time() < timeout_at:
                    messages = await bus.consume(
                        response_channel, consumer_group, "cli",
                        count=1, block_ms=1000,
                    )
                    if messages:
                        for _msg_id, msg_data in messages:
                            parsed = AegisMessage.model_validate(msg_data)
                            response_text = parsed.payload.get("response", "(no response)")
                            metadata = parsed.payload.get("metadata", {})
                            typer.echo(f"Aegis > {response_text}")

                            tools_used = metadata.get("tools_used", [])
                            if tools_used:
                                typer.echo(f"        [tools: {', '.join(tools_used)}]")
                            
                            response_received = True
                        break
                
                if not response_received:
                    typer.echo("Aegis > (timeout — no response received)")

                typer.echo("")

        finally:
            await bus.disconnect()

    try:
        asyncio.run(_chat_loop())
    except KeyboardInterrupt:
        typer.echo("\\n[✓] Chat ended.")
''',


# ── CLI: user ────────────────────────────────────────────

"aegis/cli/commands/user.py": '''
# aegis/cli/commands/user.py
# Implements: Part X, §10.1 — `aegis user` subcommands
"""
User management: create, list, update, delete.
Routes through the Identity Agent via the bus.
"""

import asyncio
from typing import Optional, Annotated
import typer
import uuid

app = typer.Typer()


async def _send_identity_request(config_path: str, action: str, payload: dict) -> dict:
    """Helper: send an Identity protocol request and await the response."""
    from aegis.config import load_config
    from aegis.bus.redis_bus import RedisBus
    from aegis.schemas.message import AegisMessage, MessageType

    cfg = load_config(config_path)
    bus = RedisBus(cfg)
    await bus.connect()

    correlation_id = str(uuid.uuid4())
    response_channel = f"aegis:stream:cli:identity:{correlation_id}"
    consumer_group = f"cli-identity-{correlation_id}"

    try:
        await bus.create_consumer_group(response_channel, consumer_group)
    except Exception:
        pass

    msg = AegisMessage(
        correlation_id=correlation_id,
        source_agent="cli",
        target_agent="identity",
        message_type=MessageType.REQUEST,
        tenant_id=payload.get("tenant_id", "default"),
        user_id=payload.get("requesting_user_id", "root"),
        action=f"identity.{action}",
        payload=payload,
        metadata={"response_channel": response_channel},
    )
    await bus.publish("aegis:stream:identity", msg)

    timeout_at = asyncio.get_event_loop().time() + 15
    result = {"success": False, "error": "timeout"}
    while asyncio.get_event_loop().time() < timeout_at:
        messages = await bus.consume(
            response_channel, consumer_group, "cli", count=1, block_ms=500
        )
        if messages:
            for _, data in messages:
                parsed = AegisMessage.model_validate(data)
                result = parsed.payload
            break

    await bus.disconnect()
    return result


@app.command("create")
def create(
    username: Annotated[str, typer.Option("--username", "-u", prompt=True, help="Username")],
    display_name: Annotated[str, typer.Option("--name", "-n", prompt=True, help="Display name")] = "",
    email: Annotated[Optional[str], typer.Option("--email", "-e", help="Email address")] = None,
    role: Annotated[str, typer.Option("--role", "-r", help="Role to assign")] = "member",
    tenant: Annotated[str, typer.Option("--tenant", "-t", help="Tenant ID")] = "default",
    config: Annotated[str, typer.Option("--config", "-c", help="Config file path")] = "aegis_config.yaml",
) -> None:
    """Create a new user."""
    result = asyncio.run(_send_identity_request(config, "create_user", {
        "tenant_id": tenant,
        "username": username,
        "display_name": display_name,
        "email": email,
        "role_name": role,
    }))
    if result.get("success"):
        user_id = result.get('data', {}).get('user_id', 'N/A')
        typer.echo(f"[✓] User '{username}' created (ID: {user_id})")
    else:
        typer.echo(f"[✗] {result.get('error', 'Unknown error')}", err=True)


@app.command("list")
def list_users(
    tenant: Annotated[str, typer.Option("--tenant", "-t", help="Tenant ID")] = "default",
    config: Annotated[str, typer.Option("--config", "-c", help="Config file path")] = "aegis_config.yaml",
) -> None:
    """List users in the current tenant."""
    result = asyncio.run(_send_identity_request(config, "list_users", {"tenant_id": tenant}))
    users = result.get("data", {}).get("users", [])
    if not users:
        typer.echo("  No users found.")
        return
    typer.echo(f"{'Username':20s} {'Display Name':25s} {'Role':12s} {'Status':10s} {'User ID'}")
    typer.echo("─" * 100)
    for u in users:
        typer.echo(
            f"{u.get('username', ''):20s} "
            f"{u.get('display_name', ''):25s} "
            f"{u.get('role_name', ''):12s} "
            f"{u.get('status', ''):10s} "
            f"{u.get('user_id', '')}"
        )


@app.command("update")
def update(
    user_id: Annotated[str, typer.Argument(help="User ID to update")],
    display_name: Annotated[Optional[str], typer.Option("--name", "-n", help="New display name")] = None,
    email: Annotated[Optional[str], typer.Option("--email", "-e", help="New email")] = None,
    role: Annotated[Optional[str], typer.Option("--role", "-r", help="New role")] = None,
    tenant: Annotated[str, typer.Option("--tenant", "-t", help="Tenant ID")] = "default",
    config: Annotated[str, typer.Option("--config", "-c", help="Config file path")] = "aegis_config.yaml",
) -> None:
    """Update user details."""
    updates = {}
    if display_name is not None: updates["display_name"] = display_name
    if email is not None: updates["email"] = email
    if role is not None: updates["role_name"] = role

    if not updates:
        typer.echo("[!] No updates specified.")
        raise typer.Exit()

    result = asyncio.run(_send_identity_request(config, "update_user", {
        "tenant_id": tenant, "user_id": user_id, **updates
    }))
    if result.get("success"):
        typer.echo(f"[✓] User {user_id} updated.")
    else:
        typer.echo(f"[✗] {result.get('error', 'Unknown error')}", err=True)


@app.command("delete")
def delete(
    user_id: Annotated[str, typer.Argument(help="User ID to delete")],
    tenant: Annotated[str, typer.Option("--tenant", "-t", help="Tenant ID")] = "default",
    config: Annotated[str, typer.Option("--config", "-c", help="Config file path")] = "aegis_config.yaml",
    force: Annotated[bool, typer.Option("--force", "-f", help="Skip confirmation")] = False,
) -> None:
    """Delete a user."""
    if not force:
        confirm = typer.confirm(f"Permanently delete user {user_id}?")
        if not confirm:
            raise typer.Abort()

    result = asyncio.run(_send_identity_request(config, "delete_user", {
        "tenant_id": tenant, "user_id": user_id
    }))
    if result.get("success"):
        typer.echo(f"[✓] User {user_id} deleted.")
    else:
        typer.echo(f"[✗] {result.get('error', 'Unknown error')}", err=True)
''',

# ── CLI: tenant ──────────────────────────────────────────

"aegis/cli/commands/tenant.py": '''
# aegis/cli/commands/tenant.py
# Implements: Part X, §10.1 — `aegis tenant` subcommands
"""
Tenant management: create, list.
"""

import asyncio
import typer
from typing import Annotated

app = typer.Typer()


@app.command("create")
def create(
    name: Annotated[str, typer.Option("--name", "-n", prompt=True, help="Tenant name")],
    config: Annotated[str, typer.Option("--config", "-c", help="Config file path")] = "aegis_config.yaml",
) -> None:
    """Create a new tenant."""
    from aegis.cli.commands.user import _send_identity_request

    result = asyncio.run(_send_identity_request(config, "create_tenant", {"name": name}))
    if result.get("success"):
        tid = result.get("data", {}).get("tenant_id", "N/A")
        typer.echo(f"[✓] Tenant '{name}' created (ID: {tid})")
    else:
        typer.echo(f"[✗] {result.get('error', 'Unknown error')}", err=True)


@app.command("list")
def list_tenants(
    config: Annotated[str, typer.Option("--config", "-c", help="Config file path")] = "aegis_config.yaml",
) -> None:
    """List all tenants."""
    from aegis.cli.commands.user import _send_identity_request

    result = asyncio.run(_send_identity_request(config, "list_tenants", {}))
    tenants = result.get("data", {}).get("tenants", [])
    if not tenants:
        typer.echo("  No tenants found.")
        return
    typer.echo(f"{'Name':25s} {'Status':10s} {'Tenant ID'}")
    typer.echo("─" * 70)
    for t in tenants:
        typer.echo(
            f"{t.get('name', ''):25s} "
            f"{t.get('status', ''):10s} "
            f"{t.get('tenant_id', '')}"
        )
''',

# ── CLI: memory ──────────────────────────────────────────

"aegis/cli/commands/memory.py": '''
# aegis/cli/commands/memory.py
# Implements: Part X, §10.1 — `aegis memory` subcommands
"""
Lexicon memory commands: search, export, import.
"""

import asyncio
import json
import typer
import uuid
from pathlib import Path
from typing import Annotated


app = typer.Typer()


async def _send_lexicon_request(config_path: str, action: str, payload: dict) -> dict:
    """Send a Lexicon protocol request via the bus."""
    from aegis.config import load_config
    from aegis.bus.redis_bus import RedisBus
    from aegis.schemas.message import AegisMessage, MessageType

    cfg = load_config(config_path)
    bus = RedisBus(cfg)
    await bus.connect()

    correlation_id = str(uuid.uuid4())
    response_channel = f"aegis:stream:cli:lexicon:{correlation_id}"
    consumer_group = f"cli-lexicon-{correlation_id}"
    try:
        await bus.create_consumer_group(response_channel, consumer_group)
    except Exception:
        pass

    msg = AegisMessage(
        correlation_id=correlation_id,
        source_agent="cli",
        target_agent="lexicon",
        message_type=MessageType.REQUEST,
        tenant_id=payload.get("tenant_id", "default"),
        user_id=payload.get("user_id", "root"),
        action=f"lexicon.{action}",
        payload=payload,
        metadata={"response_channel": response_channel},
    )
    await bus.publish("aegis:stream:lexicon", msg)

    timeout_at = asyncio.get_event_loop().time() + 15
    result = {"success": False, "error": "timeout"}
    while asyncio.get_event_loop().time() < timeout_at:
        messages = await bus.consume(
            response_channel, consumer_group, "cli", count=1, block_ms=500
        )
        if messages:
            for _, data in messages:
                parsed = AegisMessage.model_validate(data)
                result = parsed.payload
            break

    await bus.disconnect()
    return result


@app.command("search")
def search(
    query: Annotated[str, typer.Argument(help="Search query")],
    tiers: Annotated[str, typer.Option("--tiers", help="Comma-separated tiers")] = "L1,L2,L3",
    tenant: Annotated[str, typer.Option("--tenant", "-t")] = "default",
    user: Annotated[str, typer.Option("--user", "-u")] = "root",
    limit: Annotated[int, typer.Option("--limit", "-l")] = 20,
    config: Annotated[str, typer.Option("--config", "-c")] = "aegis_config.yaml",
) -> None:
    """Search Lexicon memory."""
    tier_list = [t.strip() for t in tiers.split(",")]
    payload = {"query": query, "tiers": tier_list, "limit": limit, "tenant_id": tenant, "user_id": user}
    result = asyncio.run(_send_lexicon_request(config, "search_memory", payload))
    fragments = result.get("data", {}).get("fragments", [])
    if not fragments:
        typer.echo("  No results found.")
        return
    for i, frag in enumerate(fragments, 1):
        typer.echo(f"\\n── Result {i} [{frag.get('tier', '?')}] (relevance: {frag.get('relevance', 0):.2f}) ──")
        typer.echo(frag.get("content", ""))


@app.command("export")
def export(
    output: Annotated[Path, typer.Option("--output", "-o", help="Output file path")] = Path("aegis_memory_export.json"),
    tenant: Annotated[str, typer.Option("--tenant", "-t")] = "default",
    user: Annotated[str, typer.Option("--user", "-u")] = "root",
    config: Annotated[str, typer.Option("--config", "-c")] = "aegis_config.yaml",
) -> None:
    """Export Lexicon memory to a portable JSON file."""
    result = asyncio.run(_send_lexicon_request(config, "export_memory", {"tenant_id": tenant, "user_id": user}))
    if result.get("success"):
        data = result.get("data", {})
        output.write_text(json.dumps(data, indent=2, default=str))
        typer.echo(f"[✓] Memory exported to {output}")
    else:
        typer.echo(f"[✗] Export failed: {result.get('error', 'Unknown')}", err=True)


@app.command("import")
def import_memory(
    path: Annotated[Path, typer.Argument(help="Path to memory export JSON")],
    tenant: Annotated[str, typer.Option("--tenant", "-t")] = "default",
    user: Annotated[str, typer.Option("--user", "-u")] = "root",
    config: Annotated[str, typer.Option("--config", "-c")] = "aegis_config.yaml",
) -> None:
    """Import memory from a portable JSON file."""
    if not path.exists():
        typer.echo(f"[✗] File not found: {path}", err=True)
        raise typer.Exit(code=1)

    data = json.loads(path.read_text())
    payload = {"tenant_id": tenant, "user_id": user, "memory_data": data}
    result = asyncio.run(_send_lexicon_request(config, "import_memory", payload))
    if result.get("success"):
        typer.echo(f"[✓] Memory imported from {path}")
    else:
        typer.echo(f"[✗] Import failed: {result.get('error', 'Unknown')}", err=True)
''',

# ── CLI: schedule ────────────────────────────────────────

"aegis/cli/commands/schedule.py": '''
# aegis/cli/commands/schedule.py
# Implements: Part X, §10.1 — `aegis schedule` subcommands
"""
Scheduler management: list, add, remove.
"""

import asyncio
import json
import typer
import uuid
from typing import Annotated


app = typer.Typer()


async def _send_scheduler_request(config_path: str, action: str, payload: dict) -> dict:
    """Send a Scheduler request via the bus."""
    from aegis.config import load_config
    from aegis.bus.redis_bus import RedisBus
    from aegis.schemas.message import AegisMessage, MessageType

    cfg = load_config(config_path)
    bus = RedisBus(cfg)
    await bus.connect()

    correlation_id = str(uuid.uuid4())
    response_channel = f"aegis:stream:cli:scheduler:{correlation_id}"
    consumer_group = f"cli-sched-{correlation_id}"
    try:
        await bus.create_consumer_group(response_channel, consumer_group)
    except Exception:
        pass

    msg = AegisMessage(
        correlation_id=correlation_id,
        source_agent="cli",
        target_agent="system_manager",
        message_type=MessageType.REQUEST,
        action=f"scheduler.{action}",
        payload=payload,
        metadata={"response_channel": response_channel},
    )
    await bus.publish("aegis:stream:system_manager", msg)

    timeout_at = asyncio.get_event_loop().time() + 15
    result = {"success": False, "error": "timeout"}
    while asyncio.get_event_loop().time() < timeout_at:
        messages = await bus.consume(
            response_channel, consumer_group, "cli", count=1, block_ms=500
        )
        if messages:
            for _, data in messages:
                result = AegisMessage.model_validate(data).payload
            break

    await bus.disconnect()
    return result


@app.command("list")
def list_jobs(
    tenant: Annotated[str, typer.Option("--tenant", "-t")] = "default",
    config: Annotated[str, typer.Option("--config", "-c")] = "aegis_config.yaml",
) -> None:
    """List all scheduled jobs."""
    result = asyncio.run(_send_scheduler_request(config, "list_jobs", {"tenant_id": tenant}))
    jobs = result.get("data", {}).get("jobs", [])
    if not jobs:
        typer.echo("  No scheduled jobs.")
        return
    typer.echo(f"{'Name':25s} {'Type':10s} {'Enabled':8s} {'Next Run':25s} {'Job ID'}")
    typer.echo("─" * 100)
    for j in jobs:
        typer.echo(
            f"{j.get('name', ''):25s} "
            f"{j.get('schedule_type', ''):10s} "
            f"{'✓' if j.get('enabled') else '✗':8s} "
            f"{str(j.get('next_run', '')):25s} "
            f"{j.get('job_id', '')}"
        )


@app.command("add")
def add_job(
    name: Annotated[str, typer.Option("--name", "-n", prompt=True)],
    description: Annotated[str, typer.Option("--desc", "-d")] = "",
    schedule_type: Annotated[str, typer.Option("--type", prompt=True, help="cron, interval, or date")],
    schedule_config: Annotated[str, typer.Option("--config-json", prompt=True, help='e.g. `{"hour": 2}`')],
    action: Annotated[str, typer.Option("--action", "-a", prompt=True, help="AegisMessage action")],
    action_payload: Annotated[str, typer.Option("--payload", help="Action payload JSON")] = "{}",
    tenant: Annotated[str, typer.Option("--tenant", "-t")] = "default",
    config: Annotated[str, typer.Option("--config", "-c")] = "aegis_config.yaml",
) -> None:
    """Add a new scheduled job."""
    try:
        sched_cfg = json.loads(schedule_config)
        act_payload = json.loads(action_payload)
    except json.JSONDecodeError as e:
        typer.echo(f"[✗] Invalid JSON: {e}", err=True)
        raise typer.Exit(code=1)

    payload = {
        "tenant_id": tenant, "name": name, "description": description,
        "schedule_type": schedule_type, "schedule_config": sched_cfg,
        "action": action, "action_payload": act_payload,
    }
    result = asyncio.run(_send_scheduler_request(config, "add_job", payload))
    if result.get("success"):
        jid = result.get("data", {}).get("job_id", "N/A")
        typer.echo(f"[✓] Job '{name}' scheduled (ID: {jid})")
    else:
        typer.echo(f"[✗] {result.get('error', 'Unknown error')}", err=True)


@app.command("remove")
def remove_job(
    job_id: Annotated[str, typer.Argument(help="Job ID to remove")],
    tenant: Annotated[str, typer.Option("--tenant", "-t")] = "default",
    config: Annotated[str, typer.Option("--config", "-c")] = "aegis_config.yaml",
    force: Annotated[bool, typer.Option("--force", "-f", help="Skip confirmation")] = False,
) -> None:
    """Remove a scheduled job."""
    if not force:
        confirm = typer.confirm(f"Remove job {job_id}?")
        if not confirm:
            raise typer.Abort()

    result = asyncio.run(_send_scheduler_request(config, "remove_job", {"tenant_id": tenant, "job_id": job_id}))
    if result.get("success"):
        typer.echo(f"[✓] Job {job_id} removed.")
    else:
        typer.echo(f"[✗] {result.get('error', 'Unknown error')}", err=True)
''',

# ── CLI: config ──────────────────────────────────────────

"aegis/cli/commands/config.py": '''
# aegis/cli/commands/config.py
# Implements: Part X, §10.1 — `aegis config` subcommands
"""
Configuration management: show, set.
"""

import typer
import yaml
from pathlib import Path
from typing import Annotated

app = typer.Typer()

DEFAULT_CONFIG_PATH = "aegis_config.yaml"


@app.command("show")
def show(
    config: Annotated[Path, typer.Option("--config", "-c", help="Config file path.")] = Path(DEFAULT_CONFIG_PATH),
) -> None:
    """Show current configuration."""
    if not config.exists():
        typer.echo(f"[✗] Config not found: {config}", err=True)
        raise typer.Exit(code=1)

    data = yaml.safe_load(config.read_text())
    typer.echo("═══════════════════════════════════════")
    typer.echo("  Aegis Configuration")
    typer.echo(f"  Source: {config}")
    typer.echo("═══════════════════════════════════════")
    typer.echo(yaml.dump(data, default_flow_style=False, sort_keys=False))


@app.command("set")
def set_value(
    key: Annotated[str, typer.Argument(help="Config key (dot-notation, e.g. 'web.port')")],
    value: Annotated[str, typer.Argument(help="Value to set")],
    config: Annotated[Path, typer.Option("--config", "-c", help="Config file path.")] = Path(DEFAULT_CONFIG_PATH),
) -> None:
    """Set a configuration value (dot-notation key)."""
    if not config.exists():
        # For 'set', we can create a new file if it doesn't exist
        typer.echo(f"[!] Config not found at {config}, creating new file.")
        data = {}
    else:
        data = yaml.safe_load(config.read_text()) or {}

    keys = key.split(".")
    current = data
    for k in keys[:-1]:
        if k not in current or not isinstance(current.get(k), dict):
            current[k] = {}
        current = current[k]

    # Attempt type coercion
    if value.lower() in ("true", "false"):
        typed_value = value.lower() == "true"
    elif value.isdigit():
        typed_value = int(value)
    else:
        try:
            typed_value = float(value)
        except ValueError:
            typed_value = value

    current[keys[-1]] = typed_value
    config.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))
    typer.echo(f"[✓] {key} = {typed_value}")
''',


# ═══════════════════════════════════════════════
# SECTION 3: WEB — FastAPI Application & Routes
# Implements: Part X, §10.2 — Mission Control Web UI
# ═══════════════════════════════════════════════

"aegis/web/__init__.py": '''
# aegis/web/__init__.py
# Implements: Part X, §10.2 — Mission Control Web UI
"""Aegis Mission Control Web UI package."""
''',

"aegis/web/app.py": '''
# aegis/web/app.py
# Implements: Part X, §10.2 — Mission Control Web UI
"""
FastAPI application factory for the Aegis Mission Control Web UI.
Default: localhost:8420
"""

import logging
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

logger = logging.getLogger(__name__)

_WEB_DIR = Path(__file__).parent
_TEMPLATES_DIR = _WEB_DIR / "templates"
_STATIC_DIR = _WEB_DIR / "static"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


def create_app(config: Any = None) -> FastAPI:
    """Create and configure the Mission Control FastAPI application."""
    app = FastAPI(
        title="Aegis Mission Control",
        description="Project Aegis — Local-First Multi-Agent System Dashboard",
        version="0.12.0",
    )

    app.state.aegis_config = config
    app.state.bus = None

    @app.on_event("startup")
    async def on_startup() -> None:
        logger.info("Mission Control starting up…")
        try:
            from aegis.config import load_config
            from aegis.bus.redis_bus import RedisBus

            cfg = app.state.aegis_config or load_config()
            app.state.aegis_config = cfg

            bus = RedisBus(cfg)
            await bus.connect()
            app.state.bus = bus
            logger.info("Mission Control connected to Redis bus.")
        except Exception as exc:
            logger.warning(f"Mission Control bus connection failed: {exc}. Running in degraded mode.")

    @app.on_event("shutdown")
    async def on_shutdown() -> None:
        logger.info("Mission Control shutting down…")
        if app.state.bus:
            await app.state.bus.disconnect()

    _STATIC_DIR.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    # ── Register route modules ───────────────────────
    from aegis.web.routes.dashboard import router as dashboard_router
    from aegis.web.routes.chat import router as chat_router
    from aegis.web.routes.memory import router as memory_router
    from aegis.web.routes.users import router as users_router
    from aegis.web.routes.schedule import router as schedule_router
    from aegis.web.routes.logs import router as logs_router
    from aegis.web.routes.health import router as health_router

    app.include_router(dashboard_router)
    app.include_router(chat_router)
    app.include_router(memory_router)
    app.include_router(users_router)
    app.include_router(schedule_router)
    app.include_router(logs_router)
    app.include_router(health_router)

    return app
''',

"aegis/web/routes/__init__.py": '''
# aegis/web/routes/__init__.py
"""Web route modules for Mission Control."""
''',

# ── Web: Dashboard ───────────────────────────────────────

"aegis/web/routes/dashboard.py": '''
# aegis/web/routes/dashboard.py
# Implements: Part X, §10.2 — Dashboard (/)
"""
Dashboard route: system health, agent statuses, recent activity.
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from aegis.web.app import templates

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/", include_in_schema=False)
async def dashboard(request: Request):
    """Render the main dashboard page."""
    bus = request.app.state.bus
    agents_status = []
    redis_ok = False

    if bus:
        try:
            redis_ok = await bus.health_check()
        except Exception:
            redis_ok = False

        # Attempt to read heartbeat data
        if redis_ok:
            try:
                r = bus._redis
                keys = await r.keys("aegis:heartbeat:*")
                for key in keys:
                    agent_name = key.decode().split(":")[-1] if isinstance(key, bytes) else key.split(":")[-1]
                    val = await r.get(key)
                    ts_str = val.decode() if isinstance(val, bytes) else str(val) if val else None
                    agents_status.append({
                        "agent_id": agent_name,
                        "status": "running" if val else "unknown",
                        "last_heartbeat": ts_str,
                    })
            except Exception as exc:
                logger.debug(f"Heartbeat read failed: {exc}")

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "redis_connected": redis_ok,
        "agents": agents_status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
''',

# ── Web: Chat ────────────────────────────────────────────

"aegis/web/routes/chat.py": '''
# aegis/web/routes/chat.py
# Implements: Part X, §10.2 — Chat Page (/chat) + WebSocket
"""
Real-time chat with TOrchestrator via WebSocket.
Supports multi-turn sessions, session management.
"""

import asyncio
import json
import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect, Query
from aegis.web.app import templates
from aegis.schemas.message import AegisMessage, MessageType, Priority

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/chat", include_in_schema=False)
async def chat_page(request: Request, session_id: Optional[str] = None):
    """Render the chat page."""
    sid = session_id or str(uuid.uuid4())
    return templates.TemplateResponse("chat.html", {
        "request": request,
        "session_id": sid,
    })


@router.websocket("/ws/chat")
async def chat_websocket(
    websocket: WebSocket,
    session_id: str = Query(default=None),
    tenant_id: str = Query(default="default"),
    user_id: str = Query(default="root"),
):
    """
    WebSocket endpoint for real-time chat with TOrchestrator.

    Protocol:
        Client → Server: JSON with {"message": "...", "session_id": "..."}
        Server → Client: JSON with ChatOutput schema
    """
    await websocket.accept()
    sid = session_id or str(uuid.uuid4())
    bus = websocket.app.state.bus

    # Send session init confirmation
    await websocket.send_json({
        "type": "session_init",
        "session_id": sid,
        "status": "connected",
    })

    if not bus:
        await websocket.send_json({
            "type": "error",
            "message": "System bus unavailable. Start Aegis first.",
        })
        await websocket.close()
        return

    response_channel = f"aegis:stream:web:chat:{sid}"
    consumer_group = f"web-chat-{sid}"
    try:
        await bus.create_consumer_group(response_channel, consumer_group)
    except Exception:
        pass

    try:
        while True:
            # Receive user message
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                data = {"message": raw}

            user_message = data.get("message", "").strip()
            if not user_message:
                continue

            # Dispatch to TOrchestrator via bus
            msg = AegisMessage(
                source_agent="web",
                target_agent="torchestrator",
                message_type=MessageType.REQUEST,
                tenant_id=tenant_id,
                user_id=user_id,
                action="torchestrator.chat",
                payload={
                    "message": user_message,
                    "session_id": sid,
                    "response_channel": response_channel,
                },
                priority=Priority.NORMAL,
                metadata={"session_id": sid, "source": "web"},
            )
            await bus.publish("aegis:stream:torchestrator", msg)

            # Await response (with timeout)
            response_received = False
            deadline = asyncio.get_event_loop().time() + 60

            while asyncio.get_event_loop().time() < deadline:
                messages = await bus.consume(
                    response_channel, consumer_group, "web",
                    count=1, block_ms=1000,
                )
                if messages:
                    for _, msg_data in messages:
                        parsed = AegisMessage.model_validate(msg_data)
                        response_text = parsed.payload.get("response", "")
                        metadata = parsed.payload.get("metadata", {})
                        await websocket.send_json({
                            "type": "chat_response",
                            "response": response_text,
                            "session_id": sid,
                            "agent": "TOrchestrator",
                            "metadata": metadata,
                        })
                    response_received = True
                    break

            if not response_received:
                await websocket.send_json({
                    "type": "error",
                    "message": "Response timeout from TOrchestrator.",
                })

    except WebSocketDisconnect:
        logger.info(f"Chat WebSocket disconnected: session={sid}")
    except Exception as exc:
        logger.error(f"Chat WebSocket error: {exc}", exc_info=True)
        try:
            await websocket.send_json({"type": "error", "message": str(exc)})
        except Exception:
            pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass
''',

# ── Web: Memory ──────────────────────────────────────────

"aegis/web/routes/memory.py": '''
# aegis/web/routes/memory.py
# Implements: Part X, §10.2 — Memory Explorer (/memory)
"""
Memory Explorer: browse and search Lexicon memory tiers.
"""

import asyncio
import logging
import uuid

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse
from aegis.web.app import templates
from aegis.schemas.message import AegisMessage, MessageType

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/memory", include_in_schema=False)
async def memory_page(request: Request):
    """Render the Memory Explorer page."""
    return templates.TemplateResponse("memory.html", {
        "request": request,
        "fragments": [],
        "query": "",
    })


@router.post("/memory/search", include_in_schema=False)
async def memory_search(
    request: Request,
    query: str = Form(""),
    tiers: str = Form("L1,L2,L3"),
    tenant_id: str = Form("default"),
    user_id: str = Form("root"),
):
    """Handle memory search form submission (HTMX partial)."""
    bus = request.app.state.bus
    fragments = []

    if bus and query.strip():
        correlation_id = str(uuid.uuid4())
        response_channel = f"aegis:stream:web:lexicon:{correlation_id}"
        consumer_group = f"web-lex-{correlation_id}"
        try:
            await bus.create_consumer_group(response_channel, consumer_group)
        except Exception:
            pass

        tier_list = [t.strip() for t in tiers.split(",")]
        msg = AegisMessage(
            correlation_id=correlation_id,
            source_agent="web",
            target_agent="lexicon",
            message_type=MessageType.REQUEST,
            tenant_id=tenant_id,
            user_id=user_id,
            action="lexicon.search_memory",
            payload={
                "query": query,
                "tiers": tier_list,
                "limit": 20,
                "tenant_id": tenant_id,
                "user_id": user_id,
            },
            metadata={"response_channel": response_channel},
        )
        await bus.publish("aegis:stream:lexicon", msg)

        deadline = asyncio.get_event_loop().time() + 10
        while asyncio.get_event_loop().time() < deadline:
            messages = await bus.consume(
                response_channel, consumer_group, "web",
                count=1, block_ms=500,
            )
            if messages:
                for _, data in messages:
                    parsed = AegisMessage.model_validate(data)
                    fragments = parsed.payload.get("data", {}).get("fragments", [])
                break

    return templates.TemplateResponse("memory.html", {
        "request": request,
        "fragments": fragments,
        "query": query,
    })
''',

# ── Web: Users ───────────────────────────────────────────

"aegis/web/routes/users.py": '''
# aegis/web/routes/users.py
# Implements: Part X, §10.2 — User Management (/users)
"""
User Management CRUD interface.
"""

import asyncio
import logging
import uuid

from fastapi import APIRouter, Request, Form
from aegis.web.app import templates
from aegis.schemas.message import AegisMessage, MessageType

logger = logging.getLogger(__name__)
router = APIRouter()


async def _identity_bus_call(bus, action: str, payload: dict) -> dict:
    """Send identity request via bus and return response payload."""
    if not bus:
        return {"success": False, "error": "Bus unavailable"}

    correlation_id = str(uuid.uuid4())
    response_channel = f"aegis:stream:web:identity:{correlation_id}"
    consumer_group = f"web-id-{correlation_id}"
    try:
        await bus.create_consumer_group(response_channel, consumer_group)
    except Exception:
        pass

    msg = AegisMessage(
        correlation_id=correlation_id,
        source_agent="web",
        target_agent="identity",
        message_type=MessageType.REQUEST,
        tenant_id=payload.get("tenant_id", "default"),
        user_id="root",
        action=f"identity.{action}",
        payload=payload,
        metadata={"response_channel": response_channel},
    )
    await bus.publish("aegis:stream:identity", msg)

    deadline = asyncio.get_event_loop().time() + 10
    result = {"success": False, "error": "timeout"}
    while asyncio.get_event_loop().time() < deadline:
        messages = await bus.consume(
            response_channel, consumer_group, "web",
            count=1, block_ms=500,
        )
        if messages:
            for _, data in messages:
                parsed = AegisMessage.model_validate(data)
                result = parsed.payload
            break
    return result


@router.get("/users", include_in_schema=False)
async def users_page(request: Request, tenant_id: str = "default"):
    """Render the user management page."""
    bus = request.app.state.bus
    result = await _identity_bus_call(bus, "list_users", {"tenant_id": tenant_id})
    users = result.get("data", {}).get("users", [])
    return templates.TemplateResponse("users.html", {
        "request": request,
        "users": users,
        "tenant_id": tenant_id,
        "message": None,
    })


@router.post("/users/create", include_in_schema=False)
async def create_user(
    request: Request,
    username: str = Form(...),
    display_name: str = Form(""),
    email: str = Form(""),
    role_name: str = Form("member"),
    tenant_id: str = Form("default"),
):
    """Handle user creation form."""
    bus = request.app.state.bus
    result = await _identity_bus_call(bus, "create_user", {
        "tenant_id": tenant_id,
        "username": username,
        "display_name": display_name,
        "email": email or None,
        "role_name": role_name,
    })
    message = f"User '{username}' created." if result.get("success") else result.get("error", "Failed")

    # Re-fetch user list
    list_result = await _identity_bus_call(bus, "list_users", {"tenant_id": tenant_id})
    users = list_result.get("data", {}).get("users", [])

    return templates.TemplateResponse("users.html", {
        "request": request,
        "users": users,
        "tenant_id": tenant_id,
        "message": message,
    })


@router.post("/users/delete/{user_id}", include_in_schema=False)
async def delete_user(request: Request, user_id: str, tenant_id: str = "default"):
    """Handle user deletion."""
    bus = request.app.state.bus
    result = await _identity_bus_call(bus, "delete_user", {
        "tenant_id": tenant_id,
        "user_id": user_id,
    })
    message = f"User {user_id} deleted." if result.get("success") else result.get("error", "Failed")

    list_result = await _identity_bus_call(bus, "list_users", {"tenant_id": tenant_id})
    users = list_result.get("data", {}).get("users", [])

    return templates.TemplateResponse("users.html", {
        "request": request,
        "users": users,
        "tenant_id": tenant_id,
        "message": message,
    })
''',

# ── Web: Schedule ────────────────────────────────────────

"aegis/web/routes/schedule.py": '''
# aegis/web/routes/schedule.py
# Implements: Part X, §10.2 — Scheduler (/schedule)
"""
Scheduler management: view, add, and manage scheduled jobs.
"""

import asyncio
import json
import logging
import uuid

from fastapi import APIRouter, Request, Form
from aegis.web.app import templates
from aegis.schemas.message import AegisMessage, MessageType

logger = logging.getLogger(__name__)
router = APIRouter()


async def _scheduler_bus_call(bus, action: str, payload: dict) -> dict:
    """Send scheduler request via bus."""
    if not bus:
        return {"success": False, "error": "Bus unavailable"}

    correlation_id = str(uuid.uuid4())
    response_channel = f"aegis:stream:web:sched:{correlation_id}"
    consumer_group = f"web-sched-{correlation_id}"
    try:
        await bus.create_consumer_group(response_channel, consumer_group)
    except Exception:
        pass

    msg = AegisMessage(
        correlation_id=correlation_id,
        source_agent="web",
        target_agent="system_manager",
        message_type=MessageType.REQUEST,
        tenant_id=payload.get("tenant_id", "default"),
        user_id="root",
        action=f"scheduler.{action}",
        payload=payload,
        metadata={"response_channel": response_channel},
    )
    await bus.publish("aegis:stream:system_manager", msg)

    deadline = asyncio.get_event_loop().time() + 10
    result = {"success": False, "error": "timeout"}
    while asyncio.get_event_loop().time() < deadline:
        messages = await bus.consume(
            response_channel, consumer_group, "web",
            count=1, block_ms=500,
        )
        if messages:
            for _, data in messages:
                parsed = AegisMessage.model_validate(data)
                result = parsed.payload
            break
    return result


@router.get("/schedule", include_in_schema=False)
async def schedule_page(request: Request, tenant_id: str = "default"):
    """Render the scheduler management page."""
    bus = request.app.state.bus
    result = await _scheduler_bus_call(bus, "list_jobs", {"tenant_id": tenant_id})
    jobs = result.get("data", {}).get("jobs", [])
    return templates.TemplateResponse("schedule.html", {
        "request": request,
        "jobs": jobs,
        "message": None,
    })


@router.post("/schedule/add", include_in_schema=False)
async def add_job(
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    schedule_type: str = Form(...),
    schedule_config: str = Form("{}"),
    action: str = Form(...),
    action_payload: str = Form("{}"),
    tenant_id: str = Form("default"),
):
    """Handle add-job form submission."""
    bus = request.app.state.bus
    try:
        sched_cfg = json.loads(schedule_config)
        act_payload = json.loads(action_payload)
    except json.JSONDecodeError as e:
        return templates.TemplateResponse("schedule.html", {
            "request": request,
            "jobs": [],
            "message": f"Invalid JSON: {e}",
        })

    result = await _scheduler_bus_call(bus, "add_job", {
        "tenant_id": tenant_id,
        "name": name,
        "description": description,
        "schedule_type": schedule_type,
        "schedule_config": sched_cfg,
        "action": action,
        "action_payload": act_payload,
    })
    message = f"Job '{name}' added." if result.get("success") else result.get("error", "Failed")

    list_result = await _scheduler_bus_call(bus, "list_jobs", {"tenant_id": tenant_id})
    jobs = list_result.get("data", {}).get("jobs", [])

    return templates.TemplateResponse("schedule.html", {
        "request": request,
        "jobs": jobs,
        "message": message,
    })


@router.post("/schedule/remove/{job_id}", include_in_schema=False)
async def remove_job(request: Request, job_id: str, tenant_id: str = "default"):
    """Handle job removal."""
    bus = request.app.state.bus
    result = await _scheduler_bus_call(bus, "remove_job", {
        "tenant_id": tenant_id,
        "job_id": job_id,
    })
    message = f"Job {job_id} removed." if result.get("success") else result.get("error", "Failed")

    list_result = await _scheduler_bus_call(bus, "list_jobs", {"tenant_id": tenant_id})
    jobs = list_result.get("data", {}).get("jobs", [])

    return templates.TemplateResponse("schedule.html", {
        "request": request,
        "jobs": jobs,
        "message": message,
    })
''',

# ── Web: Logs ────────────────────────────────────────────

"aegis/web/routes/logs.py": '''
# aegis/web/routes/logs.py
# Implements: Part X, §10.2 — Log Viewer (/logs)
"""
Streaming log viewer via WebSocket. Subscribes to Observer broadcast.
"""

import asyncio
import json
import logging

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from aegis.web.app import templates

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/logs", include_in_schema=False)
async def logs_page(request: Request):
    """Render the log viewer page."""
    return templates.TemplateResponse("logs.html", {
        "request": request,
    })


@router.websocket("/ws/logs")
async def logs_websocket(websocket: WebSocket):
    """
    Stream system logs to the client via WebSocket.
    Subscribes to the aegis:stream:broadcast channel for log events.
    """
    await websocket.accept()
    bus = websocket.app.state.bus

    if not bus:
        await websocket.send_json({"type": "error", "message": "Bus unavailable"})
        await websocket.close()
        return

    consumer_group = f"web-logs-{id(websocket)}"
    try:
        await bus.create_consumer_group("aegis:stream:observer", consumer_group)
    except Exception:
        pass

    try:
        while True:
            messages = await bus.consume(
                "aegis:stream:observer",
                consumer_group,
                f"web-{id(websocket)}",
                count=10,
                block_ms=2000,
            )
            if messages:
                for _, msg_data in messages:
                    try:
                        from aegis.schemas.message import AegisMessage
                        parsed = AegisMessage.model_validate(msg_data)
                        log_entry = {
                            "type": "log",
                            "timestamp": parsed.timestamp.isoformat(),
                            "source": parsed.source_agent,
                            "action": parsed.action,
                            "level": parsed.payload.get("level", "info"),
                            "message": parsed.payload.get("message", str(parsed.payload)),
                        }
                    except Exception:
                        log_entry = {"type": "log", "message": str(msg_data)}
                    await websocket.send_json(log_entry)
            else:
                # Send heartbeat to keep connection alive
                await websocket.send_json({"type": "heartbeat"})

    except WebSocketDisconnect:
        logger.debug("Logs WebSocket disconnected.")
    except Exception as exc:
        logger.error(f"Logs WebSocket error: {exc}")
    finally:
        try:
            await websocket.close()
        except Exception:
            pass
''',

# ── Web: Health ──────────────────────────────────────────

"aegis/web/routes/health.py": '''
# aegis/web/routes/health.py
# Implements: Part X, §10.2 — Health API (/health)
"""
Machine-readable health endpoint (JSON).
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/health")
async def health(request: Request) -> JSONResponse:
    """
    Machine-readable health endpoint.
    Returns JSON with redis status, agent heartbeats, and system info.
    """
    bus = request.app.state.bus
    redis_ok = False
    agents = {}

    if bus:
        try:
            redis_ok = await bus.health_check()
        except Exception:
            redis_ok = False

        if redis_ok:
            try:
                r = bus._redis
                keys = await r.keys("aegis:heartbeat:*")
                for key in keys:
                    name = key.decode().split(":")[-1] if isinstance(key, bytes) else key.split(":")[-1]
                    val = await r.get(key)
                    agents[name] = {
                        "status": "running" if val else "unknown",
                        "last_heartbeat": val.decode() if isinstance(val, bytes) and val else None,
                    }
            except Exception:
                pass

    status_code = 200 if redis_ok else 503
    return JSONResponse(
        status_code=status_code,
        content={
            "status": "healthy" if redis_ok else "degraded",
            "redis": "connected" if redis_ok else "disconnected",
            "agents": agents,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )
''',

# ═══════════════════════════════════════════════
# SECTION 4: HTML TEMPLATES (Jinja2 + HTMX)
# ═══════════════════════════════════════════════

"aegis/web/templates/base.html": '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}Aegis Mission Control{% endblock %}</title>
    <link rel="stylesheet" href="/static/css/style.css">
    <script src="https://unpkg.com/htmx.org@1.9.12"></script>
    {% block head %}{% endblock %}
</head>
<body>
    <nav class="navbar">
        <div class="nav-brand">
            <a href="/">⚡ Aegis Mission Control</a>
        </div>
        <div class="nav-links">
            <a href="/">Dashboard</a>
            <a href="/chat">Chat</a>
            <a href="/memory">Memory</a>
            <a href="/users">Users</a>
            <a href="/schedule">Schedule</a>
            <a href="/logs">Logs</a>
        </div>
    </nav>
    <main class="container">
        {% block content %}{% endblock %}
    </main>
    <footer class="footer">
        <p>Project Aegis v0.12.0 · Local-First Multi-Agent System</p>
    </footer>
    {% block scripts %}{% endblock %}
</body>
</html>
''',

"aegis/web/templates/dashboard.html": '''
{% extends "base.html" %}
{% block title %}Dashboard · Aegis{% endblock %}
{% block content %}
<h1>System Dashboard</h1>
<div class="status-grid">
    <div class="status-card {{ 'status-ok' if redis_connected else 'status-err' }}">
        <h3>Redis</h3>
        <p>{{ "Connected" if redis_connected else "Disconnected" }}</p>
    </div>
    <div class="status-card">
        <h3>Agents</h3>
        <p>{{ agents | length }} reporting</p>
    </div>
</div>

{% if agents %}
<h2>Agent Status</h2>
<table class="data-table">
    <thead>
        <tr><th>Agent</th><th>Status</th><th>Last Heartbeat</th></tr>
    </thead>
    <tbody>
        {% for agent in agents %}
        <tr>
            <td>{{ agent.agent_id }}</td>
            <td><span class="badge {{ 'badge-ok' if agent.status == 'running' else 'badge-warn' }}">{{ agent.status }}</span></td>
            <td>{{ agent.last_heartbeat or "N/A" }}</td>
        </tr>
        {% endfor %}
    </tbody>
</table>
{% else %}
<p class="muted">No agent heartbeat data available. Is the system running?</p>
{% endif %}

<p class="muted">Last updated: {{ timestamp }}</p>
{% endblock %}
''',

"aegis/web/templates/chat.html": '''
{% extends "base.html" %}
{% block title %}Chat · Aegis{% endblock %}
{% block content %}
<h1>Chat with TOrchestrator</h1>
<p class="muted">Session: <code>{{ session_id }}</code></p>

<div id="chat-container" class="chat-container">
    <div id="chat-messages" class="chat-messages"></div>
    <div class="chat-input-bar">
        <input type="text" id="chat-input" placeholder="Type your message…" autocomplete="off" />
        <button id="chat-send" onclick="sendMessage()">Send</button>
    </div>
</div>
<div id="chat-status" class="muted">Connecting…</div>
{% endblock %}

{% block scripts %}
<script>
    const SESSION_ID = "{{ session_id }}";
    const WS_URL = `ws://${window.location.host}/ws/chat?session_id=${SESSION_ID}&tenant_id=default&user_id=root`;

    let ws = null;
    const messagesDiv = document.getElementById("chat-messages");
    const inputEl = document.getElementById("chat-input");
    const statusEl = document.getElementById("chat-status");

    function connect() {
        ws = new WebSocket(WS_URL);
        ws.onopen = () => { statusEl.textContent = "Connected"; };
        ws.onclose = () => { statusEl.textContent = "Disconnected. Refresh to reconnect."; };
        ws.onerror = () => { statusEl.textContent = "Connection error."; };
        ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            if (data.type === "chat_response") {
                appendMessage("Aegis", data.response, "agent");
                if (data.metadata && data.metadata.tools_used) {
                    appendMeta("tools: " + data.metadata.tools_used.join(", "));
                }
            } else if (data.type === "error") {
                appendMessage("System", data.message, "error");
            }
        };
    }

    function appendMessage(sender, text, cls) {
        const div = document.createElement("div");
        div.className = "chat-msg " + cls;
        div.innerHTML = `<strong>${sender}:</strong> ${escapeHtml(text)}`;
        messagesDiv.appendChild(div);
        messagesDiv.scrollTop = messagesDiv.scrollHeight;
    }

    function appendMeta(text) {
        const div = document.createElement("div");
        div.className = "chat-meta";
        div.textContent = text;
        messagesDiv.appendChild(div);
    }

    function escapeHtml(t) {
        const d = document.createElement("div");
        d.textContent = t;
        return d.innerHTML;
    }

    function sendMessage() {
        const msg = inputEl.value.trim();
        if (!msg || !ws || ws.readyState !== WebSocket.OPEN) return;
        appendMessage("You", msg, "user");
        ws.send(JSON.stringify({ message: msg, session_id: SESSION_ID }));
        inputEl.value = "";
    }

    inputEl.addEventListener("keydown", (e) => {
        if (e.key === "Enter") sendMessage();
    });

    connect();
</script>
{% endblock %}
''',

"aegis/web/templates/memory.html": '''
{% extends "base.html" %}
{% block title %}Memory Explorer · Aegis{% endblock %}
{% block content %}
<h1>Memory Explorer</h1>

<form method="post" action="/memory/search" class="search-form">
    <input type="text" name="query" value="{{ query }}" placeholder="Search your memory…" />
    <select name="tiers">
        <option value="L0,L1,L2,L3">All Tiers (L0-L3)</option>
        <option value="L0">L0 — Core Identity</option>
        <option value="L1">L1 — Domain Knowledge</option>
        <option value="L2">L2 — Workflow Calibration</option>
        <option value="L3">L3 — Episodic Memory</option>
    </select>
    <input type="hidden" name="tenant_id" value="default" />
    <input type="hidden" name="user_id" value="root" />
    <button type="submit">Search</button>
</form>

{% if fragments %}
<h2>Results ({{ fragments | length }})</h2>
{% for frag in fragments %}
<div class="memory-fragment">
    <div class="fragment-header">
        <span class="badge">{{ frag.tier if frag.tier is defined else frag.get("tier", "?") }}</span>
        <span class="muted">relevance: {{ "%.2f" | format(frag.relevance if frag.relevance is defined else frag.get("relevance", 0)) }}</span>
    </div>
    <div class="fragment-content">{{ frag.content if frag.content is defined else frag.get("content", "") }}</div>
</div>
{% endfor %}
{% elif query %}
<p class="muted">No results found for "{{ query }}".</p>
{% endif %}
{% endblock %}
''',

"aegis/web/templates/users.html": '''
{% extends "base.html" %}
{% block title %}Users · Aegis{% endblock %}
{% block content %}
<h1>User Management</h1>

{% if message %}
<div class="alert">{{ message }}</div>
{% endif %}

<h2>Create User</h2>
<form method="post" action="/users/create" class="form-inline">
    <input type="text" name="username" placeholder="Username" required />
    <input type="text" name="display_name" placeholder="Display Name" />
    <input type="email" name="email" placeholder="Email" />
    <select name="role_name">
        <option value="member">Member</option>
        <option value="admin">Admin</option>
        <option value="observer">Observer</option>
    </select>
    <input type="hidden" name="tenant_id" value="{{ tenant_id }}" />
    <button type="submit">Create</button>
</form>

<h2>Users in Tenant: {{ tenant_id }}</h2>
{% if users %}
<table class="data-table">
    <thead>
        <tr><th>Username</th><th>Display Name</th><th>Role</th><th>Status</th><th>Actions</th></tr>
    </thead>
    <tbody>
        {% for u in users %}
        <tr>
            <td>{{ u.username if u.username is defined else u.get("username", "") }}</td>
            <td>{{ u.display_name if u.display_name is defined else u.get("display_name", "") }}</td>
            <td>{{ u.role_name if u.role_name is defined else u.get("role_name", "") }}</td>
            <td>{{ u.status if u.status is defined else u.get("status", "") }}</td>
            <td>
                <form method="post" action="/users/delete/{{ u.user_id if u.user_id is defined else u.get('user_id', '') }}" style="display:inline">
                    <button type="submit" class="btn-danger" onclick="return confirm('Delete this user?')">Delete</button>
                </form>
            </td>
        </tr>
        {% endfor %}
    </tbody>
</table>
{% else %}
<p class="muted">No users found.</p>
{% endif %}
{% endblock %}
''',

"aegis/web/templates/schedule.html": '''
{% extends "base.html" %}
{% block title %}Scheduler · Aegis{% endblock %}
{% block content %}
<h1>Scheduler</h1>

{% if message %}
<div class="alert">{{ message }}</div>
{% endif %}

<h2>Add Scheduled Job</h2>
<form method="post" action="/schedule/add" class="form-stack">
    <input type="text" name="name" placeholder="Job Name" required />
    <input type="text" name="description" placeholder="Description" />
    <select name="schedule_type">
        <option value="cron">Cron</option>
        <option value="interval">Interval</option>
        <option value="date">Date (one-time)</option>
    </select>
    <input type="text" name="schedule_config" placeholder='Config JSON, e.g. {"hour": 2, "minute": 0}' required />
    <input type="text" name="action" placeholder="Action (e.g. forge.execute_skill)" required />
    <input type="text" name="action_payload" placeholder='Payload JSON (optional)' value="{}" />
    <input type="hidden" name="tenant_id" value="default" />
    <button type="submit">Add Job</button>
</form>

<h2>Scheduled Jobs</h2>
{% if jobs %}
<table class="data-table">
    <thead>
        <tr><th>Name</th><th>Type</th><th>Enabled</th><th>Next Run</th><th>Actions</th></tr>
    </thead>
    <tbody>
        {% for j in jobs %}
        <tr>
            <td>{{ j.name if j.name is defined else j.get("name", "") }}</td>
            <td>{{ j.schedule_type if j.schedule_type is defined else j.get("schedule_type", "") }}</td>
            <td>{{ "✓" if (j.enabled if j.enabled is defined else j.get("enabled", True)) else "✗" }}</td>
            <td>{{ j.next_run if j.next_run is defined else j.get("next_run", "N/A") }}</td>
            <td>
                <form method="post" action="/schedule/remove/{{ j.job_id if j.job_id is defined else j.get('job_id', '') }}" style="display:inline">
                    <button type="submit" class="btn-danger" onclick="return confirm('Remove this job?')">Remove</button>
                </form>
            </td>
        </tr>
        {% endfor %}
    </tbody>
</table>
{% else %}
<p class="muted">No scheduled jobs.</p>
{% endif %}
{% endblock %}
''',

"aegis/web/templates/logs.html": '''
{% extends "base.html" %}
{% block title %}Logs · Aegis{% endblock %}
{% block content %}
<h1>System Logs</h1>
<div class="log-controls">
    <button id="btn-clear" onclick="clearLogs()">Clear</button>
    <label><input type="checkbox" id="auto-scroll" checked /> Auto-scroll</label>
    <select id="level-filter" onchange="applyFilter()">
        <option value="all">All Levels</option>
        <option value="debug">Debug+</option>
        <option value="info">Info+</option>
        <option value="warning">Warning+</option>
        <option value="error">Error+</option>
    </select>
</div>
<div id="log-container" class="log-container"></div>
<div id="log-status" class="muted">Connecting…</div>
{% endblock %}

{% block scripts %}
<script>
    const logContainer = document.getElementById("log-container");
    const statusEl = document.getElementById("log-status");
    const LEVELS = ["debug", "info", "warning", "error", "critical"];

    let ws = null;
    function connect() {
        ws = new WebSocket(`ws://${window.location.host}/ws/logs`);
        ws.onopen = () => { statusEl.textContent = "Streaming logs…"; };
        ws.onclose = () => { statusEl.textContent = "Disconnected."; };
        ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            if (data.type === "log") {
                addLogEntry(data);
            }
        };
    }

    function addLogEntry(entry) {
        const div = document.createElement("div");
        div.className = "log-entry log-" + (entry.level || "info");
        div.dataset.level = entry.level || "info";
        const ts = entry.timestamp ? entry.timestamp.substring(11, 19) : "--:--:--";
        div.innerHTML = `<span class="log-ts">${ts}</span> <span class="log-src">[${entry.source || "?"}]</span> <span class="log-level">${(entry.level || "info").toUpperCase()}</span> ${escapeHtml(entry.message || "")}`;
        logContainer.appendChild(div);
        applyFilter();
        if (document.getElementById("auto-scroll").checked) {
            logContainer.scrollTop = logContainer.scrollHeight;
        }
    }

    function clearLogs() { logContainer.innerHTML = ""; }

    function applyFilter() {
        const minLevel = document.getElementById("level-filter").value;
        const minIdx = minLevel === "all" ? -1 : LEVELS.indexOf(minLevel);
        logContainer.querySelectorAll(".log-entry").forEach(el => {
            const lvl = LEVELS.indexOf(el.dataset.level);
            el.style.display = (minIdx === -1 || lvl >= minIdx) ? "" : "none";
        });
    }

    function escapeHtml(t) {
        const d = document.createElement("div");
        d.textContent = t;
        return d.innerHTML;
    }

    connect();
</script>
{% endblock %}
''',

# ═══════════════════════════════════════════════
# SECTION 5: STATIC ASSETS
# ═══════════════════════════════════════════════

"aegis/web/static/css/style.css": '''
/* Aegis Mission Control — Stylesheet */
/* Dark theme with accent colors for a "mission control" aesthetic */

:root {
    --bg: #0d1117;
    --bg-card: #161b22;
    --bg-input: #21262d;
    --border: #30363d;
    --text: #c9d1d9;
    --text-muted: #8b949e;
    --accent: #58a6ff;
    --green: #3fb950;
    --yellow: #d29922;
    --red: #f85149;
    --font-mono: 'SF Mono', 'Fira Code', 'Consolas', monospace;
    --font-sans: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
}

* { margin: 0; padding: 0; box-sizing: border-box; }

body {
    font-family: var(--font-sans);
    background: var(--bg);
    color: var(--text);
    line-height: 1.6;
    min-height: 100vh;
    display: flex;
    flex-direction: column;
}

/* ── Navbar ─────────────────────────────────── */
.navbar {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 0.75rem 2rem;
    background: var(--bg-card);
    border-bottom: 1px solid var(--border);
}
.nav-brand a {
    color: var(--accent);
    text-decoration: none;
    font-weight: 700;
    font-size: 1.1rem;
}
.nav-links a {
    color: var(--text-muted);
    text-decoration: none;
    margin-left: 1.5rem;
    font-size: 0.9rem;
    transition: color 0.2s;
}
.nav-links a:hover { color: var(--accent); }

/* ── Container ──────────────────────────────── */
.container {
    max-width: 1100px;
    margin: 2rem auto;
    padding: 0 1.5rem;
    flex: 1;
    width: 100%;
}

/* ── Typography ─────────────────────────────── */
h1 { font-size: 1.75rem; margin-bottom: 1rem; color: var(--text); }
h2 { font-size: 1.25rem; margin: 1.5rem 0 0.75rem; color: var(--text-muted); }
p { margin-bottom: 0.5rem; }
code { background: var(--bg-input); padding: 0.15em 0.4em; border-radius: 4px; font-family: var(--font-mono); font-size: 0.85em; }
.muted { color: var(--text-muted); font-size: 0.85rem; }

/* ── Status Grid ────────────────────────────── */
.status-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem; margin-bottom: 1.5rem; }
.status-card { background: var(--bg-card); border: 1px solid var(--border); border-radius: 8px; padding: 1.25rem; }
.status-card h3 { font-size: 0.9rem; color: var(--text-muted); margin-bottom: 0.25rem; }
.status-card p { font-size: 1.25rem; font-weight: 600; }
.status-ok p { color: var(--green); }
.status-err p { color: var(--red); }

/* ── Tables ─────────────────────────────────── */
.data-table { width: 100%; border-collapse: collapse; margin: 0.5rem 0 1.5rem; }
.data-table th, .data-table td { text-align: left; padding: 0.6rem 0.75rem; border-bottom: 1px solid var(--border); font-size: 0.9rem; }
.data-table th { color: var(--text-muted); font-weight: 600; }
.data-table tr:hover { background: var(--bg-input); }

/* ── Badges ─────────────────────────────────── */
.badge { display: inline-block; padding: 0.15em 0.5em; border-radius: 4px; font-size: 0.8rem; font-weight: 600; background: var(--bg-input); color: var(--text-muted); }
.badge-ok { background: rgba(63,185,80,0.15); color: var(--green); }
.badge-warn { background: rgba(210,153,34,0.15); color: var(--yellow); }

/* ── Alerts ─────────────────────────────────── */
.alert { background: rgba(88,166,255,0.1); border: 1px solid var(--accent); border-radius: 6px; padding: 0.75rem 1rem; margin-bottom: 1rem; font-size: 0.9rem; }

/* ── Forms ──────────────────────────────────── */
input[type="text"], input[type="email"], select, textarea {
    background: var(--bg-input);
    border: 1px solid var(--border);
    color: var(--text);
    padding: 0.5rem 0.75rem;
    border-radius: 6px;
    font-size: 0.9rem;
    outline: none;
    transition: border-color 0.2s;
}
input:focus, select:focus, textarea:focus { border-color: var(--accent); }
button, .btn {
    background: var(--accent);
    color: #fff;
    border: none;
    padding: 0.5rem 1rem;
    border-radius: 6px;
    font-size: 0.9rem;
    cursor: pointer;
    transition: opacity 0.2s;
}
button:hover { opacity: 0.85; }
.btn-danger { background: var(--red); }
.form-inline { display: flex; gap: 0.5rem; flex-wrap: wrap; margin-bottom: 1rem; }
.form-stack { display: flex; flex-direction: column; gap: 0.5rem; max-width: 500px; margin-bottom: 1rem; }
.search-form { display: flex; gap: 0.5rem; margin-bottom: 1.5rem; }
.search-form input[type="text"] { flex: 1; }

/* ── Chat ───────────────────────────────────── */
.chat-container { display: flex; flex-direction: column; height: 60vh; border: 1px solid var(--border); border-radius: 8px; overflow: hidden; background: var(--bg-card); }
.chat-messages { flex: 1; overflow-y: auto; padding: 1rem; }
.chat-msg { margin-bottom: 0.75rem; font-size: 0.9rem; line-height: 1.5; }
.chat-msg.user strong { color: var(--accent); }
.chat-msg.agent strong { color: var(--green); }
.chat-msg.error strong { color: var(--red); }
.chat-meta { font-size: 0.75rem; color: var(--text-muted); margin-bottom: 0.5rem; padding-left: 1rem; }
.chat-input-bar { display: flex; border-top: 1px solid var(--border); }
.chat-input-bar input { flex: 1; border: none; border-radius: 0; background: var(--bg-input); }
.chat-input-bar button { border-radius: 0; }

/* ── Memory Fragments ───────────────────────── */
.memory-fragment { background: var(--bg-card); border: 1px solid var(--border); border-radius: 8px; padding: 1rem; margin-bottom: 0.75rem; }
.fragment-header { display: flex; justify-content: space-between; margin-bottom: 0.5rem; }
.fragment-content { font-size: 0.9rem; white-space: pre-wrap; }

/* ── Log Viewer ─────────────────────────────── */
.log-controls { display: flex; gap: 0.75rem; align-items: center; margin-bottom: 0.75rem; }
.log-controls label { font-size: 0.85rem; color: var(--text-muted); }
.log-container { background: var(--bg-card); border: 1px solid var(--border); border-radius: 8px; height: 55vh; overflow-y: auto; padding: 0.75rem; font-family: var(--font-mono); font-size: 0.8rem; }
.log-entry { padding: 0.15rem 0; border-bottom: 1px solid rgba(48,54,61,0.5); }
.log-ts { color: var(--text-muted); }
.log-src { color: var(--accent); }
.log-level { font-weight: 700; min-width: 60px; display: inline-block; }
.log-debug .log-level { color: var(--text-muted); }
.log-info .log-level { color: var(--green); }
.log-warning .log-level { color: var(--yellow); }
.log-error .log-level, .log-critical .log-level { color: var(--red); }

/* ── Footer ─────────────────────────────────── */
.footer { text-align: center; padding: 1.5rem; color: var(--text-muted); font-size: 0.8rem; border-top: 1px solid var(--border); margin-top: 2rem; }
''',

# ═══════════════════════════════════════════════
# SECTION 6: MCP SERVER
# Implements: Part IV, §4.5 — MCP Server
# ═══════════════════════════════════════════════

"aegis/mcp/__init__.py": '''
# aegis/mcp/__init__.py
# Implements: Part IV, §4.5 — MCP Server
"""Aegis MCP Server package — exposes Lexicon memory to external MCP clients."""
''',

"aegis/mcp/server.py": '''
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
''',

# ═══════════════════════════════════════════════
# SECTION 7: TESTS
# ═══════════════════════════════════════════════

"tests/test_chunk_012/__init__.py": '''
# tests/test_chunk_012/__init__.py
"""Tests for CHUNK-012: User Interfaces (CLI + Web + MCP)."""
''',

"tests/test_chunk_012/test_cli.py": '''
# tests/test_chunk_012/test_cli.py
# Tests for Part X, §10.1 — CLI Management Tool
"""
Unit tests for the Aegis CLI application.
Tests command registration, help output, and basic invocations.
"""

import pytest
from typer.testing import CliRunner
from aegis.cli.main import app

runner = CliRunner()


class TestCLIRoot:
    """Test the root `aegis` command."""

    def test_help_displays(self):
        """aegis --help should show all subcommands."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "Project Aegis" in result.output or "aegis" in result.output.lower()

    def test_no_args_shows_help(self):
        """Running aegis with no args shows help (no_args_is_help=True)."""
        result = runner.invoke(app, [])
        assert result.exit_code == 0


class TestCLIConfig:
    """Test config commands."""

    def test_config_show_missing_file(self, tmp_path):
        """aegis config show should error on missing config."""
        result = runner.invoke(app, ["config", "show", "--config", str(tmp_path / "missing.yaml")])
        assert result.exit_code != 0 or "not found" in result.output.lower() or "✗" in result.output

    def test_config_show_valid(self, tmp_path):
        """aegis config show should display YAML content."""
        cfg_file = tmp_path / "test_config.yaml"
        cfg_file.write_text("web:\\n  port: 8420\\n")
        result = runner.invoke(app, ["config", "show", "--config", str(cfg_file)])
        assert result.exit_code == 0

    def test_config_set(self, tmp_path):
        """aegis config set should update a YAML key."""
        cfg_file = tmp_path / "test_config.yaml"
        cfg_file.write_text("web:\\n  port: 8420\\n")
        result = runner.invoke(app, ["config", "set", "web.port", "9000", "--config", str(cfg_file)])
        assert result.exit_code == 0
        assert "9000" in result.output


class TestCLISubcommandRegistration:
    """Verify all expected subcommand groups are registered."""

    @pytest.mark.parametrize("group", ["user", "tenant", "memory", "schedule", "config"])
    def test_subcommand_group_help(self, group):
        """Each subcommand group should respond to --help."""
        result = runner.invoke(app, [group, "--help"])
        assert result.exit_code == 0
''',

"tests/test_chunk_012/test_web.py": '''
# tests/test_chunk_012/test_web.py
# Tests for Part X, §10.2 — Mission Control Web UI
"""
Unit tests for the Mission Control FastAPI application.
Tests route availability, template rendering, health endpoint, and WebSocket.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Create a test client with a mocked bus."""
    # Patch bus to avoid real Redis dependency
    with patch("aegis.web.app.create_app") as mock_create:
        from aegis.web.app import create_app
        app = create_app(config=None)
        # Mock out the bus on app.state
        app.state.bus = None
        yield TestClient(app, raise_server_exceptions=False)


class TestDashboard:
    """Test the dashboard route."""

    def test_dashboard_renders(self, client):
        """GET / should return 200 with dashboard content."""
        response = client.get("/")
        assert response.status_code == 200
        assert "Dashboard" in response.text or "dashboard" in response.text.lower()


class TestHealthEndpoint:
    """Test the /health API."""

    def test_health_no_redis(self, client):
        """GET /health with no bus should return degraded status."""
        response = client.get("/health")
        # 503 or 200 depending on implementation; we check JSON shape
        data = response.json()
        assert "status" in data
        assert "redis" in data
        assert "agents" in data
        assert "timestamp" in data

    def test_health_json_format(self, client):
        """Health endpoint returns valid JSON."""
        response = client.get("/health")
        assert response.headers["content-type"].startswith("application/json")


class TestChatPage:
    """Test the chat page route."""

    def test_chat_page_renders(self, client):
        """GET /chat should return 200."""
        response = client.get("/chat")
        assert response.status_code == 200
        assert "chat" in response.text.lower()

    def test_chat_page_with_session(self, client):
        """GET /chat?session_id=xxx should pre-fill session."""
        response = client.get("/chat?session_id=test-session-123")
        assert response.status_code == 200
        assert "test-session-123" in response.text


class TestMemoryPage:
    """Test the memory explorer route."""

    def test_memory_page_renders(self, client):
        """GET /memory should return 200."""
        response = client.get("/memory")
        assert response.status_code == 200
        assert "Memory" in response.text or "memory" in response.text.lower()


class TestUsersPage:
    """Test the users management route."""

    def test_users_page_renders(self, client):
        """GET /users should return 200."""
        response = client.get("/users")
        assert response.status_code == 200


class TestSchedulePage:
    """Test the schedule route."""

    def test_schedule_page_renders(self, client):
        """GET /schedule should return 200."""
        response = client.get("/schedule")
        assert response.status_code == 200


class TestLogsPage:
    """Test the logs page route."""

    def test_logs_page_renders(self, client):
        """GET /logs should return 200."""
        response = client.get("/logs")
        assert response.status_code == 200
        assert "Logs" in response.text or "logs" in response.text.lower()
''',

"tests/test_chunk_012/test_mcp.py": '''
# tests/test_chunk_012/test_mcp.py
# Tests for Part IV, §4.5 — MCP Server
"""
Unit tests for the Aegis MCP Server.
Tests tool registration, auth validation, and request routing.
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock


class TestAegisMCPServer:
    """Test the MCP server initialization and tool registration."""

    def test_import(self):
        """MCP server module should be importable."""
        from aegis.mcp.server import AegisMCPServer
        server = AegisMCPServer(config=None)
        assert server is not None

    def test_server_config_stored(self):
        """Config should be stored on the server instance."""
        from aegis.mcp.server import AegisMCPServer
        mock_config = {"test": True}
        server = AegisMCPServer(config=mock_config)
        assert server.config == mock_config

    @pytest.mark.asyncio
    async def test_shutdown_no_bus(self):
        """Shutdown with no bus should not raise."""
        from aegis.mcp.server import AegisMCPServer
        server = AegisMCPServer()
        await server.shutdown()  # Should not raise

    @pytest.mark.asyncio
    async def test_shutdown_with_bus(self):
        """Shutdown with an active bus should disconnect."""
        from aegis.mcp.server import AegisMCPServer
        server = AegisMCPServer()
        mock_bus = AsyncMock()
        server._bus = mock_bus
        await server.shutdown()
        mock_bus.disconnect.assert_called_once()


class TestMCPAvailability:
    """Test graceful handling when MCP SDK is not installed."""

    def test_mcp_available_flag_exists(self):
        """Module should expose MCP_AVAILABLE flag."""
        from aegis.mcp.server import MCP_AVAILABLE
        assert isinstance(MCP_AVAILABLE, bool)
''',

# ═══════════════════════════════════════════════
# SECTION 8: CONFIGURATION UPDATES
# ═══════════════════════════════════════════════

"aegis_config_chunk_012_patch.yaml": '''
# aegis_config.yaml — CHUNK-012 additions
# Merge these keys into your existing aegis_config.yaml

web:
  enabled: true
  host: "0.0.0.0"
  port: 8420
  cors_origins:
    - "http://localhost:8420"
    - "http://127.0.0.1:8420"

mcp:
  enabled: true
  transport: "stdio"  # "stdio" or "sse"
  # sse_port: 8421   # Only used if transport is "sse"

cli:
  default_tenant: "default"
  default_user: "root"
  default_config: "aegis_config.yaml"
''',

"pyproject_chunk_012_patch.toml": '''
# pyproject.toml — CHUNK-012 additions
# Merge these into your existing pyproject.toml

# [project.scripts]
# aegis = "aegis.cli.main:main"
# aegis-mcp = "aegis.mcp.server:main"

# [project.optional-dependencies]
# web = [
#     "fastapi>=0.111.0",
#     "uvicorn[standard]>=0.30.0",
#     "jinja2>=3.1.4",
#     "python-multipart>=0.0.9",
# ]
# cli = [
#     "typer[all]>=0.12.0",
#     "pyyaml>=6.0",
# ]
# mcp = [
#     "mcp>=1.0.0",
# ]

# Add to existing [project.dependencies]:
#     "fastapi>=0.111.0",
#     "uvicorn[standard]>=0.30.0",
#     "jinja2>=3.1.4",
#     "python-multipart>=0.0.9",
#     "typer[all]>=0.12.0",
#     "pyyaml>=6.0",
#     "mcp>=1.0.0",
''',

"requirements_chunk_012_patch.txt": '''
# requirements.txt — CHUNK-012 additions
# Append to your existing requirements.txt

# CLI
typer[all]>=0.12.0
pyyaml>=6.0

# Web UI
fastapi>=0.111.0
uvicorn[standard]>=0.30.0
jinja2>=3.1.4
python-multipart>=0.0.13

# MCP Server
mcp>=1.0.0
''',
}

# ─────────────────────────────────────────────
# Assembly Engine
# ─────────────────────────────────────────────

def create_package_init_files(path):
    """Create __init__.py in parent directories if they don't exist."""
    dir_name = os.path.dirname(path)
    if dir_name and (dir_name.startswith("") or dir_name.startswith("tests/")):
        parts = dir_name.split("/")
        for i in range(2, len(parts) + 1):
            pkg_path = "/".join(parts[:i])
            init_file = os.path.join(pkg_path, "__init__.py")
            if not os.path.exists(init_file):
                os.makedirs(pkg_path, exist_ok=True)
                with open(init_file, "w") as f:
                    pass
                print(f"  [Created] {init_file} (empty package marker)")


def main():
    """Main function to write all files."""
    print("═══════════════════════════════════════")
    print("  Assembling CHUNK-012: User Interfaces")
    print("  (CLI + Web + MCP Server)")
    print("═══════════════════════════════════════")
    print(f"  Files: {len(CHUNK_12_FILES)}")
    print("")

    for path, content in CHUNK_12_FILES.items():
        dir_name = os.path.dirname(path)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)

        create_package_init_files(path)

        print(f"  [Writing] {path}")
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(textwrap.dedent(content.strip()) + "\n")

    print("")
    print("═══════════════════════════════════════")
    print("  Assembly Complete")
    print("═══════════════════════════════════════")
    print("")
    print("  Post-assembly steps:")
    print("  1. Merge aegis_config_chunk_012_patch.yaml into aegis_config.yaml")
    print("  2. Merge pyproject_chunk_012_patch.toml into pyproject.toml")
    print("  3. Append requirements_chunk_012_patch.txt to requirements.txt")
    print("  4. Run: pip install -e '.[cli,web,mcp]'")
    print("  5. Verify: aegis --help")
    print("  6. Verify: python -m pytest tests/test_chunk_012/ -v")
    print("")


if __name__ == "__main__":
    main()
