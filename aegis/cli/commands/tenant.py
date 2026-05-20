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
