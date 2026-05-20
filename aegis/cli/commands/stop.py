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
