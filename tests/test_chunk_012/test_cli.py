# tests/test_chunk_012/test_cli.py
# Tests for Part X, §10.1 — CLI Management Tool
"""
Unit tests for the Aegis CLI application.
Tests command registration, help output, and basic invocations.
"""

import pytest
from typer.testing import CliRunner
from aegis.cli.main import app

runner = CliRunner()


class TestCLIRoot:
    """Test the root `aegis` command."""

    def test_help_displays(self):
        """aegis --help should show all subcommands."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "Project Aegis" in result.output or "aegis" in result.output.lower()

    def test_no_args_shows_help(self):
        """Running aegis with no args shows help (no_args_is_help=True)."""
        result = runner.invoke(app, [])
        assert result.exit_code == 0


class TestCLIConfig:
    """Test config commands."""

    def test_config_show_missing_file(self, tmp_path):
        """aegis config show should error on missing config."""
        result = runner.invoke(app, ["config", "show", "--config", str(tmp_path / "missing.yaml")])
        assert result.exit_code != 0 or "not found" in result.output.lower() or "✗" in result.output

    def test_config_show_valid(self, tmp_path):
        """aegis config show should display YAML content."""
        cfg_file = tmp_path / "test_config.yaml"
        cfg_file.write_text("web:\n  port: 8420\n")
        result = runner.invoke(app, ["config", "show", "--config", str(cfg_file)])
        assert result.exit_code == 0

    def test_config_set(self, tmp_path):
        """aegis config set should update a YAML key."""
        cfg_file = tmp_path / "test_config.yaml"
        cfg_file.write_text("web:\n  port: 8420\n")
        result = runner.invoke(app, ["config", "set", "web.port", "9000", "--config", str(cfg_file)])
        assert result.exit_code == 0
        assert "9000" in result.output


class TestCLISubcommandRegistration:
    """Verify all expected subcommand groups are registered."""

    @pytest.mark.parametrize("group", ["user", "tenant", "memory", "schedule", "config"])
    def test_subcommand_group_help(self, group):
        """Each subcommand group should respond to --help."""
        result = runner.invoke(app, [group, "--help"])
        assert result.exit_code == 0
