# aegis/manager/system_manager.py
# Implements: Part III §3.3 — System Manager
"""
Aegis System Manager.

The top-level lifecycle controller for the entire Aegis system.
Responsibilities:
    1. Ordered startup:  Redis → Observer → Warden → Identity → Lexicon
                         → Janus → Oracle → Forge → TOrchestrator
    2. Graceful shutdown: Reverse startup order.
    3. Health-check polling with configurable intervals.
    4. Automatic restart of failed agents (with backoff & retry limits).
    5. Scheduler service management (APScheduler integration).

Entry point: ``python -m aegis.main``

Reference: Part III §3.3, Part XI §11.1
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import structlog

from aegis.manager.agent_registry import (
    AGENT_REGISTRY,
    AgentEntry,
    get_shutdown_order,
    get_startup_order,
)
from aegis.manager.scheduler import AegisScheduler

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Configuration Defaults
# ---------------------------------------------------------------------------

DEFAULT_CONFIG = {
    "redis": {
        "host": "localhost",
        "port": 6379,
        "db": 0,
    },
    "system_manager": {
        "health_check_interval_seconds": 30,
        "restart_max_retries": 3,
        "restart_backoff_base_seconds": 2.0,
        "restart_backoff_max_seconds": 60.0,
        "startup_timeout_seconds": 30,
        "shutdown_timeout_seconds": 15,
    },
    "scheduler": {
        "enabled": True,
        "job_store_path": "aegis_data/scheduler_jobs.db",
    },
}


def _load_config(config_path: str = "aegis_config.yaml") -> Dict[str, Any]:
    """
    Load system configuration from aegis_config.yaml.

    Falls back to DEFAULT_CONFIG if file is missing.
    Env vars override: AEGIS_REDIS_HOST, AEGIS_REDIS_PORT, etc.
    Precedence: CLI > ENV > YAML > defaults  (RT-2)
    """
    config = dict(DEFAULT_CONFIG)

    if os.path.exists(config_path):
        try:
            import yaml

            with open(config_path, "r") as f:
                file_config = yaml.safe_load(f) or {}
            _deep_merge(config, file_config)
            logger.info("Loaded config from %s", config_path)
        except ImportError:
            logger.warning(
                "PyYAML not installed — using default config. "
                "Install with: pip install pyyaml"
            )
        except Exception as exc:
            logger.warning("Failed to load %s: %s — using defaults", config_path, exc)

    # Env var overrides
    env_overrides = {
        "AEGIS_REDIS_HOST": ("redis", "host"),
        "AEGIS_REDIS_PORT": ("redis", "port"),
        "AEGIS_REDIS_DB": ("redis", "db"),
        "AEGIS_HEALTH_INTERVAL": ("system_manager", "health_check_interval_seconds"),
        "AEGIS_SCHEDULER_ENABLED": ("scheduler", "enabled"),
        "AEGIS_SCHEDULER_DB": ("scheduler", "job_store_path"),
    }
    for env_key, path in env_overrides.items():
        val = os.environ.get(env_key)
        if val is not None:
            section = config.setdefault(path[0], {})
            # Type coercion
            if path[1] in ("port", "db", "health_check_interval_seconds"):
                val = int(val)
            elif path[1] == "enabled":
                val = val.lower() in ("true", "1", "yes")
            section[path[1]] = val

    return config


def _deep_merge(base: dict, override: dict) -> None:
    """Recursively merge override into base."""
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


# ---------------------------------------------------------------------------
# Agent Health State
# ---------------------------------------------------------------------------

class AgentState:
    """Runtime state tracker for a single managed agent."""

    def __init__(self, entry: AgentEntry) -> None:
        self.entry = entry
        self.instance: Optional[Any] = None
        self.task: Optional[asyncio.Task] = None
        self.status: str = "stopped"  # stopped | starting | running | failed | restarting
        self.restart_count: int = 0
        self.last_heartbeat: Optional[datetime] = None
        self.error: Optional[str] = None

    def reset(self) -> None:
        self.status = "stopped"
        self.restart_count = 0
        self.error = None
        self.instance = None
        self.task = None


# ---------------------------------------------------------------------------
# System Manager
# ---------------------------------------------------------------------------

class SystemManager:
    """
    Orchestrates the full lifecycle of the Aegis system.

    Usage::

        manager = SystemManager()
        await manager.run()  # Blocks until shutdown signal

    Or for programmatic control::

        manager = SystemManager()
        await manager.start()
        # ... system is running ...
        await manager.stop()
    """

    def __init__(
        self,
        config_path: str = "aegis_config.yaml",
        config_override: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._config = _load_config(config_path)
        if config_override:
            _deep_merge(self._config, config_override)

        self._sm_config = self._config.get("system_manager", DEFAULT_CONFIG["system_manager"])
        self._redis_config = self._config.get("redis", DEFAULT_CONFIG["redis"])
        self._sched_config = self._config.get("scheduler", DEFAULT_CONFIG["scheduler"])

        self._agents: Dict[str, AgentState] = {}
        self._scheduler: Optional[AegisScheduler] = None
        self._redis_conn: Optional[Any] = None
        self._health_task: Optional[asyncio.Task] = None
        self._shutdown_event = asyncio.Event()
        self._running = False

        # Initialize agent states from registry
        for entry in AGENT_REGISTRY:
            self._agents[entry.agent_id] = AgentState(entry)

    # -- Properties ----------------------------------------------------------

    @property
    def config(self) -> Dict[str, Any]:
        return dict(self._config)

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def scheduler(self) -> Optional[AegisScheduler]:
        return self._scheduler

    # -- Main Entry Point ----------------------------------------------------

    async def run(self) -> None:
        """
        Start the system and block until a shutdown signal is received.

        This is the primary entry point for ``python -m aegis.main``.
        """
        # Register signal handlers
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self._handle_signal, sig)
            except NotImplementedError:
                # Windows doesn't support add_signal_handler
                pass

        try:
            await self.start()
            logger.info("Aegis system is running. Press Ctrl+C to stop.")
            await self._shutdown_event.wait()
        except KeyboardInterrupt:
            logger.info("KeyboardInterrupt received")
        finally:
            await self.stop()

    def _handle_signal(self, sig: signal.Signals) -> None:
        """Signal handler to initiate graceful shutdown."""
        logger.info("Received signal %s — initiating graceful shutdown", sig.name)
        self._shutdown_event.set()

    # -- Startup Sequence ----------------------------------------------------

    async def start(self) -> None:
        """
        Execute the full startup sequence.

        Order: Redis → Scheduler → Agents (by priority)

        Implements: Part III §3.3 — ordered startup
        """
        logger.info("=" * 60)
        logger.info("  AEGIS SYSTEM MANAGER — STARTUP SEQUENCE")
        logger.info("=" * 60)

        # Step 1: Verify Redis connectivity
        await self._verify_redis()

        # Step 2: Start Scheduler (if enabled)
        if self._sched_config.get("enabled", True):
            await self._start_scheduler()

        # Step 3: Start agents in priority order
        for entry in get_startup_order():
            state = self._agents.get(entry.agent_id)
            if state is None:
                continue
            await self._start_agent(state)

        # Step 4: Start health check loop
        self._health_task = asyncio.create_task(
            self._health_check_loop(),
            name="system-manager-health-check",
        )

        self._running = True
        logger.info("=" * 60)
        logger.info("  AEGIS SYSTEM — ALL AGENTS ONLINE")
        logger.info("=" * 60)

        # Step 5: First-run bootstrap check
        await self._check_first_run()

    async def _verify_redis(self) -> None:
        """
        Verify Redis connectivity before launching any agents.

        Implements: Part III §3.1 — Startup verification
        """
        logger.info("[Redis] Verifying connectivity...")
        try:
            import redis.asyncio as aioredis

            host = self._redis_config.get("host", "localhost")
            port = self._redis_config.get("port", 6379)
            db = self._redis_config.get("db", 0)

            self._redis_conn = aioredis.Redis(host=host, port=port, db=db)
            pong = await self._redis_conn.ping()
            if pong:
                logger.info("[Redis] Connected to %s:%s (db=%s)", host, port, db)
            else:
                raise ConnectionError("Redis PING returned False")
        except ImportError:
            logger.error(
                "[Redis] redis.asyncio not installed. "
                "Install with: pip install redis"
            )
            raise SystemExit(1)
        except Exception as exc:
            logger.error(
                "[Redis] Failed to connect: %s. "
                "Ensure redis-server is running.",
                exc,
            )
            raise SystemExit(1)

    async def _start_scheduler(self) -> None:
        """Initialize and start the Aegis Scheduler service."""
        logger.info("[Scheduler] Starting...")
        db_path = self._sched_config.get(
            "job_store_path", "aegis_data/scheduler_jobs.db"
        )

        # Create bus publisher that writes to Redis Streams
        async def bus_publisher(message: Dict[str, Any]) -> None:
            if self._redis_conn is None:
                raise RuntimeError("Redis not connected")
            target = message.get("target_agent", "torchestrator")
            stream_key = f"aegis:stream:{target}"
            await self._redis_conn.xadd(
                stream_key,
                {"data": json.dumps(message, default=str)},
            )

        self._scheduler = AegisScheduler(
            db_path=db_path,
            bus_publisher=bus_publisher,
        )
        await self._scheduler.start()
        logger.info("[Scheduler] Running (store=%s)", db_path)

    async def _start_agent(self, state: AgentState) -> None:
        """
        Start a single agent: import class → instantiate → call startup().
        """
        entry = state.entry
        log = logger.bind(agent_id=entry.agent_id)
        log.info("[%s] Starting...", entry.display_name)

        state.status = "starting"
        cls = entry.import_class()

        if cls is None:
            if entry.required:
                log.error(
                    "[%s] REQUIRED agent failed to import — system degraded",
                    entry.display_name,
                )
                state.status = "failed"
                state.error = "Import failed"
            else:
                log.warning(
                    "[%s] Optional agent not available — skipping",
                    entry.display_name,
                )
                state.status = "stopped"
            return

        try:
            # Instantiate the agent
            # Agents may accept config, redis_conn, etc.
            agent_config = self._config.get(entry.config_key, {}) if entry.config_key else {}
            try:
                instance = cls(
                    config=agent_config,
                    redis_conn=self._redis_conn,
                )
            except TypeError:
                # Fallback if agent doesn't accept these kwargs
                try:
                    instance = cls(config=agent_config)
                except TypeError:
                    instance = cls()

            state.instance = instance

            # Call startup with timeout
            timeout = self._sm_config.get("startup_timeout_seconds", 30)
            await asyncio.wait_for(instance.startup(), timeout=timeout)

            state.status = "running"
            state.last_heartbeat = datetime.now(timezone.utc)
            log.info("[%s] Started successfully", entry.display_name)

        except asyncio.TimeoutError:
            state.status = "failed"
            state.error = "Startup timed out"
            log.error(
                "[%s] Startup timed out after %ds",
                entry.display_name,
                self._sm_config.get("startup_timeout_seconds", 30),
            )
        except Exception as exc:
            state.status = "failed"
            state.error = str(exc)
            log.error("[%s] Startup failed: %s", entry.display_name, exc)

    # -- Shutdown Sequence ---------------------------------------------------

    async def stop(self) -> None:
        """
        Execute graceful shutdown in reverse startup order.

        Implements: Part III §3.3 — Graceful shutdown in reverse order
        """
        logger.info("=" * 60)
        logger.info("  AEGIS SYSTEM MANAGER — SHUTDOWN SEQUENCE")
        logger.info("=" * 60)

        self._running = False

        # Cancel health check
        if self._health_task and not self._health_task.done():
            self._health_task.cancel()
            try:
                await self._health_task
            except asyncio.CancelledError:
                pass

        # Stop agents in reverse order
        timeout = self._sm_config.get("shutdown_timeout_seconds", 15)
        for entry in get_shutdown_order():
            state = self._agents.get(entry.agent_id)
            if state is None or state.instance is None:
                continue
            await self._stop_agent(state, timeout=timeout)

        # Stop Scheduler
        if self._scheduler and self._scheduler.is_running:
            logger.info("[Scheduler] Stopping...")
            await self._scheduler.stop()
            logger.info("[Scheduler] Stopped")

        # Close Redis
        if self._redis_conn:
            logger.info("[Redis] Closing connection...")
            await self._redis_conn.close()
            self._redis_conn = None
            logger.info("[Redis] Connection closed")

        logger.info("=" * 60)
        logger.info("  AEGIS SYSTEM — SHUTDOWN COMPLETE")
        logger.info("=" * 60)

    async def _stop_agent(self, state: AgentState, timeout: int = 15) -> None:
        """Gracefully stop a single agent."""
        entry = state.entry
        log = logger.bind(agent_id=entry.agent_id)
        log.info("[%s] Stopping...", entry.display_name)

        try:
            if state.instance and hasattr(state.instance, "shutdown"):
                await asyncio.wait_for(state.instance.shutdown(), timeout=timeout)
            state.status = "stopped"
            log.info("[%s] Stopped", entry.display_name)
        except asyncio.TimeoutError:
            log.warning(
                "[%s] Shutdown timed out after %ds — forcing",
                entry.display_name,
                timeout,
            )
            state.status = "stopped"
        except Exception as exc:
            log.error("[%s] Error during shutdown: %s", entry.display_name, exc)
            state.status = "stopped"

    # -- Health Check Loop ---------------------------------------------------

    async def _health_check_loop(self) -> None:
        """
        Periodically poll agent health and restart failed agents.

        Implements: Part III §3.3 — Health-check polling, restart logic
        """
        interval = self._sm_config.get("health_check_interval_seconds", 30)
        logger.info("Health check loop started (interval=%ds)", interval)

        try:
            while self._running:
                await asyncio.sleep(interval)
                if not self._running:
                    break
                await self._run_health_checks()
        except asyncio.CancelledError:
            pass
        finally:
            logger.info("Health check loop stopped")

    async def _run_health_checks(self) -> None:
        """Execute one round of health checks across all agents."""
        for agent_id, state in self._agents.items():
            if state.status == "stopped" and not state.entry.required:
                continue  # Optional agents that aren't running

            if state.status == "running" and state.instance is not None:
                # Check if agent has a health_check method
                if hasattr(state.instance, "health_check"):
                    try:
                        healthy = await asyncio.wait_for(
                            state.instance.health_check(), timeout=10
                        )
                        if healthy:
                            state.last_heartbeat = datetime.now(timezone.utc)
                        else:
                            logger.warning(
                                "[HealthCheck] %s reported unhealthy",
                                state.entry.display_name,
                            )
                            state.status = "failed"
                            state.error = "Health check returned False"
                    except asyncio.TimeoutError:
                        logger.warning(
                            "[HealthCheck] %s health check timed out",
                            state.entry.display_name,
                        )
                        state.status = "failed"
                        state.error = "Health check timed out"
                    except Exception as exc:
                        logger.error(
                            "[HealthCheck] %s health check error: %s",
                            state.entry.display_name,
                            exc,
                        )
                        state.status = "failed"
                        state.error = str(exc)
                else:
                    # No health_check method — assume healthy if running
                    state.last_heartbeat = datetime.now(timezone.utc)

            # Attempt restart for failed agents
            if state.status == "failed":
                await self._attempt_restart(state)

    async def _attempt_restart(self, state: AgentState) -> None:
        """
        Attempt to restart a failed agent with exponential backoff.

        Implements: Part III §3.3 — Restart of failed agents
                    Part XIII RT-3, RT-4 — Observer/Warden restart priority
        """
        entry = state.entry
        max_retries = entry.restart_max or self._sm_config.get("restart_max_retries", 3)
        backoff_base = self._sm_config.get("restart_backoff_base_seconds", 2.0)
        backoff_max = self._sm_config.get("restart_backoff_max_seconds", 60.0)

        if state.restart_count >= max_retries:
            if entry.required:
                logger.critical(
                    "[Restart] REQUIRED agent '%s' exceeded %d restart attempts — "
                    "SYSTEM DEGRADED",
                    entry.display_name,
                    max_retries,
                )
            else:
                logger.error(
                    "[Restart] Optional agent '%s' exceeded %d restart attempts — "
                    "giving up",
                    entry.display_name,
                    max_retries,
                )
            return

        # Exponential backoff
        delay = min(backoff_base * (2 ** state.restart_count), backoff_max)
        state.restart_count += 1
        state.status = "restarting"

        logger.warning(
            "[Restart] Restarting '%s' (attempt %d/%d, backoff=%.1fs)",
            entry.display_name,
            state.restart_count,
            max_retries,
            delay,
        )

        await asyncio.sleep(delay)

        # Attempt clean shutdown first
        if state.instance and hasattr(state.instance, "shutdown"):
            try:
                await asyncio.wait_for(state.instance.shutdown(), timeout=5)
            except Exception:
                pass

        state.instance = None

        # Re-start
        await self._start_agent(state)

        if state.status == "running":
            logger.info(
                "[Restart] '%s' recovered after %d attempts",
                entry.display_name,
                state.restart_count,
            )

    # -- First-Run Bootstrap -------------------------------------------------

    async def _check_first_run(self) -> None:
        """
        Detect first-run condition and trigger bootstrap if needed.

        Implements: Part V §5.4 — Bootstrap / First-Run
        """
        identity_state = self._agents.get("identity")
        if identity_state is None or identity_state.instance is None:
            return

        if hasattr(identity_state.instance, "is_first_run"):
            try:
                is_first = await identity_state.instance.is_first_run()
                if is_first:
                    logger.info(
                        "=" * 60 + "\n"
                        "  FIRST RUN DETECTED — Bootstrap required.\n"
                        "  Use 'aegis user create --root' to create\n"
                        "  the initial root user and default tenant.\n"
                        + "=" * 60
                    )
            except Exception as exc:
                logger.debug("First-run check skipped: %s", exc)

    # -- Status & Introspection ----------------------------------------------

    def get_system_status(self) -> Dict[str, Any]:
        """
        Return a comprehensive status snapshot of the entire system.

        Used by CLI ``aegis status`` and Mission Control /health endpoint.
        """
        agent_statuses = {}
        for agent_id, state in self._agents.items():
            agent_statuses[agent_id] = {
                "display_name": state.entry.display_name,
                "status": state.status,
                "required": state.entry.required,
                "restart_count": state.restart_count,
                "last_heartbeat": (
                    state.last_heartbeat.isoformat() if state.last_heartbeat else None
                ),
                "error": state.error,
                "tags": state.entry.tags,
            }

        return {
            "system": {
                "running": self._running,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            "redis": {
                "connected": self._redis_conn is not None,
                "host": self._redis_config.get("host"),
                "port": self._redis_config.get("port"),
            },
            "scheduler": {
                "enabled": self._sched_config.get("enabled", True),
                "running": self._scheduler.is_running if self._scheduler else False,
            },
            "agents": agent_statuses,
        }

    def get_agent_status(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """Return status for a single agent."""
        state = self._agents.get(agent_id)
        if state is None:
            return None
        return {
            "agent_id": agent_id,
            "display_name": state.entry.display_name,
            "status": state.status,
            "required": state.entry.required,
            "restart_count": state.restart_count,
            "last_heartbeat": (
                state.last_heartbeat.isoformat() if state.last_heartbeat else None
            ),
            "error": state.error,
        }
