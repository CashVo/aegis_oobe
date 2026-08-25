# aegis/cli/commands/install.py
# Implements: Part X, §10.1 — `aegis install` first-run setup

"""
First-run installation and setup for Aegis.

This command handles the complete first-run experience:
1. Install missing dependencies (web UI, MCP)
2. Start Redis if not running
3. Start the Aegis system
4. Bootstrap the identity store with root user and tenant
"""

import asyncio
import subprocess
import sys
import time
from typing import Annotated, Optional

import typer

app = typer.Typer()

# Optional dependencies that might not be in the base install
OPTIONAL_DEPS = [
    "fastapi>=0.111.0",
    "uvicorn[standard]>=0.30.0",
    "jinja2>=3.1.4",
    "python-multipart>=0.0.9",
    "mcp>=1.0.0",
    "plotly>=5.0.0",
]


def check_redis_running() -> bool:
    """Check if Redis is running and accessible."""
    try:
        result = subprocess.run(
            ["redis-cli", "ping"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        return result.returncode == 0 and "PONG" in result.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def install_redis() -> bool:
    """Attempt to install Redis server."""
    typer.echo("  Installing Redis...")
    try:
        # Try apt (Ubuntu/Debian)
        result = subprocess.run(
            ["apt-get", "update", "&&", "apt-get", "install", "-y", "redis-server"],
            shell=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0:
            return True
    except Exception:
        pass

    try:
        # Try brew (macOS)
        result = subprocess.run(
            ["brew", "install", "redis"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0:
            return True
    except Exception:
        pass

    try:
        # Try dnf (Fedora/RHEL)
        result = subprocess.run(
            ["dnf", "install", "-y", "redis"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0:
            return True
    except Exception:
        pass

    typer.echo("  [✗] Could not install Redis automatically. Please install Redis manually.")
    return False


def start_redis() -> bool:
    """Attempt to start Redis server."""
    # First try to start if already installed
    try:
        # Try systemctl first (systemd)
        result = subprocess.run(
            ["systemctl", "start", "redis"],
            capture_output=True,
            timeout=10,
        )
        if result.returncode == 0:
            return True
    except FileNotFoundError:
        pass

    try:
        # Try brew services (macOS)
        result = subprocess.run(
            ["brew", "services", "start", "redis"],
            capture_output=True,
            timeout=10,
        )
        if result.returncode == 0:
            return True
    except FileNotFoundError:
        pass

    try:
        # Try redis-server directly
        subprocess.Popen(
            ["redis-server", "--daemonize", "yes"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(1)
        return check_redis_running()
    except FileNotFoundError:
        pass

    # Redis not installed, try to install it
    typer.echo("  Redis not found, attempting to install...")
    if install_redis():
        # Try starting again after installation
        try:
            subprocess.Popen(
                ["redis-server", "--daemonize", "yes"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            time.sleep(1)
            return check_redis_running()
        except FileNotFoundError:
            pass

    return False


def install_optional_deps() -> bool:
    """Install optional dependencies for web UI and MCP."""
    try:
        typer.echo("  Installing optional dependencies (web UI, MCP)...")
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-q"] + OPTIONAL_DEPS,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            typer.echo(f"  Warning: Some optional dependencies failed to install: {result.stderr}")
            return False
        return True
    except subprocess.TimeoutExpired:
        typer.echo("  Warning: Optional dependency installation timed out")
        return False
    except Exception as e:
        typer.echo(f"  Warning: Failed to install optional dependencies: {e}")
        return False


async def run_bootstrap(
    username: str,
    display_name: str,
    passphrase: Optional[str],
    tenant_name: str,
    config: str,
) -> bool:
    """Run the bootstrap command via the message bus."""
    from aegis.config import load_config
    from aegis.bus.redis_bus import RedisBus
    from aegis.schemas.message import AegisMessage, MessageType
    import uuid

    cfg = load_config(config)
    bus = RedisBus(cfg)
    await bus.connect()

    correlation_id = str(uuid.uuid4())
    response_channel = f"aegis:stream:cli:identity:{correlation_id}"
    consumer_group = f"cli-identity-{correlation_id}"

    try:
        await bus.create_consumer_group(response_channel, consumer_group)
    except Exception:
        pass

    msg = AegisMessage(
        correlation_id=correlation_id,
        source_agent="cli",
        target_agent="identity",
        message_type=MessageType.REQUEST,
        tenant_id="bootstrap",
        user_id="bootstrap",
        action="identity.run_bootstrap",
        payload={
            "root_username": username,
            "root_display_name": display_name,
            "root_passphrase": passphrase,
            "tenant_name": tenant_name,
        },
        metadata={"response_channel": response_channel},
    )
    await bus.publish("aegis:stream:identity", msg)

    timeout_at = asyncio.get_event_loop().time() + 30
    result = {"success": False, "error": "timeout"}
    while asyncio.get_event_loop().time() < timeout_at:
        messages = await bus.consume(
            response_channel, consumer_group, "cli", count=1, block_ms=500
        )
        if messages:
            for _, data in messages:
                result = data
            break
        await asyncio.sleep(0.1)

    await bus.disconnect()
    # The response is an AegisMessage with payload containing success
    if isinstance(result, dict):
        if "payload" in result and isinstance(result["payload"], dict):
            return result["payload"].get("success", False)
    return result.get("success", False)


@app.command()
def install(
    username: Annotated[
        str,
        typer.Option("--username", "-u", help="Root username"),
    ] = "root",
    display_name: Annotated[
        str,
        typer.Option("--name", "-n", help="Root display name"),
    ] = "System Root",
    passphrase: Annotated[
        Optional[str],
        typer.Option("--passphrase", "-p", help="Root passphrase (optional)"),
    ] = None,
    tenant_name: Annotated[
        str,
        typer.Option("--tenant-name", help="Initial tenant name"),
    ] = "Default",
    config: Annotated[
        str,
        typer.Option("--config", "-c", help="Config file path"),
    ] = "aegis_config.yaml",
    skip_deps: Annotated[
        bool,
        typer.Option("--skip-deps", help="Skip optional dependency installation"),
    ] = False,
    skip_redis: Annotated[
        bool,
        typer.Option("--skip-redis", help="Skip Redis installation and startup"),
    ] = False,
) -> None:
    """
    Run the complete first-run installation for Aegis.

    This command will:
    1. Install optional dependencies (web UI, MCP server)
    2. Install and start Redis if not running
    3. Start the Aegis system
    4. Bootstrap the identity store with root user and tenant

    After completion, the system will be running and accessible at http://localhost:8420
    """

    import sys
    
    # Environment info
    venv_path = sys.prefix
    python_path = sys.executable
    in_venv = hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix)
    
    async def _run_install():
        typer.echo("═" * 60)
        typer.echo("  AEGIS FIRST-RUN INSTALLATION")
        typer.echo("═" * 60)
        typer.echo(f"  Root User: {username} ({display_name})")
        typer.echo(f"  Tenant: {tenant_name}")
        typer.echo(f"  Config: {config}")
        typer.echo(f"  Python: {python_path}")
        typer.echo(f"  Virtual Env: {venv_path if in_venv else 'NOT IN VENV'}")
        typer.echo(f"  Platform: {sys.platform}")
        typer.echo("")

        # Step 1: Install optional dependencies
        installed_deps = []
        if not skip_deps:
            typer.echo("[1/4] Checking optional dependencies...")
            if not install_optional_deps():
                typer.echo("  [✗] Some optional dependencies failed (continuing anyway)")
            else:
                typer.echo("  [✓] Optional dependencies installed")
                installed_deps = ["fastapi", "uvicorn", "jinja2", "python-multipart", "mcp", "plotly"]
        else:
            typer.echo("[1/4] Skipping optional dependency installation")

        # Step 2: Start Redis
        if not skip_redis:
            typer.echo("[2/4] Checking Redis...")
            if check_redis_running():
                typer.echo("  [✓] Redis is already running")
            else:
                typer.echo("  Redis not running, attempting to start...")
                if start_redis():
                    typer.echo("  [✓] Redis started successfully")
                else:
                    typer.echo("  [✗] Failed to start Redis automatically")
                    typer.echo("  Please start Redis manually and re-run this command")
                    raise typer.Exit(code=1)
        else:
            typer.echo("[2/4] Skipping Redis check")

        # Step 3: Start Aegis system
        typer.echo("[3/4] Starting Aegis system...")

        # Import here to avoid circular imports
        from aegis.manager.system_manager import SystemManager

        manager = SystemManager(config)

        await manager.startup()
        typer.echo("  [✓] All agents online")

        # Step 4: Run bootstrap
        typer.echo("[4/4] Bootstrapping identity store...")

        # Give the system a moment to fully initialize
        await asyncio.sleep(2)

        # Check if bootstrap is needed (fresh install vs re-run)
        from aegis.identity.store import IdentityStore
        from aegis.config import load_config
        cfg = load_config(config)
        data_dir = cfg.data_dir
        db_path = f"{data_dir}/identity.db"
        store = IdentityStore(db_path=db_path)
        await store.initialize()
        needs_bootstrap = await store.is_empty()
        await store.close()
        
        if not needs_bootstrap:
            typer.echo("  [!] Identity store already has tenants — skipping bootstrap (re-run detected)")
            success = True
        else:
            success = await run_bootstrap(username, display_name, passphrase, tenant_name, config)

        if success:
            typer.echo("  [✓] Bootstrap complete!")
            typer.echo(f"      Tenant: {tenant_name}")
            typer.echo(f"      Root User: {username}")
        else:
            typer.echo("  [✗] Bootstrap failed")
            raise typer.Exit(code=1)

        # Summary
        typer.echo("")
        typer.echo("═" * 60)
        typer.echo("  INSTALLATION COMPLETE")
        typer.echo("═" * 60)
        typer.echo("")
        typer.echo("  Aegis is now running with:")
        typer.echo(f"    • Root user: {username}")
        typer.echo(f"    • Tenant: {tenant_name}")
        if installed_deps:
            typer.echo(f"    • Optional dependencies installed: {', '.join(installed_deps)}")
        typer.echo(f"    • Mission Control: http://localhost:8420")
        typer.echo("")
        typer.echo("  Next steps:")
        typer.echo("    • Open http://localhost:8420 for Mission Control")
        typer.echo("    • Run 'aegis chat' for CLI chat with TOrchestrator")
        typer.echo("    • Run 'aegis stop' to gracefully shutdown")
        typer.echo("")
        typer.echo("  Environment:")
        typer.echo(f"    • Python: {python_path}")
        typer.echo(f"    • Virtual Env: {venv_path if in_venv else 'NOT IN VENV'}")
        typer.echo(f"    • Platform: {sys.platform}")
        typer.echo("")
        typer.echo("  Press Ctrl+C to stop the system")

        # Keep the system running
        try:
            await manager._shutdown_event.wait()
        except KeyboardInterrupt:
            typer.echo("\n[…] Shutting down gracefully…")
        finally:
            await manager.shutdown()
            typer.echo("[✓] Aegis stopped")

    asyncio.run(_run_install())


if __name__ == "__main__":
    app()