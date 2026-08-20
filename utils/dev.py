#!/usr/bin/env python3
# utils/dev.py
# Development utilities for Aegis

"""
Development utilities for Aegis.

Provides commands for development workflow:
- delete-aegis: Complete uninstall/cleanup for fresh start
- reset-db: Reset databases only
- clean-logs: Clean log files
- setup-envs: Create dev/test/prod worktrees
- populate-test-data: Generate sample observability data
- worktree: Manage git worktrees
- start-dev: Start dev server with hot reload
- build-docs: Build documentation for GitHub Pages
"""

import asyncio
import json
import os
import random
import shutil
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Annotated, Optional
from uuid import uuid4

import typer

from redis.asyncio import Redis
from aegis.schemas.message import AegisMessage, MessageType, Priority

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


# ============================================
# Git Worktree Management
# ============================================

@app.command("setup-envs")
def setup_envs(
    base_dir: Annotated[
        Optional[Path],
        typer.Option("--base-dir", help="Base directory for worktrees (default: parent of repo)"),
    ] = None,
    dev_branch: Annotated[str, typer.Option("--dev-branch", help="Branch for dev worktree")] = "main",
    test_branch: Annotated[str, typer.Option("--test-branch", help="Branch for test worktree")] = "test",
    prod_branch: Annotated[str, typer.Option("--prod-branch", help="Branch for prod worktree")] = "prod",
) -> None:
    """Create dev/test/prod worktrees for multi-environment workflow."""
    root = get_aegis_root()
    base = base_dir or root.parent

    typer.echo("═" * 60)
    typer.echo("  SETTING UP MULTI-ENVIRONMENT WORKTREES")
    typer.echo("═" * 60)

    worktrees = [
        ("dev", dev_branch, base / "aegis-dev"),
        ("test", test_branch, base / "aegis-test"),
        ("prod", prod_branch, base / "aegis-prod"),
    ]

    for name, branch, path in worktrees:
        if path.exists():
            typer.echo(f"  ⚠ {name} worktree already exists at {path}")
            continue

        # Ensure branch exists
        result = subprocess.run(
            ["git", "rev-parse", "--verify", branch],
            cwd=root,
            capture_output=True,
        )
        if result.returncode != 0:
            # Create branch from main
            typer.echo(f"  Creating branch '{branch}' from main...")
            subprocess.run(["git", "branch", branch, "main"], cwd=root, check=True)

        typer.echo(f"  Creating {name} worktree at {path}...")
        subprocess.run(["git", "worktree", "add", str(path), branch], cwd=root, check=True)
        typer.echo(f"  ✓ {name} worktree ready")

    # Initialize each environment
    for name, _, path in worktrees:
        typer.echo(f"\n  Initializing {name} environment...")
        _init_environment(path, name)

    typer.echo("\n" + "═" * 60)
    typer.echo("  ALL ENVIRONMENTS READY")
    typer.echo("═" * 60)
    typer.echo("  Dev:  cd ../aegis-dev && python -m utils.dev start-dev")
    typer.echo("  Test: cd ../aegis-test && python -m utils.dev populate-test-data")
    typer.echo("  Prod: cd ../aegis-prod && python -m utils.dev health-check")


def _init_environment(path: Path, env_name: str) -> None:
    """Initialize environment with config and dependencies."""
    # Copy config template if needed
    config_src = path / "aegis_config.yaml.example"
    config_dst = path / "aegis_config.yaml"
    if config_src.exists() and not config_dst.exists():
        shutil.copy(config_src, config_dst)
        typer.echo(f"    ✓ Created {env_name} config from template")

    # Create .env template
    env_file = path / ".env"
    if not env_file.exists():
        env_content = f"""# Aegis {env_name.upper()} Environment
AEGIS_ENV={env_name}
AEGIS_LOG_LEVEL={"DEBUG" if env_name == "dev" else "INFO" if env_name == "test" else "WARNING"}
REDIS_DB={"0" if env_name == "dev" else "1" if env_name == "test" else "2"}
"""
        env_file.write_text(env_content)
        typer.echo(f"    ✓ Created {env_name} .env template")


@app.command("worktree")
def worktree_cmd(
    action: Annotated[str, typer.Argument(help="Action: list, create, remove, sync")],
    name: Annotated[Optional[str], typer.Argument(help="Worktree name (for create/remove)")] = None,
    branch: Annotated[Optional[str], typer.Option("--branch", "-b", help="Branch for new worktree")] = None,
) -> None:
    """Manage git worktrees."""
    root = get_aegis_root()

    if action == "list":
        result = subprocess.run(
            ["git", "worktree", "list"], cwd=root, capture_output=True, text=True
        )
        typer.echo(result.stdout or "No worktrees")

    elif action == "create":
        if not name:
            typer.echo("Error: worktree name required for create")
            raise typer.Exit(1)
        target_branch = branch or name
        path = root.parent / f"aegis-{name}"
        if path.exists():
            typer.echo(f"Error: {path} already exists")
            raise typer.Exit(1)
        typer.echo(f"Creating worktree '{name}' at {path} on branch '{target_branch}'...")
        subprocess.run(["git", "worktree", "add", "-b", target_branch, str(path), "main"], cwd=root, check=True)
        _init_environment(path, name)
        typer.echo(f"✓ Worktree '{name}' created")

    elif action == "remove":
        if not name:
            typer.echo("Error: worktree name required for remove")
            raise typer.Exit(1)
        path = root.parent / f"aegis-{name}"
        if not path.exists():
            typer.echo(f"Error: {path} does not exist")
            raise typer.Exit(1)
        subprocess.run(["git", "worktree", "remove", str(path)], cwd=root, check=True)
        typer.echo(f"✓ Worktree '{name}' removed")

    elif action == "sync":
        typer.echo("Syncing all worktrees...")
        result = subprocess.run(
            ["git", "worktree", "list", "--porcelain"], cwd=root, capture_output=True, text=True
        )
        worktrees = []
        current = {}
        for line in result.stdout.split("\n"):
            if line.startswith("worktree "):
                if current:
                    worktrees.append(current)
                current = {"path": line.split(" ", 1)[1]}
            elif line.startswith("branch "):
                current["branch"] = line.split(" ", 1)[1]
        if current:
            worktrees.append(current)

        for wt in worktrees:
            typer.echo(f"  Syncing {wt['path']} ({wt.get('branch', 'detached')})...")
            subprocess.run(["git", "-C", wt["path"], "pull", "origin", wt.get("branch", "main")], check=False)
        typer.echo("✓ All worktrees synced")

    else:
        typer.echo(f"Unknown action: {action}. Use: list, create, remove, sync")
        raise typer.Exit(1)


# ============================================
# Test Data Population
# ============================================

import json
import random
from datetime import datetime, timezone, timedelta
from uuid import uuid4

from redis.asyncio import Redis
from aegis.schemas.message import AegisMessage, MessageType, Priority


@app.command("populate-test-data")
def populate_test_data(
    days: Annotated[int, typer.Option("--days", "-d", help="Days of historical data")] = 7,
    messages_per_day: Annotated[int, typer.Option("--msgs-per-day", help="Messages per day per stream")] = 100,
    clear_first: Annotated[bool, typer.Option("--clear", help="Clear existing test data first")] = True,
) -> None:
    """Populate test environment with sample observability data."""
    root = get_aegis_root()
    test_dir = root.parent / "aegis-test"

    if not test_dir.exists():
        typer.echo("Error: Test worktree not found. Run 'setup-envs' first.")
        raise typer.Exit(1)

    typer.echo("═" * 60)
    typer.echo(f"  POPULATING TEST DATA ({days} days, {messages_per_day} msgs/day/stream)")
    typer.echo("═" * 60)

    # Run the async population
    asyncio.run(_populate_test_data_async(test_dir, days, messages_per_day, clear_first))


async def _populate_test_data_async(test_dir: Path, days: int, msgs_per_day: int, clear_first: bool) -> None:
    """Async implementation of test data population."""
    # Add test directory to path
    import sys
    sys.path.insert(0, str(test_dir))

    redis = Redis(decode_responses=True)

    try:
        if clear_first:
            typer.echo("\n[1/4] Clearing existing test data...")
            await _clear_test_redis(redis)

        typer.echo("\n[2/4] Creating streams and consumer groups...")
        await _create_test_streams(redis)

        typer.echo("\n[3/4] Generating messages...")
        await _generate_test_messages(redis, days, msgs_per_day)

        typer.echo("\n[4/4] Creating historical aggregates...")
        await _create_historical_aggregates(redis, days)

        typer.echo("\n" + "═" * 60)
        typer.echo("  TEST DATA POPULATION COMPLETE")
        typer.echo("═" * 60)

    finally:
        await redis.aclose()


async def _clear_test_redis(redis: Redis) -> None:
    """Clear all aegis:* keys from Redis."""
    keys = []
    async for key in redis.scan_iter(match="aegis:*"):
        keys.append(key)
    if keys:
        await redis.delete(*keys)
        typer.echo(f"  ✓ Cleared {len(keys)} Redis keys")
    else:
        typer.echo("  No keys to clear")


async def _create_test_streams(redis: Redis) -> None:
    """Create test streams and consumer groups."""
    agents = [
        ("warden", "Security & Access Control"),
        ("torchestrator", "Task Orchestration"),
        ("lexicon", "Context & Knowledge"),
        ("janus", "Policy Evaluation"),
        ("observer", "Health & Monitoring"),
    ]

    for agent_id, _ in agents:
        stream = f"aegis:stream:{agent_id}"
        group = f"aegis:group:{agent_id}"

        # Create stream with initial entry
        await redis.xadd(stream, {"data": '{"init": true}'}, maxlen=10000)

        # Create consumer group
        try:
            await redis.xgroup_create(stream, group, id="0", mkstream=True)
        except Exception:
            pass  # Group may exist

        typer.echo(f"  ✓ Stream: {stream}")

    # Broadcast stream
    await redis.xadd("aegis:stream:broadcast", {"data": '{"init": true}'})
    try:
        await redis.xgroup_create("aegis:stream:broadcast", "aegis:group:broadcast:test", id="0", mkstream=True)
    except Exception:
        pass
    typer.echo("  ✓ Stream: aegis:stream:broadcast")


async def _generate_test_messages(redis: Redis, days: int, msgs_per_day: int) -> None:
    """Generate realistic test messages."""
    agents = ["warden", "torchestrator", "lexicon", "janus", "observer"]
    message_types = [MessageType.REQUEST, MessageType.RESPONSE, MessageType.EVENT, MessageType.ERROR]
    priorities = [Priority.LOW, Priority.NORMAL, Priority.HIGH, Priority.CRITICAL]
    actions = [
        "authorize", "execute_task", "retrieve_context", "evaluate_policy",
        "health_check", "store_memory", "query_memory", "schedule_job",
        "handle_event", "process_request", "validate_token", "audit_access"
    ]

    now = datetime.now(timezone.utc)
    total_messages = 0

    for day in range(days):
        day_start = now - timedelta(days=days - day)
        day_messages = 0

        for _ in range(msgs_per_day):
            # Random time within the day
            msg_time = day_start + timedelta(
                seconds=random.randint(0, 86399)
            )
            timestamp_ms = int(msg_time.timestamp() * 1000)

            source = random.choice(agents)
            target = random.choice([a for a in agents if a != source] + ["broadcast"])
            msg_type = random.choice(message_types)
            priority = random.choice(priorities)
            action = random.choice(actions)

            # Create correlation chain for request/response pairs
            correlation_id = str(uuid4()) if msg_type == MessageType.REQUEST else None

            # Token usage (realistic for LLM calls)
            if msg_type in (MessageType.REQUEST, MessageType.RESPONSE):
                prompt_tokens = random.randint(50, 2000)
                completion_tokens = random.randint(20, 1500)
                total_tokens = prompt_tokens + completion_tokens
            else:
                prompt_tokens = completion_tokens = total_tokens = 0

            message = AegisMessage(
                message_id=str(uuid4()),
                correlation_id=correlation_id,
                source_agent=source,
                target_agent=target,
                message_type=msg_type,
                tenant_id="test-tenant",
                user_id=f"test-user-{random.randint(1, 10)}",
                action=action,
                payload={
                    "task_id": f"task-{uuid4().hex[:8]}",
                    "params": {"key": "value"},
                    "token_usage": {
                        "prompt_tokens": prompt_tokens,
                        "completion_tokens": completion_tokens,
                        "total_tokens": total_tokens,
                    } if total_tokens > 0 else None,
                },
                priority=priority,
                timestamp=msg_time,
                ttl_seconds=300,
                metadata={
                    "trace_id": f"trace-{uuid4().hex[:16]}",
                    "span_id": f"span-{uuid4().hex[:8]}",
                },
            )

            stream = f"aegis:stream:{target}" if target != "broadcast" else "aegis:stream:broadcast"

            # Add to stream with auto-generated ID (using * to avoid conflicts)
            await redis.xadd(
                stream,
                {"data": message.model_dump_json()},
                id="*",
                maxlen=10000,
            )

            # Also add some to pending (for consumer group visualization)
            if msg_type == MessageType.REQUEST and random.random() < 0.3:
                group = f"aegis:group:{target}" if target != "broadcast" else "aegis:group:broadcast:test"
                # Message stays in pending (not acknowledged)

            day_messages += 1
            total_messages += 1

        typer.echo(f"  Day {day + 1}/{days}: {day_messages} messages")

    typer.echo(f"  ✓ Generated {total_messages} total messages")


async def _create_historical_aggregates(redis: Redis, days: int) -> None:
    """Create historical data for cumulative charts (stored in observability.db)."""
    # This would populate the SQLite observability database
    # For now, the archiver will generate this when it runs
    typer.echo("  ✓ Historical aggregates will be generated by archiver on first run")


# ============================================
# Reset Test Data
# ============================================

@app.command("reset-test-data")
def reset_test_data() -> None:
    """Reset only test environment data."""
    root = get_aegis_root()
    test_dir = root.parent / "aegis-test"

    if not test_dir.exists():
        typer.echo("Error: Test worktree not found")
        raise typer.Exit(1)

    typer.echo("Resetting test environment data...")

    # Clear Redis
    import subprocess
    result = subprocess.run(
        ["redis-cli", "--scan", "--pattern", "aegis:*"],
        capture_output=True, text=True, timeout=10
    )
    if result.returncode == 0 and result.stdout.strip():
        keys = result.stdout.strip().split("\n")
        if keys and keys[0]:
            subprocess.run(["redis-cli", "DEL"] + keys, timeout=10)
            typer.echo(f"  ✓ Deleted {len(keys)} Redis keys")

    # Clear observability DB
    obs_db = test_dir / "data" / "observability.db"
    if obs_db.exists():
        obs_db.unlink()
        typer.echo(f"  ✓ Removed {obs_db}")

    # Clear aegis_data
    data_dir = test_dir / "aegis_data"
    if data_dir.exists():
        shutil.rmtree(data_dir)
        typer.echo(f"  ✓ Removed {data_dir}")

    typer.echo("  ✓ Test data reset complete")


# ============================================
# Dev Server with Hot Reload
# ============================================

@app.command("start-dev")
def start_dev(
    port: Annotated[int, typer.Option("--port", "-p", help="Port to run on")] = 8420,
    host: Annotated[str, typer.Option("--host", help="Host to bind")] = "0.0.0.0",
    reload: Annotated[bool, typer.Option("--reload/--no-reload", help="Enable hot reload")] = True,
) -> None:
    """Start development server with hot reload."""
    import os
    os.chdir(get_aegis_root())

    typer.echo(f"Starting dev server on {host}:{port}...")

    cmd = ["uv", "run", "aegis-web"]
    if reload:
        cmd.extend(["--reload", "--reload-dir", "aegis"])
    cmd.extend(["--host", host, "--port", str(port)])

    try:
        subprocess.run(cmd, check=True)
    except KeyboardInterrupt:
        typer.echo("\n✓ Dev server stopped")
    except subprocess.CalledProcessError as e:
        typer.echo(f"✗ Dev server failed: {e}")
        raise typer.Exit(1)


# ============================================
# Production Commands
# ============================================

@app.command("build-prod")
def build_prod() -> None:
    """Build optimized production package."""
    root = get_aegis_root()
    typer.echo("Building production package...")
    # Add build steps here (compile, minify, etc.)
    typer.echo("  ✓ Production build ready (placeholder)")


@app.command("deploy-prod")
def deploy_prod(
    target: Annotated[str, typer.Option("--target", help="Deployment target")] = "local",
) -> None:
    """Deploy to production."""
    typer.echo(f"Deploying to {target}...")
    # Add deployment logic (docker, systemd, k8s, etc.)
    typer.echo("  ✓ Deployment complete (placeholder)")


@app.command("health-check")
def health_check(
    env: Annotated[str, typer.Option("--env", help="Environment to check")] = "prod",
) -> None:
    """Check environment health."""
    root = get_aegis_root()
    env_dir = root.parent / f"aegis-{env}"

    if not env_dir.exists():
        typer.echo(f"Error: {env} environment not found")
        raise typer.Exit(1)

    typer.echo(f"Checking {env} health...")
    # Add health checks (Redis, API, DB, etc.)
    typer.echo("  ✓ Health check passed (placeholder)")


@app.command("rollback-prod")
def rollback_prod() -> None:
    """Rollback production to previous version."""
    typer.echo("Rolling back production...")
    # Add rollback logic
    typer.echo("  ✓ Rollback complete (placeholder)")


# ============================================
# GitHub Pages / Documentation
# ============================================

@app.command("build-docs")
def build_docs() -> None:
    """Build documentation for GitHub Pages."""
    root = get_aegis_root()
    docs_dir = root / "doc"
    output_dir = root / "docs"  # GitHub Pages expects /docs or / (root)

    if not docs_dir.exists():
        typer.echo("Error: doc/ directory not found")
        raise typer.Exit(1)

    typer.echo("Building documentation...")

    # Copy docs to output directory
    if output_dir.exists():
        shutil.rmtree(output_dir)
    shutil.copytree(docs_dir, output_dir)

    # Create index.html redirect
    index_html = output_dir / "index.html"
    index_html.write_text("""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Aegis Documentation</title>
    <meta http-equiv="refresh" content="0; url=ENVIRONMENT_MANAGEMENT.html">
</head>
<body>
    <p>Redirecting to <a href="ENVIRONMENT_MANAGEMENT.html">Documentation</a>...</p>
</body>
</html>""")

    # Create _config.yml for Jekyll (GitHub Pages)
    config_yml = output_dir / "_config.yml"
    config_yml.write_text("""title: Aegis Documentation
description: Multi-Agent System Development Guide
theme: minima
markdown: kramdown
plugins:
  - jekyll-relative-links
relative_links:
  enabled: true
  collections: true
""")

    # Create .nojekyll to disable Jekyll processing (optional)
    (output_dir / ".nojekyll").write_text("")

    typer.echo(f"✓ Documentation built in {output_dir}")
    typer.echo("  Push to GitHub and enable Pages from /docs folder")


@app.command("serve-docs")
def serve_docs(
    port: Annotated[int, typer.Option("--port", "-p", help="Port to serve on")] = 8421,
) -> None:
    """Serve documentation locally for preview."""
    root = get_aegis_root()
    docs_dir = root / "docs"

    if not docs_dir.exists():
        typer.echo("Run 'build-docs' first")
        raise typer.Exit(1)

    typer.echo(f"Serving docs on http://localhost:{port}")
    import http.server
    import socketserver

    os.chdir(docs_dir)
    handler = http.server.SimpleHTTPRequestHandler
    with socketserver.TCPServer(("", port), handler) as httpd:
        typer.echo(f"Serving at http://localhost:{port}")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            typer.echo("\n✓ Doc server stopped")


if __name__ == "__main__":
    app()