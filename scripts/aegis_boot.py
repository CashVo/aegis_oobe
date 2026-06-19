#!/usr/bin/env python3
# scripts/aegis_boot.py
"""
Aegis System Boot Script
========================
Starts the complete Aegis system from a cold state.

Implements: Chunk-013 Spec — Part 2: Boot Script

Usage:
    python scripts/aegis_boot.py [--skip-redis] [--skip-frx] [--headless] [--verbose]

Sequence:
    1. Detect first-run -> trigger FRX wizard if needed
    2. Load configuration & verify prerequisites
    3. Start Redis (if not already running and not --skip-redis)
    4. Verify Redis connectivity
    5. Launch Aegis System Manager (which boots all agents in order)
    6. Start Mission Control web server (unless --headless)
    7. Wait for full health confirmation (agents + web)
"""

import argparse
import subprocess
import sys
import os
import time
from pathlib import Path

# Ensure project root on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts._launcher_common import (
    resolve_config,
    LauncherLogger,
    LauncherConfig,
    ServiceState,
    is_redis_running,
    is_aegis_running,
    is_web_server_running,
    write_pid,
    read_pid,
    wait_for_condition,
    find_executable,
    is_port_available,
)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for the boot script."""
    parser = argparse.ArgumentParser(description="Boot the Aegis system")
    parser.add_argument(
        "--skip-redis",
        action="store_true",
        help="Assume Redis is externally managed",
    )
    parser.add_argument(
        "--skip-frx",
        action="store_true",
        help="Skip first-run experience (for CI/testing)",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Skip web server (CLI-only mode)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose output",
    )
    parser.add_argument(
        "--keep-streams",
        action="store_true",
        help="Preserve existing Redis streams (skip flush on boot)",
    )
    return parser.parse_args()

BANNER = r"""
    +=============================================+
    |           PROJECT AEGIS -- BOOT             |
    |                                             |
    |   Local-First AI Agent System               |
    |   Starting all services...                  |
    +=============================================+
"""


class AegisBoot:
    """
    Orchestrates the full system boot sequence.

    Handles first-run detection, prerequisite verification, Redis startup,
    System Manager launch, web server startup, and health confirmation.
    Idempotent: safe to run when system is already up (per RT-13-6).
    """

    def __init__(self, config: LauncherConfig, logger: LauncherLogger, args: argparse.Namespace):
        self.config = config
        self.logger = logger
        self.args = args
        self.total_steps = 8 if not args.headless else 7

    def run(self) -> int:
        """
        Execute boot sequence.

        Returns:
            Exit code (0=success, 1=failure, 130=interrupted).
        """
        
        # Check if we're running aegis outside of our sandbox venv
        venv_path = self.config.project_root / ".venv"
        if venv_path.exists() and str(venv_path) not in sys.prefix:
            self.logger.warn(
                f"Running outside project venv. Activate with:\n"
                f"    {venv_path / 'Scripts' / 'Activate.ps1'}"
            )
            return 1 # exit
    
        try:
            self._print_banner()

            # Pre-check: already running? (Idempotency per RT-13-6)
            if is_aegis_running(self.config):
                self.logger.info("Aegis is already running. Use aegis_restart.py to restart.")
                return 0

            # Step 1: First Run Detection
            step = 1
            from aegis.frx.wizard import should_run_frx, run_frx_wizard

            if not self.args.skip_frx and should_run_frx(self.config):
                self.logger.step(step, self.total_steps, "First run detected -- launching setup wizard")
                frx_success = run_frx_wizard(self.config, self.logger)
                if not frx_success:
                    self.logger.error("First run setup failed or was cancelled.")
                    return 1
            else:
                frx_msg = r"""First Run Experience (FRX)
    Configuration found -- skipping FRX. 
    NOTE: To execute the First Run Experience (FRX) again, delete the following:
        - .aegis_bootstrapped
        - aegis_config.yaml 
        - aegis_data/ directory or just the files within it
                """
                self.logger.step(step, self.total_steps, frx_msg)

            # Step 2: Verify prerequisites
            step = 2
            self.logger.step(step, self.total_steps, "Verifying prerequisites")
            from aegis.frx.checks import verify_prerequisites

            prereq_result = verify_prerequisites(self.config)
            if not prereq_result.all_passed:
                self._report_prereq_failures(prereq_result)
                return 1
            self.logger.success("All prerequisites satisfied.")

            # Step 3: Start Redis
            step = 3
            if not self.args.skip_redis:
                self.logger.step(step, self.total_steps, "Starting Redis")
                if not self._start_redis():
                    return 1
            else:
                self.logger.step(step, self.total_steps, "Redis management skipped (--skip-redis)")
                if not is_redis_running(self.config):
                    self.logger.error("Redis not reachable. Start it manually or remove --skip-redis.")
                    return 1

            # Step 4: Verify Redis connectivity
            step = 4
            self.logger.step(step, self.total_steps, "Verifying Redis connectivity")
            if not wait_for_condition(
                lambda: is_redis_running(self.config),
                timeout=10.0,
                description="Redis ready",
            ):
                self.logger.error("Redis did not become reachable within timeout.")
                return 1
            self.logger.success("Redis is responsive.")

            # Step 5: Flush stale streams (NEW)
            step = 5
            if not getattr(self.args, "keep_streams", False):
                self.logger.step(step, self.total_steps, "Flushing stale streams")
                if not self._flush_streams():
                    self.logger.warn("Stream flush failed — continuing with stale data.")
            else:
                self.logger.step(step, self.total_steps, "Stream flush skipped (--keep-streams)")
            
            # Small pause to ensure Redis processes the DEL commands fully
            time.sleep(0.5)

            # Step 6: Launch Aegis System Manager
            step = 6
            self.logger.step(step, self.total_steps, "Launching Aegis System Manager")
            if not self._start_system_manager():
                return 1

            # Step 7: Start Mission Control web server
            step = 7
            if not self.args.headless:
                self.logger.step(step, self.total_steps, "Starting Mission Control web server")
                if not self._start_web_server():
                    self.logger.warn(
                        "Web server failed to start. System is running headless (CLI-only)."
                    )
                    # Non-fatal: agents are up, web is a convenience layer
            else:
                self.logger.step(step, self.total_steps, "Headless mode -- skipping web server")

            # Step 8: Health confirmation
            final_step = 8
            self.logger.step(final_step, self.total_steps, "Waiting for full system health confirmation")
            if not self._wait_for_health():
                self.logger.warn("System started but health check incomplete. Check logs.")
                return 0  # Non-fatal -- system is running

            self._print_success()
            return 0

        except KeyboardInterrupt:
            self.logger.warn("Boot interrupted by user.")
            return 130
        except Exception as e:
            self.logger.error(f"Unexpected error during boot: {e}")
            if self.args.verbose:
                import traceback
                traceback.print_exc()
            return 1

    def _print_banner(self) -> None:
        """Print the Aegis boot banner."""
        print(BANNER)

    def _start_redis(self) -> bool:
        """
        Start redis-server as a background daemon.

        Checks if already running first (idempotent). Verifies port availability,
        locates the redis-server binary, spawns it with daemonize, and waits
        for connectivity.

        Returns:
            True if Redis is running after this call, False on failure.
        """

        # Check if already running (covers WSL, Docker, external)
        if is_redis_running(self.config):
            self.logger.info("Redis is already running (externally managed).")
            return True

        # Only try to start if binary is available
        redis_bin = find_executable("redis-server")
        if redis_bin is None:
            self.logger.error(
                "redis-server not found on PATH and Redis is not reachable.\n"
                "  Either install Redis locally, start it in WSL/Docker,\n"
                "  or use --skip-redis if it's already running."
            )
            return False

        # Check port availability
        if not is_port_available(self.config.redis_host, self.config.redis_port):
            self.logger.error(
                f"Port {self.config.redis_port} is already in use by a non-Redis process."
            )
            return False

        pid_file = self.config.pid_dir / "redis.pid"
        log_file = self.config.logs_dir / "redis.log"

        cmd = [
            str(redis_bin),
            "--daemonize", "yes",
            "--bind", self.config.redis_host,
            "--port", str(self.config.redis_port),
            "--pidfile", str(pid_file),
            "--logfile", str(log_file),
        ]

        if self.args.verbose:
            self.logger.info(f"Redis command: {' '.join(cmd)}")

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if result.returncode != 0:
                self.logger.error(f"Redis failed to start: {result.stderr.strip()}")
                return False
        except subprocess.TimeoutExpired:
            self.logger.error("Redis start command timed out.")
            return False
        except FileNotFoundError:
            self.logger.error(f"Could not execute: {redis_bin}")
            return False

        # Wait for Redis to be reachable
        if not wait_for_condition(
            lambda: is_redis_running(self.config),
            timeout=5.0,
            description="Redis startup",
        ):
            self.logger.error("Redis process started but is not responding.")
            return False

        self.logger.success(f"Redis started on {self.config.redis_host}:{self.config.redis_port}")
        return True

    def _start_system_manager(self) -> bool:
        """
        Launch the Aegis System Manager as a detached subprocess.

        The System Manager (aegis.main) handles ordered agent startup:
        Observer -> Warden -> Identity -> Lexicon -> Janus -> Oracle -> Forge -> TOrchestrator

        Writes PID to .pids/aegis_system_manager.pid.

        Returns:
            True if process launched successfully, False on failure.
        """
        python_bin = sys.executable
        log_file = self.config.logs_dir / "aegis_system.log"

        cmd = [
            python_bin, "-m", "aegis.main",
            "--config", str(self.config.config_path),
        ]

        if self.args.verbose:
            self.logger.info(f"System Manager command: {' '.join(cmd)}")

        try:
            with open(log_file, "a") as log_fh:
                proc = subprocess.Popen(
                    cmd,
                    stdout=log_fh,
                    stderr=subprocess.STDOUT,
                    cwd=str(self.config.project_root),
                    start_new_session=True,  # Detach from terminal
                )

            # Write PID
            write_pid(self.config.pid_dir / "aegis_system_manager.pid", proc.pid)

            # Give it a moment to fail fast if there's an immediate error
            time.sleep(1.0)

            # Check if it's still alive
            poll = proc.poll()
            if poll is not None:
                self.logger.error(
                    f"System Manager exited immediately with code {poll}. "
                    f"Check {log_file}"
                )
                return False

            self.logger.success(f"System Manager launched (PID: {proc.pid})")
            return True

        except Exception as e:
            self.logger.error(f"Failed to start System Manager: {e}")
            return False

    def _start_web_server(self) -> bool:
        """
        Launch Mission Control (uvicorn + FastAPI) as a background process.

        The web server depends on:
          - Redis (for real-time agent status via pub/sub)
          - System Manager (for health endpoint proxying)
          - TOrchestrator (for chat/session API endpoints)

        Writes PID to .pids/aegis_web.pid.
        Logs to logs/aegis_web.log.

        Returns:
            True if web server is running after this call, False on failure.
        """
        # Check if already running
        if is_web_server_running(self.config):
            self.logger.info("Mission Control web server is already running.")
            return True

        # Check port availability
        if not is_port_available(self.config.web_host, self.config.web_port):
            self.logger.error(
                f"Web port {self.config.web_port} is already in use. "
                "Change web.port in aegis_config.yaml or free the port."
            )
            return False

        python_bin = sys.executable
        log_file = self.config.logs_dir / "aegis_web.log"

        cmd = [
            python_bin, "-m", "uvicorn",
            "aegis.web.app:app",
            "--host", self.config.web_host,
            "--port", str(self.config.web_port),
            "--log-level", "warning",
            "--no-access-log",
        ]

        if self.args.verbose:
            self.logger.info(f"Web server command: {' '.join(cmd)}")

        try:
            with open(log_file, "a") as log_fh:
                proc = subprocess.Popen(
                    cmd,
                    stdout=log_fh,
                    stderr=subprocess.STDOUT,
                    cwd=str(self.config.project_root),
                    start_new_session=True,
                )

            write_pid(self.config.pid_dir / "aegis_web.pid", proc.pid)

            # Wait for process to stabilize
            time.sleep(2.0)

            poll = proc.poll()
            if poll is not None:
                self.logger.error(
                    f"Web server exited immediately with code {poll}. Check {log_file}"
                )
                return False

            # Wait for HTTP health response
            healthy = wait_for_condition(
                lambda: self._check_web_health(),
                timeout=10.0,
                interval=1.0,
                description="Web server ready",
            )

            if healthy:
                self.logger.success(
                    f"Mission Control started at http://{self.config.web_host}:{self.config.web_port}"
                )
            else:
                self.logger.warn(
                    "Web server process is alive but not responding on HTTP yet. "
                    "It may still be initializing."
                )

            return True

        except Exception as e:
            self.logger.error(f"Failed to start web server: {e}")
            return False

    def _check_web_health(self) -> bool:
        """Check if web server health endpoint responds with HTTP 200."""
        try:
            import httpx
            resp = httpx.get(
                f"http://{self.config.web_host}:{self.config.web_port}/health",
                timeout=1.0,
            )
            if resp.status_code == 200:
                data = resp.json()
                return data.get("ready", False)  # True for both "healthy" and "degraded"
            return False
        except Exception:
            return False

    def _wait_for_health(self) -> bool:
        """
        Poll until the System Manager process confirms full health.

        Uses process liveness as a proxy: if the SM is still running after
        boot_timeout_seconds, it has successfully brought up all agents.

        Returns:
            True if system is healthy within timeout.
        """
        for attempt in range(self.config.boot_timeout_seconds):
            try:
                if self._check_web_health():
                    return True
                time.sleep(1)
            except KeyboardInterrupt:
                # On Windows, subprocess signals can leak here
                # Retry instead of dying
                continue
        return False

    def _report_prereq_failures(self, result) -> None:
        """Pretty-print which prerequisites failed with fix instructions."""
        self.logger.error("Prerequisite check failed:")
        for check in result.critical_failures:
            self.logger.error(
                f"  x {check.name}: got {check.actual_value}, need {check.required_value}"
            )
            if check.fix_instruction:
                for line in check.fix_instruction.split("\n"):
                    self.logger.info(f"    -> {line}")

    def _print_success(self) -> None:
        """Print success message with access URLs."""
        print()
        self.logger.success("=== AEGIS SYSTEM ONLINE ===")
        print()
        self.logger.info(f"  Mission Control: http://{self.config.web_host}:{self.config.web_port}")
        self.logger.info(f"  CLI Chat:        aegis chat | aegis --help")
        self.logger.info(f"  System Status:   aegis status")
        self.logger.info(f"  Logs:            {self.config.logs_dir}/")
        self.logger.info("  Next steps:")
        self.logger.info("    . .\.venv\Scripts\Activate   (optional: if using python directly)")
        self.logger.info("    .\dev run boot --skip-redis")
        print()

    def _flush_streams(self) -> bool:
        """
        Delete all Aegis Redis streams to prevent stale message processing.
        
        Streams are recreated automatically by MessageSubscriber (MKSTREAM)
        when agents subscribe. This ensures a clean slate on every boot.
        
        Returns:
            True if flush succeeded or was skipped, False on error.
        """
        try:
            import redis as redis_lib
            r = redis_lib.Redis(
                host=self.config.redis_host,
                port=self.config.redis_port,
                decode_responses=True,
            )
            
            keys = r.keys("aegis:stream:*")
            if not keys:
                self.logger.info("No existing streams to flush.")
                return True
            
            deleted = r.delete(*keys)
            self.logger.success(f"Flushed {deleted} stream(s) from previous session.")
            r.close()
            return True
            
        except Exception as e:
            self.logger.error(f"Stream flush failed: {e}")
            return False

if __name__ == "__main__":
    args = parse_args()
    config = resolve_config()
    logger = LauncherLogger(config.logs_dir / "aegis_launcher.log")

    boot = AegisBoot(config, logger, args)
    exit_code = boot.run()
    logger.close()
    sys.exit(exit_code)
