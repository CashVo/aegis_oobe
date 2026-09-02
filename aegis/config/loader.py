# File: aegis/config/loader.py
# Purpose: Handles loading config from YAML and merging with ENV overrides.

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from pydantic import BaseModel, ValidationError

class RedisConfig(BaseModel):
    """Configuration for Redis connection."""
    host: str = "127.0.0.1"
    port: int = 6379
    db: int = 0

class APIConfig(BaseModel):
    """Configuration for the API server (Janus)."""
    host: str = "127.0.0.1"
    port: int = 8000

class OracleModelConfig(BaseModel):
    """Configuration for an Oracle model."""
    llm_id: str
    provider: str
    display_name: str
    context_window: int
    preference_tags: List[str] = []
    supports_json_mode: bool = False
    supports_embeddings: bool = False
    max_output_tokens: int = 4096

class OracleProviderConfig(BaseModel):
    """Configuration for an Oracle provider."""
    provider_type: str
    base_url: str
    enabled: bool = True
    timeout_seconds: int = 60
    max_concurrent: int = 4
    max_retries: int = 3
    api_key_env: Optional[str] = None
    default_model: Optional[str] = None

class OracleConfig(BaseModel):
    """Configuration for the Oracle LLM Gateway."""
    max_concurrent_requests: int = 8
    default_model: str = "nemotron-3-ultra-550b"
    providers: Dict[str, OracleProviderConfig] = {}
    models: Dict[str, OracleModelConfig] = {}
    cache: Dict[str, Any] = {}
    rate_limit: Dict[str, Any] = {}
    token_budget: Dict[str, Any] = {}
    templates: Dict[str, Any] = {}
    request_timeout_seconds: int = 120
    fallback_order: List[str] = ["ollama", "openrouter"]

class AegisConfig(BaseModel):
    """Typed configuration model for the entire Aegis system."""
    project_name: str = "aegis"
    version: str = "0.1.0"
    log_level: str = "INFO"
    data_dir: str = "aegis_data"
    redis: RedisConfig = RedisConfig()
    api: APIConfig = APIConfig()
    agent_timeout_s: int = 30
    oracle: OracleConfig = OracleConfig()

def _load_env_vars(prefix: str) -> dict[str, Any]:
    """Loads and parses environment variables with a specific prefix."""
    env_vars = {}
    for key, value in os.environ.items():
        if key.startswith(prefix):
            # Remove prefix, convert to lower case
            key_path = key[len(prefix):].lower()
            # Split by double underscore for nesting
            parts = key_path.split("__")

            d = env_vars
            for part in parts[:-1]:
                d = d.setdefault(part, {})
            d[parts[-1]] = value

    return env_vars

def load_config(
    config_path: str | Path = "aegis_config.yaml",
    env_prefix: str = "AEGIS_",
) -> AegisConfig:
    """
    Loads configuration with a clear precedence: ENV > YAML > Defaults.

    Args:
        config_path: Path to the YAML configuration file.
        env_prefix: Prefix for environment variables (e.g., "AEGIS_").

    Returns:
        A populated and validated AegisConfig object.

    Raises:
        FileNotFoundError: If the config_path does not exist.
        ValidationError: If the final merged configuration is invalid.
    """
    # 1. Start with Pydantic defaults
    # (This happens automatically on model instantiation)

    # 2. Load from YAML file if it exists
    path = Path(config_path)
    if not path.is_file():
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(path, "r") as f:
        yaml_config = yaml.safe_load(f) or {}

    # 3. Load from environment variables
    env_config = _load_env_vars(env_prefix)

    # 4. Merge configurations: env overrides yaml
    # A simple dict update won't work for nested models. We need a deep merge.
    def deep_merge(source, destination):
        for key, value in source.items():
            if isinstance(value, dict):
                node = destination.setdefault(key, {})
                deep_merge(value, node)
            else:
                destination[key] = value
        return destination

    merged_config = deep_merge(yaml_config, {})
    merged_config = deep_merge(env_config, merged_config)

    # 5. Validate and return the final config
    try:
        return AegisConfig.model_validate(merged_config)
    except ValidationError as e:
        print(f"Configuration validation error:\n{e}")
        raise
