# File: tests/test_config.py
# Purpose: Unit tests for the configuration loader.

import os
from pathlib import Path
import pytest
import yaml

from pydantic import ValidationError
from aegis.config import load_config, AegisConfig

@pytest.fixture
def temp_config_file(tmp_path: Path) -> Path:
    """Create a temporary YAML config file for testing."""
    config_data = {
        "log_level": "DEBUG",
        "data_dir": "/tmp/yaml_data",
        "redis": {
            "host": "yaml_host",
            "port": 1111,
        },
        "api": {
            "port": 9999
        }
    }
    config_file = tmp_path / "test_config.yaml"
    with open(config_file, "w") as f:
        yaml.dump(config_data, f)
    return config_file

def test_load_from_yaml_file(temp_config_file: Path):
    """Test loading configuration purely from a YAML file."""
    config = load_config(temp_config_file)
    assert config.log_level == "DEBUG"
    assert config.redis.host == "yaml_host"
    assert config.redis.port == 1111
    assert config.api.port == 9999
    assert config.api.host == "127.0.0.1" # Default value

def test_env_var_override(temp_config_file: Path, monkeypatch):
    """Test that environment variables override YAML values."""
    monkeypatch.setenv("AEGIS_LOG_LEVEL", "WARNING")
    monkeypatch.setenv("AEGIS_REDIS__HOST", "env_host")
    monkeypatch.setenv("AEGIS_API__PORT", "8888")

    config = load_config(temp_config_file)

    assert config.log_level == "WARNING"
    assert config.redis.host == "env_host" # ENV overrides YAML
    assert config.redis.port == 1111       # YAML value is preserved
    assert int(config.api.port) == 8888    # ENV vars are strings, Pydantic casts them

def test_load_defaults_when_no_file_or_env(tmp_path: Path):
    """Test that Pydantic defaults are used when no other sources are present."""
    # Create an empty config file
    empty_file = tmp_path / "empty.yaml"
    with open(empty_file, "w") as f:
        yaml.dump({}, f)

    config = load_config(empty_file)

    # These should be the defaults from the AegisConfig model
    default_config = AegisConfig()
    assert config.log_level == default_config.log_level
    assert config.redis.host == default_config.redis.host
    assert config.data_dir == default_config.data_dir

def test_file_not_found_error():
    """Test that a FileNotFoundError is raised for a missing config file."""
    with pytest.raises(FileNotFoundError):
        load_config("non_existent_file.yaml")

def test_validation_error_for_bad_data(tmp_path: Path):
    """Test that a ValidationError is raised for invalid data types."""
    bad_config_file = tmp_path / "bad_config.yaml"
    with open(bad_config_file, "w") as f:
        # Port should be an integer, not a string
        yaml.dump({"redis": {"port": "not-a-number"}}, f)

    with pytest.raises(ValidationError):
        load_config(bad_config_file)
