#!/usr/bin/env python3
# scripts/aegis_shutdown.py
"""
Aegis System Shutdown Script
=============================
Gracefully stops the entire Aegis system.

Implements: Chunk-013 Spec — Part 3: Shutdown Script (with web server lifecycle addendum)

Usage:
    python scripts/aegis_shutdown.py [--keep-redis] [--keep-web] [--force] [--timeout SECONDS]

Sequence:
    1. Verify system is running
    2. Stop Mission Control web server (drain connections, then kill)
    3. Send graceful shutdown signal to System Manager
       (reverse-order agent teardown:
        TOrchestrator -> Forge -> Oracle -> Janus -> Lexicon -> Identity -> Warden -> Observer)
    4. Wait for System Manager process to exit
    5. Stop Redis (unless --keep-redis)
    6. Cleanup PID files
    7. Report final status
"""

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts._launcher_common import (
    resolve_config,
    LauncherLogger,
    LauncherConfig,
    is_redis_running,
    is_aegis_running,
    is_web_server_running,
    read_pid,
    remove_pid,
    wait_for_condition,
    find_executable,
)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for the shutdown script."""
    parser = argparse.ArgumentParser(description="Shutdown the Aegis system")
    parser.add_argument(
        "--keep-redis",
        action="store_true",
        help="Leave Redis running after Aegis stops",
    )
    parser.add_argument(
        "--keep-web",
        action="store_true",
        help="Leave web server running (for rolling agent restarts)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force kill if graceful shutdown times out",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=15,
        help="Seconds to wait for graceful shutdown (default: 15)",
    )
    return parser.parse_args()


class AegisShutdown:
    """
    Orchestrates the full shutdown sequence.

    Stops web server first (prevents new requests during teardown),
    then signals the System Manager for reverse-order agent shutdown,
    then stops Redis. Idempotent: safe to run when already stopped.
    """

    def __init__(self, config: LauncherConfig, logger: LauncherLogger, args: argparse.Namespace):
        self.config = config
        self.logger = logger
        self.args = args

    def run(self) -> int:
        """
        Execute shutdown sequence.

        Returns:
            Exit code (0=success, 1=failure, 130=interrupted).
        """
        try:
            aegis_running = is_aegis_running(self.config)
            web_running = is_web_server_running(self.config)
            redis_running = is_redis_running(self.config)

            # Idempotent: nothing to do
            if not aegis_running and not web_running:
                self.logger.info("Aegis is not currently running.")
                if not self.args.keep_redis and redis_running:
                    self.logger.info("Stopping orphaned Redis instance...")
                    self._stop_redis()
                self._cleanup_stale_pids()
                return 0

            total_steps = 5

            # Step 1: Stop Mission Control web server FIRST
            # Rationale: Prevent new inbound requests during agent teardown
            if web_running and not self.args.keep_web:
                self.logger.step(1, total_steps, "Stopping Mission Control web server")
                self._stop_web_server()
            elif self.args.keep_web and web_running:
                self.logger.step(1, total_steps, "Web server left running (--keep-web)")
            else:
                self.logger.step(1, total_steps, "Web server not running -- skipping")

            # Step 2: Signal System Manager to shutdown
            self.logger.step(2, total_steps, "Sending shutdown signal to System Manager")
            sm_pid_file = self.config.pid_dir / "aegis_system_manager.pid"
            sm_pid = read_pid(sm_pid_file)
            if sm_pid:
                self._signal_graceful_shutdown(sm_pid)
            else:
                self.logger.warn("No System Manager PID found. May already be stopped.")

            # Step 3: Wait for System Manager to exit
            self.logger.step(
                3, total_steps,
                f"Waiting for graceful shutdown (timeout: {self.args.timeout}s)",
            )

            if sm_pid:
                exited = wait_for_condition(
                    lambda: not is_aegis_running(self.config),
                    timeout=self.args.timeout,
                    description="System Manager exit",
                )

                if not exited:
                    if self.args.force:
                        self.logger.warn("Graceful shutdown timed out. Force killing...")
                        self._force_kill(sm_pid)
                    else:
                        self.logger.error(
                            f"Shutdown timed out after {self.args.timeout}s. "
                            "Use --force to kill, or increase --timeout."
                        )
                        return 1
                else:
                    self.logger.success("System Manager stopped gracefully.")

            # Step 4: Stop Redis
            if not self.args.keep_redis:
                self.logger.step(4, total_steps, "Stopping Redis")
                self._stop_redis()
            else:
                self.logger.step(4, total_steps, "Redis left running (--keep-redis)")

            # Step 5: Cleanup
            self.logger.step(5, total_steps, "Cleaning up PID files")
            self._cleanup_stale_pids()

            self.logger.success("Aegis system fully stopped.")
            return 0

        except KeyboardInterrupt:
            self.logger.warn("Shutdown interrupted. System may be in partial state.")
            return 130
        except Exception as e:
            self.logger.error(f"Unexpected error during shutdown: {e}")
            return 1

    def _signal_graceful_shutdown(self, pid: int) -> None:
        """Send graceful shutdown signal (cross-platform)."""
        try:
            if sys.platform == "win32":
                os.kill(pid, signal.CTRL_BREAK_EVENT)
            else:
                os.kill(pid, signal.SIGTERM)
            self.logger.info(f"Sent shutdown signal to System Manager (PID: {pid})")
        except ProcessLookupError:
            self.logger.warn(f"Process {pid} not found. Already stopped.")
        except (PermissionError, OSError) as e:
            self.logger.error(f"Failed to signal PID {pid}: {e}")

    def _force_kill(self, pid: int) -> None:
        """Force kill as last resort (cross-platform)."""
        self._force_kill_pid(pid)
        time.sleep(0.5)
        remove_pid(self.config.pid_dir / "aegis_system_manager.pid")

    def _stop_web_server(self) -> None:
        """
        Gracefully stop the Mission Control web server.

        Windows strategy:
          1. Send CTRL_BREAK_EVENT (graceful — uvicorn handles this)
          2. Wait up to 5s for process to exit and port to free
          3. If still alive, TerminateProcess as last resort
          4. Wait for port release after hard kill
          5. Remove PID file
        """
        web_pid_file = self.config.pid_dir / "aegis_web.pid"
        web_pid = read_pid(web_pid_file)
        if web_pid is None:
            remove_pid(web_pid_file)
            return

        # Phase 1: Graceful signal
        try:
            if sys.platform == "win32":
                # CTRL_BREAK_EVENT works because boot used start_new_session=True
                # (which sets CREATE_NEW_PROCESS_GROUP on Windows)
                os.kill(web_pid, signal.CTRL_BREAK_EVENT)
                self.logger.info(f"Sent CTRL_BREAK to web server (PID: {web_pid})")
            else:
                os.kill(web_pid, signal.SIGTERM)
                self.logger.info(f"Sent SIGTERM to web server (PID: {web_pid})")
        except ProcessLookupError:
            remove_pid(web_pid_file)
            return
        except OSError as e:
            self.logger.warn(f"Signal to web server failed: {e}. Trying hard kill.")
            self._force_kill_pid(web_pid)
            remove_pid(web_pid_file)
            return

        # Phase 2: Wait for process to exit
        exited = wait_for_condition(
            lambda: read_pid(web_pid_file) is None,
            timeout=5.0,
            interval=0.25,
            description="Web server exit",
        )

        if not exited:
            # Phase 3: Hard kill
            self.logger.warn("Graceful shutdown timed out. Force killing web server.")
            self._force_kill_pid(web_pid)

        # Phase 4: Wait for port to be released (Windows needs this)
        if sys.platform == "win32":
            port_free = wait_for_condition(
                lambda: is_port_available(self.config.web_host, self.config.web_port),
                timeout=3.0,
                interval=0.25,
                description="Port release",
            )
            if not port_free:
                self.logger.warn(
                    f"Port {self.config.web_port} still in use after kill. "
                    "May need manual cleanup."
                )

        remove_pid(web_pid_file)
        self.logger.success("Mission Control web server stopped.")


    def _force_kill_pid(self, pid: int) -> None:
        """Cross-platform force kill a single PID."""
        try:
            if sys.platform == "win32":
                # taskkill /F /T kills the process tree (children too)
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(pid)],
                    capture_output=True,
                    timeout=5,
                )
            else:
                os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, OSError, subprocess.TimeoutExpired):
            pass

    def _stop_redis(self) -> None:
        """
        Stop Redis via redis-cli shutdown or PID signal fallback.

        Prefers redis-cli shutdown (graceful, triggers RDB save option).
        Falls back to SIGTERM on the Redis PID if redis-cli is unavailable.
        """
        if not is_redis_running(self.config):
            self.logger.info("Redis is not running.")
            remove_pid(self.config.pid_dir / "redis.pid")
            return

        # Prefer redis-cli shutdown (graceful)
        redis_cli = find_executable("redis-cli")
        if redis_cli:
            try:
                result = subprocess.run(
                    [
                        str(redis_cli),
                        "-h", self.config.redis_host,
                        "-p", str(self.config.redis_port),
                        "shutdown", "nosave",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                # redis-cli shutdown returns empty on success
                time.sleep(0.5)
                if not is_redis_running(self.config):
                    remove_pid(self.config.pid_dir / "redis.pid")
                    self.logger.success("Redis stopped via redis-cli.")
                    return
            except Exception:
                pass

        # Fallback: kill by PID
        redis_pid = read_pid(self.config.pid_dir / "redis.pid")
        if redis_pid:
            try:
                os.kill(redis_pid, signal.SIGTERM)
                time.sleep(1.0)
            except ProcessLookupError:
                pass

        remove_pid(self.config.pid_dir / "redis.pid")
        self.logger.success("Redis stopped.")

    def _cleanup_stale_pids(self) -> None:
        """Remove all PID files in pid_dir that reference dead processes."""
        if not self.config.pid_dir.exists():
            return

        for pid_file in self.config.pid_dir.glob("*.pid"):
            pid = read_pid(pid_file)
            if pid is None:
                # Process is dead or file is invalid -- remove
                remove_pid(pid_file)


if __name__ == "__main__":
    args = parse_args()
    config = resolve_config()
    logger = LauncherLogger(config.logs_dir / "aegis_launcher.log")

    shutdown = AegisShutdown(config, logger, args)
    exit_code = shutdown.run()
    logger.close()
    sys.exit(exit_code)
