# aegis/cli/commands/user.py
# Implements: Part X, §10.1 — `aegis user` subcommands
"""
User management: create, list, update, delete.
Routes through the Identity Agent via the bus.
"""

import asyncio
import logging
from typing import Optional, Annotated
import typer
import uuid

app = typer.Typer()

logger = logging.getLogger(__name__)


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


async def _send_identity_request_with_response(config_path: str, action: str, payload: dict) -> dict:
    """Helper: send an Identity protocol request that expects a response on a reply channel."""
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


@app.command("bootstrap")
def bootstrap(
    username: Annotated[str, typer.Option("--username", "-u", help="Root username")] = "root",
    display_name: Annotated[str, typer.Option("--name", "-n", help="Root display name")] = "System Root",
    passphrase: Annotated[Optional[str], typer.Option("--passphrase", "-p", help="Root passphrase (optional)")] = None,
    tenant_name: Annotated[str, typer.Option("--tenant-name", help="Initial tenant name")] = "Default",
    config: Annotated[str, typer.Option("--config", "-c", help="Config file path")] = "aegis_config.yaml",
) -> None:
    """Bootstrap the identity system (first-run initialization). Creates the initial tenant and root user."""
    async def _run_bootstrap():
        from aegis.config import load_config
        from aegis.bus.redis_bus import RedisBus
        from aegis.schemas.message import AegisMessage, MessageType

        cfg = load_config(config)
        bus = RedisBus(cfg)
        await bus.connect()

        correlation_id = str(uuid.uuid4())
        response_channel = f"aegis:stream:cli:identity:{correlation_id}"
        consumer_group = f"cli-identity-{correlation_id}"

        try:
            await bus.create_consumer_group(response_channel, consumer_group)
            logger.info(f"Created consumer group {consumer_group} on {response_channel}")
        except Exception as e:
            logger.warning(f"Consumer group creation: {e}")

        # Call the Identity Agent's run_bootstrap method via the message bus
        msg = AegisMessage(
            correlation_id=correlation_id,
            source_agent="cli",
            target_agent="identity",
            message_type=MessageType.REQUEST,
            tenant_id="bootstrap",  # Special tenant for bootstrap
            user_id="bootstrap",
            action="identity.run_bootstrap",
            payload={
                "root_username": username,
                "root_display_name": display_name,
                "root_passphrase": passphrase,
                "tenant_name": tenant_name,
            },
            metadata={"response_channel": response_channel},
        )
        logger.info(f"Publishing bootstrap request to aegis:stream:identity with response_channel={response_channel}")
        await bus.publish("aegis:stream:identity", msg)

        timeout_at = asyncio.get_event_loop().time() + 30
        result = {"success": False, "error": "timeout"}
        while asyncio.get_event_loop().time() < timeout_at:
            messages = await bus.consume(
                response_channel, consumer_group, "cli", count=1, block_ms=500
            )
            if messages:
                logger.info(f"Received {len(messages)} messages from {response_channel}")
                for _, data in messages:
                    parsed = AegisMessage.model_validate(data)
                    result = parsed.payload
                break

        await bus.disconnect()
        return result

    result = asyncio.run(_run_bootstrap())
    if result.get("success"):
        typer.echo(f"[✓] Bootstrap complete!")
        data = result.get("data", {})
        tenant = data.get("tenant", {})
        root_user = data.get("root_user", {})
        typer.echo(f"  Tenant: {tenant.get('name', 'N/A')} ({tenant.get('tenant_id', 'N/A')})")
        typer.echo(f"  Root User: {root_user.get('username', 'N/A')} ({root_user.get('user_id', 'N/A')})")
    else:
        typer.echo(f"[✗] Bootstrap failed: {result.get('error', 'Unknown error')}", err=True)
