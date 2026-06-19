# tests/test_chunk_013/test_launcher_common.py
"""
Unit tests for scripts/_launcher_common.py

Tests PID management, port checking, service state, and config resolution.
"""

import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Ensure project root on path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts._launcher_common import (
    ServiceState,
    ServiceStatus,
    LauncherConfig,
    LauncherLogger,
    read_pid,
    write_pid,
    remove_pid,
    wait_for_condition,
    find_executable,
    is_port_available,
    _is_process_alive,
)


class TestServiceStatus:
    """Tests for ServiceStatus dataclass."""

    def test_to_dict_basic(self):
        status = ServiceStatus(name="Redis", state=ServiceState.RUNNING, pid=1234)
        d = status.to_dict()
        assert d["name"] == "Redis"
        assert d["state"] == "running"
        assert d["pid"] == 1234
        assert d["error"] is None

    def test_to_dict_with_error(self):
        status = ServiceStatus(
            name="Web UI", state=ServiceState.ERROR, error="Port in use"
        )
        d = status.to_dict()
        assert d["state"] == "error"
        assert d["error"] == "Port in use"


class TestPIDManagement:
    """Tests for PID file read/write/remove operations."""

    def test_write_and_read_pid(self, tmp_path):
        pid_file = tmp_path / "test.pid"
        # Write our own PID (guaranteed alive)
        write_pid(pid_file, os.getpid())
        result = read_pid(pid_file)
        assert result == os.getpid()

    def test_read_pid_nonexistent(self, tmp_path):
        pid_file = tmp_path / "nonexistent.pid"
        assert read_pid(pid_file) is None

    def test_read_pid_stale(self, tmp_path):
        """A PID file pointing to a dead process should return None."""
        pid_file = tmp_path / "stale.pid"
        # Use a PID that almost certainly doesn't exist
        pid_file.write_text("999999999")
        assert read_pid(pid_file) is None

    def test_read_pid_invalid_content(self, tmp_path):
        pid_file = tmp_path / "invalid.pid"
        pid_file.write_text("not_a_number")
        assert read_pid(pid_file) is None

    def test_remove_pid_exists(self, tmp_path):
        pid_file = tmp_path / "removeme.pid"
        pid_file.write_text("12345")
        remove_pid(pid_file)
        assert not pid_file.exists()

    def test_remove_pid_nonexistent(self, tmp_path):
        pid_file = tmp_path / "ghost.pid"
        # Should not raise
        remove_pid(pid_file)

    def test_write_pid_creates_parent_dirs(self, tmp_path):
        pid_file = tmp_path / "deep" / "nested" / "test.pid"
        write_pid(pid_file, 42)
        assert pid_file.exists()
        assert pid_file.read_text().strip() == "42"


class TestWaitForCondition:
    """Tests for the polling utility."""

    def test_immediate_true(self):
        result = wait_for_condition(lambda: True, timeout=1.0)
        assert result is True

    def test_timeout_false(self):
        result = wait_for_condition(lambda: False, timeout=0.5, interval=0.1)
        assert result is False

    def test_becomes_true(self):
        start = time.monotonic()
        # Will become true after ~0.3 seconds
        result = wait_for_condition(
            lambda: (time.monotonic() - start) > 0.3,
            timeout=2.0,
            interval=0.1,
        )
        assert result is True


class TestPortAvailability:
    """Tests for port checking."""

    def test_available_port(self):
        # Port 0 trick: OS assigns a free port
        # Check a very high port that's unlikely to be in use
        assert is_port_available("127.0.0.1", 59999) is True

    def test_unavailable_port(self):
        """Bind a port, then verify is_port_available sees it as in use."""
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        port = sock.getsockname()[1]
        try:
            assert is_port_available("127.0.0.1", port) is False
        finally:
            sock.close()


class TestProcessAlive:
    """Tests for _is_process_alive."""

    def test_own_process(self):
        assert _is_process_alive(os.getpid()) is True

    def test_dead_process(self):
        assert _is_process_alive(999999999) is False


class TestFindExecutable:
    """Tests for find_executable."""

    def test_find_python(self):
        # python or python3 should always exist
        result = find_executable("python3") or find_executable("python")
        assert result is not None

    def test_find_nonexistent(self):
        result = find_executable("aegis_nonexistent_binary_xyz")
        assert result is None


class TestLauncherLogger:
    """Tests for the dual-output logger."""

    def test_creates_log_file(self, tmp_path):
        log_path = tmp_path / "test.log"
        logger = LauncherLogger(log_path)
        logger.info("test message")
        logger.close()
        assert log_path.exists()
        content = log_path.read_text()
        assert "test message" in content

    def test_log_json_format(self, tmp_path):
        import json as json_mod
        log_path = tmp_path / "test.log"
        logger = LauncherLogger(log_path)
        logger.error("something broke", component="redis")
        logger.close()
        line = log_path.read_text().strip()
        data = json_mod.loads(line)
        assert data["level"] == "ERROR"
        assert data["message"] == "something broke"
        assert data["component"] == "redis"
