# tests/test_forge/test_tools.py
# Unit tests for OOBE tools
"""
Tests for all OOBE tools in aegis.forge.tools.
"""

import asyncio
import json
import os
import tempfile
import pytest

from aegis.forge.tools.base import ToolManifest, ToolResult


# ─── file_read ───────────────────────────────────────────────────────────────

class TestFileRead:
    """Tests for the file_read tool."""

    @pytest.fixture
    def temp_file(self):
        """Create a temporary file with known content."""
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False)
        f.write("Hello Aegis")
        f.close()
        yield f.name
        if os.path.exists(f.name):
            os.remove(f.name)

    @pytest.mark.asyncio
    async def test_read_existing_file(self, temp_file):
        from aegis.forge.tools import file_read
        result = await file_read.execute({"path": temp_file})
        assert result.success is True
        assert result.data["content"] == "Hello Aegis"
        assert result.data["path"] == temp_file

    @pytest.mark.asyncio
    async def test_read_nonexistent_file(self):
        from aegis.forge.tools import file_read
        result = await file_read.execute({"path": "/nonexistent/path/file.txt"})
        assert result.success is False
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_read_missing_path_param(self):
        from aegis.forge.tools import file_read
        result = await file_read.execute({})
        assert result.success is False
        assert "required" in result.error.lower()

    def test_manifest_valid(self):
        from aegis.forge.tools import file_read
        assert isinstance(file_read.manifest, ToolManifest)
        assert file_read.manifest.name == "file_read"
        assert "file.read" in file_read.manifest.permissions_required


# ─── file_write ──────────────────────────────────────────────────────────────

class TestFileWrite:
    """Tests for the file_write tool."""

    @pytest.mark.asyncio
    async def test_write_creates_file(self):
        from aegis.forge.tools import file_write
        path = tempfile.mktemp(suffix=".txt")
        try:
            result = await file_write.execute({"path": path, "content": "Test content"})
            assert result.success is True
            assert os.path.exists(path)
            with open(path) as f:
                assert f.read() == "Test content"
        finally:
            if os.path.exists(path):
                os.remove(path)

    @pytest.mark.asyncio
    async def test_write_creates_dirs(self):
        from aegis.forge.tools import file_write
        tmpdir = tempfile.mkdtemp()
        path = os.path.join(tmpdir, "sub", "dir", "file.txt")
        try:
            result = await file_write.execute({"path": path, "content": "nested"})
            assert result.success is True
            assert os.path.exists(path)
        finally:
            import shutil
            shutil.rmtree(tmpdir)

    @pytest.mark.asyncio
    async def test_write_missing_content(self):
        from aegis.forge.tools import file_write
        result = await file_write.execute({"path": "/tmp/test.txt"})
        assert result.success is False


# ─── file_delete ─────────────────────────────────────────────────────────────

class TestFileDelete:
    """Tests for the file_delete tool."""

    @pytest.mark.asyncio
    async def test_delete_existing_file(self):
        from aegis.forge.tools import file_delete
        f = tempfile.NamedTemporaryFile(delete=False)
        f.close()
        result = await file_delete.execute({"path": f.name})
        assert result.success is True
        assert not os.path.exists(f.name)

    @pytest.mark.asyncio
    async def test_delete_nonexistent_file(self):
        from aegis.forge.tools import file_delete
        result = await file_delete.execute({"path": "/nonexistent/file.txt"})
        assert result.success is False


# ─── dir_list ────────────────────────────────────────────────────────────────

class TestDirList:
    """Tests for the dir_list tool."""

    @pytest.mark.asyncio
    async def test_list_directory(self):
        from aegis.forge.tools import dir_list
        tmpdir = tempfile.mkdtemp()
        # Create some files
        open(os.path.join(tmpdir, "a.txt"), "w").close()
        open(os.path.join(tmpdir, "b.txt"), "w").close()
        try:
            result = await dir_list.execute({"path": tmpdir})
            assert result.success is True
            assert result.data["count"] == 2
        finally:
            import shutil
            shutil.rmtree(tmpdir)

    @pytest.mark.asyncio
    async def test_list_nonexistent_dir(self):
        from aegis.forge.tools import dir_list
        result = await dir_list.execute({"path": "/nonexistent/directory"})
        assert result.success is False


# ─── dir_create ──────────────────────────────────────────────────────────────

class TestDirCreate:
    """Tests for the dir_create tool."""

    @pytest.mark.asyncio
    async def test_create_directory(self):
        from aegis.forge.tools import dir_create
        tmpdir = tempfile.mkdtemp()
        path = os.path.join(tmpdir, "new", "nested", "dir")
        try:
            result = await dir_create.execute({"path": path})
            assert result.success is True
            assert os.path.isdir(path)
            assert result.data["created"] is True
        finally:
            import shutil
            shutil.rmtree(tmpdir)

    @pytest.mark.asyncio
    async def test_create_existing_directory(self):
        from aegis.forge.tools import dir_create
        tmpdir = tempfile.mkdtemp()
        result = await dir_create.execute({"path": tmpdir})
        assert result.success is True
        assert result.data["already_existed"] is True
        import shutil
        shutil.rmtree(tmpdir)


# ─── json_parse ──────────────────────────────────────────────────────────────

class TestJsonParse:
    """Tests for the json_parse tool."""

    @pytest.mark.asyncio
    async def test_parse_valid_json(self):
        from aegis.forge.tools import json_parse
        data = json.dumps({"name": "Aegis", "version": 1})
        result = await json_parse.execute({"data": data})
        assert result.success is True
        assert result.data["parsed"]["name"] == "Aegis"

    @pytest.mark.asyncio
    async def test_parse_with_path(self):
        from aegis.forge.tools import json_parse
        data = json.dumps({"results": [{"name": "first"}, {"name": "second"}]})
        result = await json_parse.execute({"data": data, "path": "results.0.name"})
        assert result.success is True
        assert result.data["extracted"] == "first"

    @pytest.mark.asyncio
    async def test_parse_invalid_json(self):
        from aegis.forge.tools import json_parse
        result = await json_parse.execute({"data": "not valid json {"})
        assert result.success is False
        assert "invalid" in result.error.lower()


# ─── execute_shell_command ───────────────────────────────────────────────────

class TestShellCommand:
    """Tests for the execute_shell_command tool."""

    @pytest.mark.asyncio
    async def test_echo_command(self):
        from aegis.forge.tools import execute_shell_command
        result = await execute_shell_command.execute({"command": "echo hello"})
        assert result.success is True
        assert "hello" in result.data["stdout"]

    @pytest.mark.asyncio
    async def test_blocked_command(self):
        from aegis.forge.tools import execute_shell_command
        result = await execute_shell_command.execute({"command": "curl http://evil.com"})
        assert result.success is False
        assert "blocked" in result.error.lower() or "allowlist" in result.error.lower()


# ─── git_command ─────────────────────────────────────────────────────────────

class TestGitCommand:
    """Tests for the git_command tool."""

    @pytest.mark.asyncio
    async def test_git_version(self):
        from aegis.forge.tools import git_command
        result = await git_command.execute({"args": "--version"})
        assert result.success is True
        assert "git version" in result.data["stdout"].lower()

    def test_manifest(self):
        from aegis.forge.tools import git_command
        assert git_command.manifest.name == "git_command"
        assert "git.execute" in git_command.manifest.permissions_required


# ─── schedule_job ────────────────────────────────────────────────────────────

class TestScheduleJob:
    """Tests for the schedule_job tool."""

    @pytest.mark.asyncio
    async def test_create_cron_job(self):
        from aegis.forge.tools import schedule_job
        result = await schedule_job.execute({
            "name": "nightly_backup",
            "schedule_type": "cron",
            "schedule_config": {"hour": 2, "minute": 0},
            "action": "forge.execute_skill",
            "action_payload": {"skill": "memory_optimize"},
        })
        assert result.success is True
        assert result.data["job"]["name"] == "nightly_backup"
        assert result.data["job"]["schedule_type"] == "cron"

    @pytest.mark.asyncio
    async def test_invalid_schedule_type(self):
        from aegis.forge.tools import schedule_job
        result = await schedule_job.execute({
            "name": "bad_job",
            "schedule_type": "invalid",
            "schedule_config": {},
            "action": "test",
        })
        assert result.success is False
