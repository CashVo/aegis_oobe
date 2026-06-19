#!/usr/bin/env python3
# scripts/aegis_status.py
"""
Aegis System Status Script
===========================
Quick health check without starting or stopping anything.

Implements: Chunk-013 Spec — Part 5: Status Script

Usage:
    python scripts/aegis_status.py [--json]

Reports:
    - Redis: running/stopped (PID, port)
    - System Manager: running/stopped (PID)
    - Web UI: accessible/not (port)
    - Agent Council: individual agent status (if health endpoint available)
"""

import argparse
import json
import sys
from aegis.utils.time import utcnow
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts._launcher_common import (
    resolve_config,
    LauncherLogger,
    LauncherConfig,
    ServiceStatus,
    ServiceState,
    is_redis_running,
    is_aegis_running,
    is_web_server_running,
    read_pid,
)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for the status script."""
    parser = argparse.ArgumentParser(description="Check Aegis system status")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output status as JSON (for scripting)",
    )
    return parser.parse_args()


class AegisStatus:
    """
    Gathers and reports system status for all Aegis components.

    Checks Redis, System Manager, Web UI, and individual agents.
    Supports both human-readable and JSON output formats.
    """

    def __init__(self, config: LauncherConfig, logger: LauncherLogger, args: argparse.Namespace):
        self.config = config
        self.logger = logger
        self.args = args

    def run(self) -> int:
        """
        Gather and report system status.

        Returns:
            0 if all critical services running, 1 otherwise.
        """
        statuses = self._gather_all_status()

        if self.args.json:
            self._output_json(statuses)
        else:
            self._output_human(statuses)

        # Exit 0 if all critical services running, 1 otherwise
        critical = ["Redis", "System Manager"]
        all_critical_running = all(
            s.state == ServiceState.RUNNING
            for s in statuses
            if s.name in critical
        )
        return 0 if all_critical_running else 1

    def _gather_all_status(self) -> list:
        """Check each component and return status list."""
        statuses = []
        statuses.append(self._check_redis())
        statuses.append(self._check_system_manager())
        statuses.append(self._check_web_ui())
        statuses.extend(self._check_agents())
        return statuses

    def _check_redis(self) -> ServiceStatus:
        """Check Redis connectivity and report status."""
        redis_pid = read_pid(self.config.pid_dir / "redis.pid")
        if is_redis_running(self.config):
            return ServiceStatus(
                name="Redis",
                state=ServiceState.RUNNING,
                pid=redis_pid,
                details=f":{self.config.redis_port}",
            )
        return ServiceStatus(
            name="Redis",
            state=ServiceState.STOPPED,
            pid=redis_pid,
        )

    def _check_system_manager(self) -> ServiceStatus:
        """Check System Manager process and report status."""
        sm_pid = read_pid(self.config.pid_dir / "aegis_system_manager.pid")
        if sm_pid and is_aegis_running(self.config):
            return ServiceStatus(
                name="System Manager",
                state=ServiceState.RUNNING,
                pid=sm_pid,
            )
        return ServiceStatus(
            name="System Manager",
            state=ServiceState.STOPPED,
        )

    def _check_web_ui(self) -> ServiceStatus:
        """Check Mission Control web server health via HTTP probe."""
        pid = read_pid(self.config.pid_dir / "aegis_web.pid")
        if pid is None:
            return ServiceStatus(
                name="Web UI (Mission Control)",
                state=ServiceState.STOPPED,
            )

        # Verify HTTP health endpoint responds
        try:
            import httpx
            resp = httpx.get(
                f"http://{self.config.web_host}:{self.config.web_port}/health",
                timeout=2.0,
            )
            if resp.status_code == 200:
                return ServiceStatus(
                    name="Web UI (Mission Control)",
                    state=ServiceState.RUNNING,
                    pid=pid,
                    details=f":{self.config.web_port}",
                )
        except Exception:
            pass

        return ServiceStatus(
            name="Web UI (Mission Control)",
            state=ServiceState.ERROR,
            pid=pid,
            error="Process alive but not responding on HTTP",
        )

    def _check_agents(self) -> list:
        """
        Check individual agent status via System Manager health endpoint.

        Falls back to 'unknown' if SM is not running or health endpoint
        is unavailable.
        """
        agents = [
            "Observer", "Warden", "Identity", "Lexicon",
            "Janus", "Oracle", "Forge", "TOrchestrator",
        ]

        if not is_aegis_running(self.config):
            return [
                ServiceStatus(name=agent, state=ServiceState.STOPPED)
                for agent in agents
            ]

        # Try to get detailed status from health endpoint
        try:
            import httpx
            resp = httpx.get(
                f"http://{self.config.web_host}:{self.config.web_port}/api/v1/health/agents",
                timeout=3.0,
            )
            if resp.status_code == 200:
                data = resp.json()
                statuses = []
                for agent in agents:
                    agent_data = data.get(agent.lower(), {})
                    state_str = agent_data.get("state", "unknown")
                    try:
                        state = ServiceState(state_str)
                    except ValueError:
                        state = ServiceState.UNKNOWN
                    statuses.append(ServiceStatus(
                        name=agent,
                        state=state,
                        details=agent_data.get("details"),
                    ))
                return statuses
        except Exception:
            pass

        # Fallback: SM is running, so assume agents are too
        return [
            ServiceStatus(name=agent, state=ServiceState.UNKNOWN, details="SM alive, no detail")
            for agent in agents
        ]

    def _output_json(self, statuses: list) -> None:
        """Output status as structured JSON for scripting/monitoring."""
        output = {
            "timestamp": utcnow().isoformat(),
            "services": [s.to_dict() for s in statuses],
        }
        print(json.dumps(output, indent=2))

    def _output_human(self, statuses: list) -> None:
        """Pretty-print status table to stdout with color and alignment."""
        STATE_ICONS = {
            ServiceState.RUNNING: "\033[32m UP  \033[0m",
            ServiceState.STOPPED: "\033[31m DOWN\033[0m",
            ServiceState.ERROR:   "\033[33m ERR \033[0m",
            ServiceState.UNKNOWN: "\033[37m UNK \033[0m",
            ServiceState.STARTING: "\033[36m BOOT\033[0m",
            ServiceState.STOPPING: "\033[33m STOP\033[0m",
        }

        print()
        print("+--------------------------------------------------+")
        print("|             AEGIS SYSTEM STATUS                   |")
        print("+------------------------+--------+----------------+")
        print("| Component              | State  | Details        |")
        print("+------------------------+--------+----------------+")

        for s in statuses:
            name = s.name[:22].ljust(22)
            icon = STATE_ICONS.get(s.state, " ?  ")
            details = ""
            if s.pid:
                details = f"PID {s.pid}"
            if s.details:
                details = f"{details} {s.details}".strip() if details else s.details
            if s.error:
                details = s.error
            details = details[:14].ljust(14)
            print(f"| {name} | {icon} | {details} |")

        print("+------------------------+--------+----------------+")
        print()


if __name__ == "__main__":
    args = parse_args()
    config = resolve_config()
    logger = LauncherLogger(config.logs_dir / "aegis_launcher.log")

    status = AegisStatus(config, logger, args)
    exit_code = status.run()
    logger.close()
    sys.exit(exit_code)
