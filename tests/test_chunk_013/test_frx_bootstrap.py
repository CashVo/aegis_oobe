# tests/test_chunk_013/test_frx_bootstrap.py
"""
Unit tests for aegis/frx/bootstrap.py

Tests identity store creation and Lexicon storage initialization.
"""

import sys
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from aegis.frx.bootstrap import (
    bootstrap_identity_store,
    bootstrap_lexicon_storage,
)


@pytest.fixture
def mock_config(tmp_path):
    """Create a mock config with tmp_path as data_dir."""
    config = MagicMock()
    config.data_dir = tmp_path / "aegis_data"
    return config


@pytest.fixture
def root_creds():
    """Standard root credentials for testing."""
    return {
        "username": "testroot",
        "passphrase": "testpassphrase123",
        "display_name": "Test Root User",
    }


class TestBootstrapIdentityStore:
    """Tests for identity database creation."""

    def test_creates_database(self, mock_config, root_creds):
        result = bootstrap_identity_store(mock_config, root_creds, "TestTenant")
        db_path = mock_config.data_dir / "identity.db"
        assert db_path.exists()
        assert "tenant_id" in result
        assert "user_id" in result
        assert "role_id" in result

    def test_creates_tenant(self, mock_config, root_creds):
        result = bootstrap_identity_store(mock_config, root_creds, "MyOrg")
        conn = sqlite3.connect(str(mock_config.data_dir / "identity.db"))
        row = conn.execute("SELECT name FROM tenants WHERE tenant_id = ?", (result["tenant_id"],)).fetchone()
        conn.close()
        assert row[0] == "MyOrg"

    def test_creates_root_user(self, mock_config, root_creds):
        result = bootstrap_identity_store(mock_config, root_creds, "TestTenant")
        conn = sqlite3.connect(str(mock_config.data_dir / "identity.db"))
        row = conn.execute(
            "SELECT username, is_root, display_name FROM users WHERE user_id = ?",
            (result["user_id"],)
        ).fetchone()
        conn.close()
        assert row[0] == "testroot"
        assert row[1] == 1  # is_root
        assert row[2] == "Test Root User"

    def test_passphrase_is_hashed(self, mock_config, root_creds):
        result = bootstrap_identity_store(mock_config, root_creds, "TestTenant")
        conn = sqlite3.connect(str(mock_config.data_dir / "identity.db"))
        row = conn.execute(
            "SELECT passphrase_hash, passphrase_salt FROM users WHERE user_id = ?",
            (result["user_id"],)
        ).fetchone()
        conn.close()
        # Hash should NOT be the plaintext passphrase
        assert row[0] != root_creds["passphrase"]
        # Salt should be a hex string
        assert len(row[1]) == 64  # 32 bytes = 64 hex chars

    def test_creates_system_roles(self, mock_config, root_creds):
        bootstrap_identity_store(mock_config, root_creds, "TestTenant")
        conn = sqlite3.connect(str(mock_config.data_dir / "identity.db"))
        roles = conn.execute("SELECT name FROM roles ORDER BY name").fetchall()
        conn.close()
        role_names = [r[0] for r in roles]
        assert "root" in role_names
        assert "admin" in role_names
        assert "user" in role_names


class TestBootstrapLexiconStorage:
    """Tests for Lexicon directory and file creation."""

    def test_creates_directory_structure(self, mock_config):
        bootstrap_lexicon_storage(mock_config, "tenant-123", "user-456", "TestUser")
        user_dir = mock_config.data_dir / "tenant-123" / "user-456"
        assert user_dir.exists()
        assert (user_dir / "l0_identity.yaml").exists()
        assert (user_dir / "memory.db").exists()
        assert (user_dir / "sessions").exists()
        assert (user_dir / "sessions").is_dir()

    def test_l0_identity_content(self, mock_config):
        bootstrap_lexicon_storage(mock_config, "t1", "u1", "Cash")
        import yaml
        l0_path = mock_config.data_dir / "t1" / "u1" / "l0_identity.yaml"
        with open(l0_path) as f:
            content = yaml.safe_load(f)
        assert content["identity"]["display_name"] == "Cash"
        assert content["preferences"]["tone"] == "direct"

    def test_memory_db_has_tables(self, mock_config):
        bootstrap_lexicon_storage(mock_config, "t1", "u1", "User")
        db_path = mock_config.data_dir / "t1" / "u1" / "memory.db"
        conn = sqlite3.connect(str(db_path))
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        conn.close()
        table_names = [t[0] for t in tables]
        assert "l1_episodes" in table_names
        assert "l2_semantics" in table_names
        assert "l3_procedures" in table_names
        assert "l4_strategic" in table_names
        assert "promotion_log" in table_names
