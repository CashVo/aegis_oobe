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
            if bus.connected:
                await bus.disconnect()

        agents_status = {}
        if redis_ok:
            try:
                import redis.asyncio as aioredis
                # Reconnect for this query
                await bus.connect()
                r = bus.client
                keys = await r.keys("aegis:heartbeat:*")
                for key in keys:
                    agent_name = key.decode().split(":")[-1]
                    val = await r.get(key)
                    agents_status[agent_name] = "running" if val else "unknown"
            except Exception:
                pass
            finally:
                if bus.connected:
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
