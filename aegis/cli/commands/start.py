# aegis/cli/commands/start.py
# Implements: Part X, §10.1 — `aegis start`
"""
Start the Aegis system via System Manager.
"""

import asyncio
import sys
import typer
from typing import Annotated


def start(
    config: Annotated[str, typer.Option(
        "--config", "-c",
        help="Path to the Aegis configuration file.",
    )] = "aegis_config.yaml",

    web: Annotated[bool, typer.Option(
        help="Enable or disable the Mission Control Web UI.",
    )] = True,

    web_port: Annotated[int, typer.Option(
        "--port", "-p",
        help="Port for the Mission Control Web UI.",
    )] = 8420,

) -> None:
    """Start the Aegis system (System Manager bootstrap)."""
    import os
    
    # Environment info
    venv_path = sys.prefix
    python_path = sys.executable
    in_venv = hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix)
    
    typer.echo("═══════════════════════════════════════")
    typer.echo("  Project Aegis — Starting System")
    typer.echo("═══════════════════════════════════════")
    typer.echo(f"  Config       : {config}")
    typer.echo(f"  Web UI       : {'enabled' if web else 'disabled'}")
    if web:
        typer.echo(f"  Port         : {web_port}")
    typer.echo(f"  Python       : {python_path}")
    typer.echo(f"  Virtual Env  : {venv_path if in_venv else 'NOT IN VENV'}")
    typer.echo(f"  Platform     : {sys.platform}")
    typer.echo("")

    from aegis.manager.system_manager import SystemManager
    from aegis.config import load_config

    cfg = load_config(config)

    async def _run() -> None:
        manager = SystemManager(cfg)
        try:
            await manager.startup()
            typer.echo("[✓] All agents online. System ready.")
            if web:
                typer.echo(f"[✓] Mission Control → http://localhost:{web_port}")
                # Launch web server alongside agent loop
                try:
                    from aegis.web.app import create_app
                    import uvicorn
                except ImportError as e:
                    typer.echo(f"[✗] Web UI dependencies not installed: {e}")
                    typer.echo("    Run 'aegis install' or 'pip install -e \".[web]\"' to install web dependencies.")
                    raise typer.Exit(code=1)

                web_app = create_app(cfg)
                web_config = uvicorn.Config(
                    web_app,
                    host="0.0.0.0",
                    port=web_port,
                    log_level="info",
                )
                server = uvicorn.Server(web_config)
                await server.serve()
            else:
                # Block until interrupted
                while True:
                    await asyncio.sleep(1)
        except KeyboardInterrupt:
            typer.echo("\n[…] Shutting down gracefully…")
        finally:
            await manager.shutdown()
            typer.echo("[✓] Aegis stopped.")

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        pass
