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
    schedule_type: Annotated[str, typer.Option("--type", prompt=True, help="cron, interval, or date")],
    schedule_config: Annotated[str, typer.Option("--config-json", prompt=True, help='e.g. `{"hour": 2}`')],
    action: Annotated[str, typer.Option("--action", "-a", prompt=True, help="AegisMessage action")],
    description: Annotated[str, typer.Option("--desc", "-d")] = "",
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
