# scripts/_launcher_common.py
"""
Shared utilities for all Aegis launcher scripts.

Implements: Chunk-013 Spec — Part 1: Launcher Common Utilities

Provides configuration resolution, PID management, service state tracking,
and dual-output logging (human-readable stdout + structured JSON file).
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Callable
import subprocess
import shutil
import sys
import os
from aegis.utils.time import utcnow, dt_time, monotonic, sleep
import signal
import json
import socket
from pathlib import Path


class ServiceState(str, Enum):
    """Possible states for a managed system service."""
    RUNNING = "running"
    STOPPED = "stopped"
    STARTING = "starting"
    STOPPING = "stopping"
    ERROR = "error"
    UNKNOWN = "unknown"
    DEGRADED = "degraded"
    HEALTHY = "healthy"


@dataclass
class ServiceStatus:
    """Status report for a single system component."""
    name: str
    state: ServiceState
    pid: Optional[int] = None
    uptime_seconds: Optional[float] = None
    error: Optional[str] = None
    details: Optional[str] = None

    def to_dict(self) -> dict:
        """Serialize to dictionary for JSON output."""
        return {
            "name": self.name,
            "state": self.state.value,
            "pid": self.pid,
            "uptime_seconds": self.uptime_seconds,
            "error": self.error,
            "details": self.details,
        }


@dataclass
class LauncherConfig:
    """
    Resolved system configuration used by all launcher scripts.

    Populated from aegis_config.yaml with environment variable overrides.
    """
    project_root: Path
    config_path: Path          # aegis_config.yaml
    data_dir: Path             # aegis_data/
    logs_dir: Path             # logs/
    pid_dir: Path              # .pids/ (runtime PID tracking)
    redis_host: str = "127.0.0.1"
    redis_port: int = 6379
    web_host: str = "127.0.0.1"
    web_port: int = 8420
    boot_timeout_seconds: int = 30
    shutdown_timeout_seconds: int = 15


class LauncherLogger:
    """
    Dual-output logger: human-readable colored stdout + structured JSON file.

    All launcher scripts use this for consistent output formatting and
    persistent log records.
    """

    COLORS = {
        "info": "\033[37m",      # white
        "warn": "\033[33m",      # yellow
        "error": "\033[31m",     # red
        "success": "\033[32m",   # green
        "step": "\033[36m",      # cyan
        "reset": "\033[0m",
    }

    def __init__(self, log_path: Path):
        """
        Initialize logger with file output path.

        Args:
            log_path: Path to the JSON log file. Parent directories are
                      created if they don't exist.
        """
        self.log_path = log_path
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._file = open(self.log_path, "a", encoding="utf-8")

    def _write_file(self, level: str, message: str, **context) -> None:
        """Write a structured JSON log entry to the log file."""
        entry = {
            "timestamp": utcnow().isoformat(),
            "level": level,
            "message": message,
            **context,
        }
        self._file.write(json.dumps(entry) + "\n")
        self._file.flush()

    def _print(self, color_key: str, prefix: str, message: str) -> None:
        """Print a colored message to stdout."""
        c = self.COLORS.get(color_key, "")
        r = self.COLORS["reset"]
        print(f"{c}{prefix}{r} {message}")

    def info(self, message: str, **context) -> None:
        """Log an informational message."""
        self._print("info", "[INFO]", message)
        self._write_file("INFO", message, **context)

    def warn(self, message: str, **context) -> None:
        """Log a warning message."""
        self._print("warn", "[WARN]", message)
        self._write_file("WARN", message, **context)

    def error(self, message: str, **context) -> None:
        """Log an error message."""
        self._print("error", "[ERROR]", message)
        self._write_file("ERROR", message, **context)

    def success(self, message: str, **context) -> None:
        """Log a success message."""
        self._print("success", "[OK]", message)
        self._write_file("SUCCESS", message, **context)

    def step(self, step_num: int, total: int, message: str) -> None:
        """Log a numbered step in a sequence."""
        prefix = f"[{step_num}/{total}]"
        self._print("step", prefix, message)
        self._write_file("STEP", message, step_num=step_num, total=total)

    def close(self) -> None:
        """Flush and close the log file handle."""
        if self._file and not self._file.closed:
            self._file.close()


def resolve_config() -> LauncherConfig:
    """
    Locate project root and build a LauncherConfig.

    Resolution order:
      1. Walk up from this file's directory to find project root
      2. Load aegis_config.yaml if it exists
      3. Apply environment variable overrides

    Returns:
        Fully resolved LauncherConfig instance.
    """
    # Walk up from this file to find project root
    current = Path(__file__).resolve().parent.parent
    project_root = current

    config_path = project_root / "aegis_config.yaml"
    data_dir = project_root / "aegis_data"
    logs_dir = project_root / "logs"
    pid_dir = project_root / ".pids"

    # Ensure runtime directories exist
    logs_dir.mkdir(parents=True, exist_ok=True)
    pid_dir.mkdir(parents=True, exist_ok=True)

    # Defaults
    redis_host = "127.0.0.1"
    redis_port = 6379
    web_host = "127.0.0.1"
    web_port = 8420
    boot_timeout = 30
    shutdown_timeout = 15

    # Load config file if it exists
    if config_path.exists():
        try:
            import yaml

            with open(config_path, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}

            redis_cfg = cfg.get("redis", {})
            redis_host = redis_cfg.get("host", redis_host)
            redis_port = int(redis_cfg.get("port", redis_port))

            web_cfg = cfg.get("web", {})
            web_host = web_cfg.get("host", web_host)
            web_port = int(web_cfg.get("port", web_port))

            sm_cfg = cfg.get("system_manager", {})
            boot_timeout = int(sm_cfg.get("startup_timeout_seconds", boot_timeout))
            shutdown_timeout = int(sm_cfg.get("shutdown_timeout_seconds", shutdown_timeout))

        except Exception:
            pass  # Use defaults if config is malformed

    # Environment variable overrides (highest precedence)
    redis_host = os.environ.get("AEGIS_REDIS_HOST", redis_host)
    redis_port = int(os.environ.get("AEGIS_REDIS_PORT", str(redis_port)))
    web_port = int(os.environ.get("AEGIS_WEB_PORT", str(web_port)))

    return LauncherConfig(
        project_root=project_root,
        config_path=config_path,
        data_dir=data_dir,
        logs_dir=logs_dir,
        pid_dir=pid_dir,
        redis_host=redis_host,
        redis_port=redis_port,
        web_host=web_host,
        web_port=web_port,
        boot_timeout_seconds=boot_timeout,
        shutdown_timeout_seconds=shutdown_timeout,
    )


def is_redis_running(config: LauncherConfig) -> bool:
    """
    Check if Redis is reachable on configured host:port.

    Performs a socket connect followed by a PING command to verify
    the service is actually Redis (not just any TCP listener).

    Args:
        config: Launcher configuration with Redis host/port.

    Returns:
        True if Redis responds to PING, False otherwise.
    """
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2.0)
        result = sock.connect_ex((config.redis_host, config.redis_port))
        sock.close()
        if result != 0:
            return False
        # Verify it's actually Redis by sending PING
        import redis as redis_lib
        r = redis_lib.Redis(host=config.redis_host, port=config.redis_port, socket_timeout=2)
        return r.ping()
    except ImportError:
        raise RuntimeError(
            "Python 'redis' package not installed. Run: pip install redis[hiredis]"
        )
    except Exception:
        return False


def is_aegis_running(config: LauncherConfig) -> bool:
    """
    Check if Aegis System Manager PID file exists and process is alive.

    Args:
        config: Launcher configuration with PID directory.

    Returns:
        True if System Manager process is alive.
    """
    pid = read_pid(config.pid_dir / "aegis_system_manager.pid")
    return pid is not None


def is_web_server_running(config: LauncherConfig) -> bool:
    """
    Check if Mission Control web server PID file exists and process is alive.

    Args:
        config: Launcher configuration with PID directory.

    Returns:
        True if web server process is alive.
    """
    pid = read_pid(config.pid_dir / "aegis_web.pid")
    return pid is not None


def read_pid(pid_file: Path) -> Optional[int]:
    """
    Read PID from file and verify process is alive.

    If the PID file exists but the process is dead, this returns None
    (stale PID detection per RT-13-4).

    Args:
        pid_file: Path to the .pid file.

    Returns:
        PID integer if process is alive, None otherwise.
    """
    if not pid_file.exists():
        return None

    try:
        pid = int(pid_file.read_text().strip())
    except (ValueError, OSError):
        return None

    # Verify process is alive
    if _is_process_alive(pid):
        return pid

    # Stale PID file — process no longer exists
    return None


def write_pid(pid_file: Path, pid: int) -> None:
    """
    Write PID to file atomically via tmp+rename.

    Args:
        pid_file: Destination path for the PID file.
        pid: Process ID to write.
    """
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    tmp_file = pid_file.with_suffix(".tmp")
    tmp_file.write_text(str(pid))
    tmp_file.replace(pid_file)


def remove_pid(pid_file: Path) -> None:
    """
    Remove PID file if it exists. Safe to call on non-existent files.

    Args:
        pid_file: Path to the .pid file to remove.
    """
    try:
        pid_file.unlink(missing_ok=True)
    except OSError:
        pass


def wait_for_condition(
    predicate: Callable[[], bool],
    timeout: float,
    interval: float = 0.5,
    description: str = "",
) -> bool:
    """
    Poll a predicate function until it returns True or timeout expires.

    Args:
        predicate: Zero-argument callable returning bool.
        timeout: Maximum seconds to wait.
        interval: Seconds between polls.
        description: Human-readable description for logging.

    Returns:
        True if predicate became True within timeout, False otherwise.
    """
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        if predicate():
            return True
        sleep(interval)
    return False


def find_executable(name: str) -> Optional[Path]:
    """
    Locate an executable on PATH.

    Args:
        name: Name of the executable (e.g., 'redis-server').

    Returns:
        Path to the executable if found, None otherwise.
    """
    result = shutil.which(name)
    return Path(result) if result else None


def is_port_available(host: str, port: int) -> bool:
    """
    Check if a TCP port is available (not bound by another process).

    Args:
        host: Hostname or IP to check.
        port: Port number to check.

    Returns:
        True if port is free, False if something is listening.
    """
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1.0)
        result = sock.connect_ex((host, port))
        sock.close()
        return result != 0  # Non-zero means connection refused = port is free
    except OSError:
        return True  # Assume available on error


def _is_process_alive(pid: int) -> bool:
    """
    Check if a process with given PID is alive using signal 0.

    Args:
        pid: Process ID to check.

    Returns:
        True if process exists and is accessible.
    """
    try:
        os.kill(pid, 0)  # Signal 0: no kill, just check existence
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # Process exists but we can't signal it
    except OSError:
        return False
