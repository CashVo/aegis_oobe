#!/usr/bin/env python3
# utils/dev.py
# Development utilities for Aegis

"""
Development utilities for Aegis.

Provides commands for development workflow:
- delete-aegis: Complete uninstall/cleanup for fresh start
- reset-db: Reset databases only
- clean-logs: Clean log files
"""

import asyncio
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Annotated, Optional

import typer

app = typer.Typer(
    name="aegis-dev",
    help="Aegis development utilities",
    no_args_is_help=True,
    rich_markup_mode="rich",
)


def get_aegis_root() -> Path:
    """Get the Aegis project root directory."""
    # Start from this file's location and go up
    return Path(__file__).parent.parent


def confirm_destructive(action: str) -> bool:
    """Confirm a destructive action."""
    typer.echo(f"⚠️  WARNING: This will {action}.")
    typer.echo("   This action cannot be undone.")
    return typer.confirm("   Are you sure you want to continue?")


@app.command("delete-aegis")
def delete_aegis(
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Skip confirmation prompt"),
    ] = False,
    keep_venv: Annotated[
        bool,
        typer.Option("--keep-venv", help="Keep the virtual environment"),
    ] = False,
    keep_config: Annotated[
        bool,
        typer.Option("--keep-config", help="Keep aegis_config.yaml"),
    ] = False,
) -> None:
    """
    Complete uninstall/cleanup of Aegis for a fresh start.

    Removes:
    - aegis_data/ directory (all databases, caches, logs)
    - __pycache__ directories
    - .pytest_cache
    - .venv/ (unless --keep-venv)
    - aegis_config.yaml (unless --keep-config)
    - Redis keys (flushes aegis:* namespace)
    """
    root = get_aegis_root()
    typer.echo("═" * 60)
    typer.echo("  AEGIS DEVELOPMENT CLEANUP")
    typer.echo("═" * 60)

    if not force:
        if not confirm_destructive("permanently delete all Aegis data"):
            typer.echo("Aborted.")
            raise typer.Exit(0)

    # Paths to remove
    paths_to_remove = [
        root / "aegis_data",
        root / ".pytest_cache",
        root / ".coverage",
        root / "htmlcov",
    ]

    # Add __pycache__ directories
    for pycache in root.rglob("__pycache__"):
        paths_to_remove.append(pycache)

    for pyc in root.rglob("*.pyc"):
        paths_to_remove.append(pyc)

    # Handle venv
    venv_path = root / ".venv"
    if not keep_venv and venv_path.exists():
        paths_to_remove.append(venv_path)

    # Handle config
    config_path = root / "aegis_config.yaml"
    if not keep_config and config_path.exists():
        paths_to_remove.append(config_path)

    typer.echo("\n[1/4] Removing filesystem data...")
    removed_count = 0
    for path in paths_to_remove:
        if path.exists():
            try:
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()
                typer.echo(f"  ✓ Removed: {path.relative_to(root)}")
                removed_count += 1
            except Exception as e:
                typer.echo(f"  ✗ Failed to remove {path}: {e}")

    typer.echo(f"  Removed {removed_count} items")

    # Clean Redis
    typer.echo("\n[2/4] Cleaning Redis (aegis:* keys)...")
    try:
        result = subprocess.run(
            ["redis-cli", "--scan", "--pattern", "aegis:*"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            keys = result.stdout.strip().split("\n")
            if keys and keys[0]:
                # Delete all aegis keys
                delete_result = subprocess.run(
                    ["redis-cli", "DEL"] + keys,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if delete_result.returncode == 0:
                    typer.echo(f"  ✓ Deleted {len(keys)} Redis keys")
                else:
                    typer.echo(f"  ✗ Failed to delete Redis keys: {delete_result.stderr}")
            else:
                typer.echo("  No aegis:* keys found")
        else:
            typer.echo("  No aegis:* keys found or Redis not accessible")
    except Exception as e:
        typer.echo(f"  ✗ Redis cleanup failed: {e}")

    # Stop any running Redis (optional)
    typer.echo("\n[3/4] Checking for running Aegis processes...")
    try:
        result = subprocess.run(
            ["pkill", "-f", "aegis"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            typer.echo("  ✓ Stopped Aegis processes")
        else:
            typer.echo("  No Aegis processes found")
    except Exception:
        typer.echo("  Could not check processes")

    # Summary
    typer.echo("\n[4/4] Cleanup complete!")
    typer.echo("═" * 60)
    typer.echo("  Aegis has been reset to a clean state.")
    if not keep_venv:
        typer.echo("  Run 'python -m venv .venv && source .venv/bin/activate'")
        typer.echo("  Then 'pip install -e \".[dev]\"' to reinstall.")
    typer.echo("  Then run 'aegis install' for a fresh first-run experience.")
    typer.echo("═" * 60)


@app.command("reset-db")
def reset_db(
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Skip confirmation prompt"),
    ] = False,
) -> None:
    """Reset only the databases (keeps venv, config, logs)."""
    root = get_aegis_root()

    if not force:
        if not confirm_destructive("reset all databases"):
            typer.echo("Aborted.")
            raise typer.Exit(0)

    typer.echo("Resetting databases...")
    db_path = root / "aegis_data"
    if db_path.exists():
        shutil.rmtree(db_path)
        typer.echo(f"  ✓ Removed {db_path}")

    # Clear Redis
    try:
        result = subprocess.run(
            ["redis-cli", "--scan", "--pattern", "aegis:*"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            keys = result.stdout.strip().split("\n")
            if keys and keys[0]:
                subprocess.run(
                    ["redis-cli", "DEL"] + keys,
                    capture_output=True,
                    timeout=10,
                )
                typer.echo(f"  ✓ Deleted {len(keys)} Redis keys")
    except Exception as e:
        typer.echo(f"  Redis cleanup: {e}")

    typer.echo("  ✓ Database reset complete")


@app.command("clean-logs")
def clean_logs() -> None:
    """Clean log files only."""
    root = get_aegis_root()
    log_dirs = [
        root / "logs",
        root / "aegis_data" / "logs",
    ]

    for log_dir in log_dirs:
        if log_dir.exists():
            shutil.rmtree(log_dir)
            typer.echo(f"  ✓ Removed {log_dir}")

    # Recreate log dirs
    for log_dir in log_dirs:
        log_dir.mkdir(parents=True, exist_ok=True)

    typer.echo("  ✓ Logs cleaned and directories recreated")


@app.command("install-dev")
def install_dev(
    editable: Annotated[
        bool,
        typer.Option("--editable/--no-editable", "-e", help="Install in editable mode"),
    ] = True,
) -> None:
    """Install Aegis in development mode with all dependencies."""
    root = get_aegis_root()

    typer.echo("Installing Aegis in development mode...")

    cmd = [sys.executable, "-m", "pip", "install"]
    if editable:
        cmd.append("-e")
    cmd.append(".\"[dev]\"")

    result = subprocess.run(cmd, cwd=root)
    if result.returncode == 0:
        typer.echo("✓ Development installation complete")
    else:
        typer.echo("✗ Installation failed")
        raise typer.Exit(1)


@app.command("test")
def run_tests(
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Verbose output"),
    ] = False,
    coverage: Annotated[
        bool,
        typer.Option("--coverage", help="Run with coverage"),
    ] = False,
    pattern: Annotated[
        Optional[str],
        typer.Option("--pattern", "-k", help="Run tests matching pattern"),
    ] = None,
) -> None:
    """Run the test suite."""
    root = get_aegis_root()

    cmd = ["python", "-m", "pytest"]
    if verbose:
        cmd.append("-v")
    else:
        cmd.append("-q")

    if coverage:
        cmd.extend(["--cov=aegis", "--cov-report=term-missing"])

    if pattern:
        cmd.extend(["-k", pattern])

    typer.echo(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=root)
    if result.returncode != 0:
        raise typer.Exit(result.returncode)


@app.command("start-redis")
def start_redis() -> None:
    """Start Redis server if not running."""
    typer.echo("Starting Redis...")
    try:
        subprocess.run(["redis-server", "--daemonize", "yes"], check=True)
        import time
        time.sleep(1)
        result = subprocess.run(["redis-cli", "ping"], capture_output=True, text=True)
        if result.returncode == 0 and "PONG" in result.stdout:
            typer.echo("✓ Redis started successfully")
        else:
            typer.echo("✗ Redis failed to start")
    except Exception as e:
        typer.echo(f"✗ Failed to start Redis: {e}")


@app.command("stop-redis")
def stop_redis() -> None:
    """Stop Redis server."""
    typer.echo("Stopping Redis...")
    try:
        subprocess.run(["redis-cli", "shutdown"], check=True)
        typer.echo("✓ Redis stopped")
    except Exception as e:
        typer.echo(f"✗ Failed to stop Redis: {e}")


if __name__ == "__main__":
    app()