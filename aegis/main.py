# File: aegis/main.py
# Purpose: Entry point stub. Loads config, prints banner, exits.

import structlog
import typer
from rich.console import Console
from rich.panel import Panel

from aegis.config import AegisConfig, load_config

# Initialize a rich console for pretty printing
console = Console()

# Configure structured logging
log = structlog.get_logger()

# Create the Typer CLI application
cli_app = typer.Typer(name="aegis")

@cli_app.command()
def main(
    config_file: str = typer.Option(
        "aegis_config.yaml",
        "--config",
        "-c",
        help="Path to the YAML configuration file.",
    )
):
    """
    Initializes and runs the Aegis System.

    This is the main entry point which will eventually start the System Manager
    and all configured agents. For now, it just loads configuration and
    displays a startup banner.
    """
    try:
        config = load_config(config_file)
        _print_banner(config)
    except FileNotFoundError:
        console.print(f"[bold red]Error:[/bold red] Configuration file not found at '{config_file}'.")
        raise typer.Exit(code=1)
    except Exception as e:
        console.print(f"[bold red]An unexpected error occurred during startup:[/bold red]\n{e}")
        log.exception("Startup failed")
        raise typer.Exit(code=1)

    log.info("Aegis startup sequence complete (CHUNK-001 stub). Exiting.")

def _print_banner(config: AegisConfig):
    """Prints a startup banner with key configuration details."""
    banner_text = (
        f"[bold cyan]Project Aegis[/bold cyan] [dim]v{config.version}[/dim]\n"
        f"Local-First Multi-Agent System\n"
        f"—"
    )
    config_details = (
        f" • [b]Log Level:[/b] {config.log_level}\n"
        f" • [b]Data Dir:[/b]  {config.data_dir}\n"
        f" • [b]Redis:[/b]      {config.redis.host}:{config.redis.port}\n"
    )
    panel_content = f"{banner_text}\n{config_details}"
    console.print(
        Panel(
            panel_content,
            title="[yellow]SYSTEM BOOT[/yellow]",
            border_style="blue",
            expand=False,
        )
    )

if __name__ == "__main__":
    cli_app()
