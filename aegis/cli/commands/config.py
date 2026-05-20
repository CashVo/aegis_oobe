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
