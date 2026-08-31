# aegis/cli/main.py
# Implements: Part X, §10.1 — CLI Management Tool
"""Root CLI application.

Assembles all command groups into the `aegis` command.

Usage::

    aegis start          Start the Aegis system
    aegis stop           Graceful shutdown
    aegis status         Show system health
    aegis chat           Interactive chat with TOrchestrator
    aegis user ...       User management
    aegis tenant ...     Tenant management
    aegis memory ...     Memory search / export / import
    aegis schedule ...   Scheduler management
    aegis config ...     Configuration management
    aegis secrets ...    Secret/Key management

Note: .env file values are loaded into os.environ via python-dotenv
so that environment variables (e.g. OPENROUTER_API_KEY) are available.
"""

from __future__ import annotations

import logging

import structlog
from dotenv import load_dotenv
from pathlib import Path

# Load .env file values into os.environ so environment variables
# (e.g. OPENROUTER_API_KEY) are available to the CLI and system
env_path = Path(__file__).parent.parent.parent / ".env"
if env_path.is_file():
    load_dotenv(dotenv_path=env_path)

import typer

# --- Import command FUNCTIONS and sub-apps ---
from aegis.cli.commands.start import start
from aegis.cli.commands.stop import stop
from aegis.cli.commands.status import status
from aegis.cli.commands.chat import chat
from aegis.cli.commands.install import install
from aegis.cli.commands.user import app as user_app
from aegis.cli.commands.tenant import app as tenant_app
from aegis.cli.commands.memory import app as memory_app
from aegis.cli.commands.schedule import app as schedule_app
from aegis.cli.commands.config import app as config_app
from aegis.cli.commands.secrets import app as secrets_app

app = typer.Typer(
    name="aegis",
    help="Project Aegis — Local-First Multi-Agent System",
    no_args_is_help=False,
    rich_markup_mode="rich",
)

# --- Register top-level commands (the correct way) ──────
app.command()(start)
app.command()(stop)
app.command()(status)
app.command()(chat)
app.command()(install)

# Register sub-command groups ────────────────────────
app.add_typer(user_app, name="user", help="User management commands.")
app.add_typer(tenant_app, name="tenant", help="Tenant management commands.")
app.add_typer(memory_app, name="memory", help="Lexicon memory commands.")
app.add_typer(schedule_app, name="schedule", help="Scheduler management commands.")
app.add_typer(config_app, name="config", help="Configuration commands.")
app.add_typer(secrets_app, name="secrets", help="Secret/Key management commands.")


def main() -> None:
    """Entry point invoked by the console_scripts hook."""
    app()


if __name__ == "__main__":
    main()