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
        typer.echo(f"\n── Result {i} [{frag.get('tier', '?')}] (relevance: {frag.get('relevance', 0):.2f}) ──")
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
