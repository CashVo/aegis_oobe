#!/usr/bin/env python3
# scripts/aegis_restart.py
"""
Aegis System Restart Script
============================
Performs a graceful shutdown followed by a full boot.

Implements: Chunk-013 Spec — Part 4: Restart Script

Usage:
    python scripts/aegis_restart.py [--full] [--force] [--headless] [--verbose]

Sequence:
    1. Run full shutdown (with --keep-redis by default for faster restart)
    2. Verify clean state
    3. Run full boot (skipping FRX since already configured)
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts._launcher_common import resolve_config, LauncherLogger, LauncherConfig
from scripts.aegis_shutdown import AegisShutdown
from scripts.aegis_boot import AegisBoot


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for the restart script."""
    parser = argparse.ArgumentParser(description="Restart the Aegis system")
    parser.add_argument(
        "--full",
        action="store_true",
        help="Full restart including Redis (default keeps Redis alive)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force kill if graceful shutdown times out",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Skip web server on boot (CLI-only mode)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose output",
    )
    return parser.parse_args()


BANNER = r"""
    +=============================================+
    |          PROJECT AEGIS -- RESTART           |
    +=============================================+
"""


class AegisRestart:
    """
    Orchestrates shutdown -> verification -> boot cycle.

    By default keeps Redis alive between shutdown and boot for speed.
    Use --full for a complete cold restart including Redis.
    """

    def __init__(self, config: LauncherConfig, logger: LauncherLogger, args: argparse.Namespace):
        self.config = config
        self.logger = logger
        self.args = args

    def run(self) -> int:
        """
        Execute restart sequence (shutdown -> verify -> boot).

        Returns:
            Exit code (0=success, non-zero=failure).
        """
        print(BANNER)
        self.logger.info("=== AEGIS RESTART ===")

        # Phase 1: Shutdown
        self.logger.info("Phase 1/3: Shutting down...")
        shutdown_args = argparse.Namespace(
            keep_redis=(not self.args.full),
            keep_web=False,
            force=self.args.force,
            timeout=15,
        )
        shutdown = AegisShutdown(self.config, self.logger, shutdown_args)
        shutdown_code = shutdown.run()

        if shutdown_code not in (0,):
            self.logger.error("Shutdown phase failed. Aborting restart.")
            return shutdown_code

        # Phase 2: Verify clean state
        self.logger.info("Phase 2/3: Verifying clean state...")
        time.sleep(0.5)

        # Ensure web port is free before boot
        from scripts._launcher_common import wait_for_condition, is_port_available
        if not wait_for_condition(
            lambda: is_port_available(self.config.web_host, self.config.web_port),
            timeout=5.0,
            interval=0.5,
            description="Web port release",
        ):
            self.logger.warn(f"Port {self.config.web_port} still in use. Attempting cleanup...")
            # Nuclear option: kill anything on the port
            if sys.platform == "win32":
                subprocess.run(
                    f"for /f \"tokens=5\" %a in ('netstat -ano ^| findstr :{self.config.web_port}') do taskkill /F /PID %a",
                    shell=True, capture_output=True,
                )
                time.sleep(1)

        # Phase 3: Boot
        self.logger.info("Phase 3/3: Booting...")
        boot_args = argparse.Namespace(
            skip_redis=(not self.args.full),
            skip_frx=True,  # Never re-run FRX on restart
            headless=self.args.headless,
            verbose=self.args.verbose,
            keep_streams=getattr(self.args, "keep_streams", False),  # Pass through
        )
        boot = AegisBoot(self.config, self.logger, boot_args)
        boot_code = boot.run()

        if boot_code == 0:
            self.logger.success("Aegis restart complete.")
        else:
            self.logger.error("Boot phase failed after successful shutdown.")

        return boot_code


if __name__ == "__main__":
    args = parse_args()
    config = resolve_config()
    logger = LauncherLogger(config.logs_dir / "aegis_launcher.log")

    restart = AegisRestart(config, logger, args)
    exit_code = restart.run()
    logger.close()
    sys.exit(exit_code)
