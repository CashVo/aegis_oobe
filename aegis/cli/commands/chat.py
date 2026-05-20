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
                    typer.echo("\n[✓] Chat session ended.")
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
        typer.echo("\n[✓] Chat ended.")
