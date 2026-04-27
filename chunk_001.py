# File: assemble_chunk_001.py
# Purpose: Standalone installation script for Project Aegis CHUNK-001.
# How to use: python assemble_chunk_001.py

import os
import textwrap
from pathlib import Path

# --- File Manifest & Content ---

FILE_MANIFEST = {
    "pyproject.toml": '''
        # File: pyproject.toml
        # Purpose: PEP 621 metadata, dependencies, and CLI entry point for Aegis.

        [build-system]
        requires = ["setuptools>=61.0"]
        build-backend = "setuptools.build_meta"

        [project]
        name = "aegis-system"
        version = "0.1.0"
        authors = [
          { name="Cash Vo", email="cash.vo@example.com" },
        ]
        description = "A local-first, multi-agent AI system."
        readme = "README.md"
        requires-python = ">=3.11"
        classifiers = [
            "Programming Language :: Python :: 3",
            "Programming Language :: Python :: 3.11",
            "Programming Language :: Python :: 3.12",
            "License :: OSI Approved :: MIT License",
            "Operating System :: OS Independent",
            "Topic :: Scientific/Engineering :: Artificial Intelligence",
        ]
        dependencies = [
            "pydantic>=2.7,<3.0",
            "pyyaml>=6.0",
            "structlog>=24.1",
            "typer[all]>=0.12",
            "redis>=5.0",
            "fastapi>=0.111",
            "uvicorn[standard]>=0.29",
            "apscheduler>=3.10",
            "mcp>=1.0", # Placeholder for Model Context Protocol
        ]

        [project.optional-dependencies]
        dev = [
            "pytest>=8.0",
            "pytest-asyncio>=0.23",
            "ruff>=0.4",
            "mypy>=1.9"
        ]

        [project.scripts]
        aegis = "aegis.main:cli_app"

        [tool.ruff]
        line-length = 88
        target-version = "py311"

        [tool.ruff.lint]
        select = ["E", "F", "W", "I", "UP"]

        [tool.setuptools.packages.find]
        where = ["."]
        include = ["aegis*"]
        exclude = ["tests*"]
    ''',
    "requirements.txt": '''
        # File: requirements.txt
        # Purpose: Pinned/compatible-release deps for reproducible environments.
        # Generated from pyproject.toml. Use `pip install -r requirements.txt`.

        pydantic==2.7.1
        pyyaml==6.0.1
        structlog==24.1.0
        typer==0.12.3
        redis==5.0.4
        fastapi==0.111.0
        uvicorn==0.29.0
        apscheduler==3.10.4
        # mcp is a placeholder, assuming a version
        # mcp==1.0.0
    ''',
    "aegis_config.yaml": '''
        # File: aegis_config.yaml
        # Purpose: Default config template. Values here are the lowest precedence.

        project_name: "aegis"
        version: "0.1.0"
        log_level: "INFO" # CRITICAL, ERROR, WARNING, INFO, DEBUG

        # Root directory for all persistent data, partitioned by tenant/user.
        data_dir: "aegis_data"

        # Redis connection for the message bus (CHUNK-002)
        redis:
          host: "127.0.0.1"
          port: 6379
          db: 0

        # API server configuration (for Janus agent, CHUNK-006)
        api:
          host: "127.0.0.1"
          port: 8000

        # Default timeout for agent request-response cycles.
        agent_timeout_s: 30
    ''',
    "README.md": '''
        # File: README.md
        # Purpose: Project overview, setup, and architecture summary.

        # Project Aegis

        Aegis is a local-first, multi-agent AI system designed for robust, secure, and extensible operation. It is built on an event-driven architecture and is designed to be multi-tenant from the ground up.

        ## Core Architecture
        - **Local-First:** No mandatory cloud dependencies. Runs on your own hardware.
        - **Python-Based:** Uses standard Python 3.11+ with a `venv`.
        - **Event-Driven:** Agents communicate asynchronously via a Redis message bus.
        - **Multi-Agent:** A council of specialized agents handles distinct tasks (Orchestration, Code Generation, Memory, Security, etc.).
        - **Multi-Tenant:** All data is strictly partitioned by `tenant_id` and `user_id`.

        ## Quick Setup

        1.  **Clone the repository:**
            ```bash
            git clone <repository_url>
            cd project-aegis
            ```

        2.  **Create and activate a virtual environment:**
            ```bash
            python -m venv .venv
            source .venv/bin/activate
            # On Windows: .venv\\Scripts\\activate
            ```

        3.  **Install in editable mode with development dependencies:**
            ```bash
            pip install -e ".[dev]"
            ```

        4.  **Run the main entry point:**
            This will load the configuration and confirm the system can start.
            ```bash
            python -m aegis.main
            ```
            or use the installed CLI script:
            ```bash
            aegis
            ```

        5.  **Run tests:**
            ```bash
            pytest
            ```

        ## Project Structure
        - `aegis/`: The main Python package.
          - `agents/`: Agent implementations, starting with `base.py`.
          - `schemas/`: Pydantic models for core data structures like `AegisMessage`.
          - `config/`: Configuration loading and validation.
          - `bus/`: (Forthcoming) Redis message bus implementation.
        - `tests/`: Unit and integration tests.
        - `pyproject.toml`: Project metadata and dependencies.
        - `aegis_config.yaml`: Default configuration file.
    ''',
    "CHANGELOG.md": '''
        # File: CHANGELOG.md
        # Purpose: Record of all changes by chunk/version.

        # Changelog

        All notable changes to this project will be documented in this file.

        ## [0.1.0] - CHUNK-001 - 2026-04-23

        ### Added
        - **Project Foundation:** Initialized the entire project structure.
        - **Core Schemas:**
          - `AegisMessage`, `MessageType`, `Priority` for inter-agent communication.
          - `AgentID` and `TierName` enums for canonical identifiers.
        - **Agent Base Class:** `BaseAgent` abstract base class to enforce agent contracts.
        - **Configuration Loader:**
          - `AegisConfig` typed Pydantic model.
          - Loader supports `aegis_config.yaml`, environment variables (`AEGIS_*`), and defaults.
        - **Entry Point:** `aegis.main` stub that loads config and prints a banner.
        - **Testing:** Unit tests for message serialization, config loading, and ABC enforcement.
        - **Dependencies:** `pyproject.toml` and `requirements.txt` defined with initial production and development dependencies.
        - **Documentation:** `README.md` with setup and `CHANGELOG.md`.
    ''',
    "aegis/__init__.py": '''
        # File: aegis/__init__.py
        # Purpose: Root package init; makes version accessible.

        __version__ = "0.1.0"
    ''',
    "aegis/__main__.py": '''
        # File: aegis/__main__.py
        # Purpose: Enables `python -m aegis` execution by forwarding to the main CLI app.

        from aegis.main import cli_app

        if __name__ == "__main__":
            cli_app()
    ''',
    "aegis/main.py": '''
        # File: aegis/main.py
        # Purpose: Entry point stub. Loads config, prints banner, exits.

        import structlog
        import typer
        from rich.console import Console
        from rich.panel import Panel

        from aegis.config import AegisConfig, load_config

        # Initialize a rich console for pretty printing
        console = Console()

        # Configure structured logging
        log = structlog.get_logger()

        # Create the Typer CLI application
        cli_app = typer.Typer(name="aegis")

        @cli_app.command()
        def main(
            config_file: str = typer.Option(
                "aegis_config.yaml",
                "--config",
                "-c",
                help="Path to the YAML configuration file.",
            )
        ):
            """
            Initializes and runs the Aegis System.

            This is the main entry point which will eventually start the System Manager
            and all configured agents. For now, it just loads configuration and
            displays a startup banner.
            """
            try:
                config = load_config(config_file)
                _print_banner(config)
            except FileNotFoundError:
                console.print(f"[bold red]Error:[/bold red] Configuration file not found at '{config_file}'.")
                raise typer.Exit(code=1)
            except Exception as e:
                console.print(f"[bold red]An unexpected error occurred during startup:[/bold red]\\n{e}")
                log.exception("Startup failed")
                raise typer.Exit(code=1)

            log.info("Aegis startup sequence complete (CHUNK-001 stub). Exiting.")

        def _print_banner(config: AegisConfig):
            """Prints a startup banner with key configuration details."""
            banner_text = (
                f"[bold cyan]Project Aegis[/bold cyan] [dim]v{config.version}[/dim]\\n"
                f"Local-First Multi-Agent System\\n"
                f"—"
            )
            config_details = (
                f" • [b]Log Level:[/b] {config.log_level}\\n"
                f" • [b]Data Dir:[/b]  {config.data_dir}\\n"
                f" • [b]Redis:[/b]      {config.redis.host}:{config.redis.port}\\n"
            )
            panel_content = f"{banner_text}\\n{config_details}"
            console.print(
                Panel(
                    panel_content,
                    title="[yellow]SYSTEM BOOT[/yellow]",
                    border_style="blue",
                    expand=False,
                )
            )

        if __name__ == "__main__":
            cli_app()
    ''',
    "aegis/schemas/__init__.py": '''
        # File: aegis/schemas/__init__.py
        # Purpose: Re-exports key models for easier imports.

        from .common import AgentID, TierName, stream_name, tenant_path
        from .message import AegisMessage, MessageType, Priority

        __all__ = [
            "AegisMessage",
            "MessageType",
            "Priority",
            "AgentID",
            "TierName",
            "stream_name",
            "tenant_path",
        ]
    ''',
    "aegis/schemas/message.py": '''
        # File: aegis/schemas/message.py
        # Purpose: Defines the core communication contract for all agents.

        import sys
        from datetime import datetime
        from enum import Enum
        from typing import Any, Optional
        from uuid import uuid4

        from pydantic import BaseModel, Field, ConfigDictd

        # Compatibility for Python < 3.12 `utcnow` deprecation
        if sys.version_info >= (3, 12):
            from datetime import UTC
            def utcnow():
                return datetime.now(UTC)
        else:
            # still available pre-3.12
            utcnow = datetime.utcnow

        class MessageType(str, Enum):
            """Defines the intent of the message."""
            REQUEST = "request"
            RESPONSE = "response"
            EVENT = "event"
            ERROR = "error"

        class Priority(str, Enum):
            """Defines the message processing priority."""
            LOW = "low"
            NORMAL = "normal"
            HIGH = "high"
            CRITICAL = "critical"

        class AegisMessage(BaseModel):
            """
            The canonical message structure for all inter-agent communication.
            Conforms to Genesis Spec Part II, Section 2.2.
            """
            message_id: str = Field(
                default_factory=lambda: str(uuid4()),
                description="Unique identifier for the message."
            )
            correlation_id: Optional[str] = Field(
                default=None,
                description="ID of the message this one is responding to or related to."
            )
            source_agent: str = Field(description="The ID of the agent sending the message.")
            target_agent: str = Field(description="The ID of the intended recipient agent.")
            message_type: MessageType = Field(description="The type of the message.")
            tenant_id: str = Field(description="The tenant context for this message.")
            user_id: str = Field(description="The user context for this message.")
            action: str = Field(description="The specific action the target agent should perform.")
            payload: dict[str, Any] = Field(
                default_factory=dict,
                description="A flexible payload containing action-specific data."
            )
            priority: Priority = Field(
                default=Priority.NORMAL,
                description="Message processing priority."
            )
            timestamp: datetime = Field(
                default_factory=utcnow,
                description="UTC timestamp of when the message was created."
            )
            ttl_seconds: Optional[int] = Field(
                default=300,
                description="Time-to-live in seconds before the message expires."
            )
            metadata: dict[str, Any] = Field(
                default_factory=dict,
                description="Extra metadata, e.g., for tracing or security."
            )

            model_config = ConfigDict(
                use_enum_values=True,
                from_attributes=True,
            )
    ''',
    "aegis/schemas/common.py": '''
        # File: aegis/schemas/common.py
        # Purpose: Shared enums and helper functions used across the system.

        from enum import Enum
        from pathlib import Path

        class AgentID(str, Enum):
            """
            Canonical identifiers for all agents in the Aegis Council, plus the observer.
            Conforms to Genesis Spec Part II, Section 2.1.
            """
            # Council Members
            ORCHESTRATOR = "t_orchestrator"
            FORGE = "forge"
            ORACLE = "oracle"
            WARDEN = "warden"
            LEXICON = "lexicon"
            JANUS = "janus"
            IDENTITY = "identity"
            # Non-council
            OBSERVER = "observer"

        class TierName(str, Enum):
            """
            Defines the hierarchy of memory and identity storage.
            Conforms to Genesis Spec Part IV, Section 4.2 (naming implied).
            """
            L0 = "l0_identity.yaml"
            L1 = "l1_context"
            L2 = "l2_episodic"
            L3 = "l3_semantic"
            L4 = "l4_procedural"
            L5 = "l5_archive"

        def stream_name(agent_id: AgentID | str) -> str:
            """
            Generates the canonical Redis stream key for an agent's inbound channel.

            Args:
                agent_id: The ID of the agent.

            Returns:
                The formatted Redis stream key string.
            """
            id_val = agent_id.value if isinstance(agent_id, AgentID) else agent_id
            return f"aegis:stream:{id_val}"

        def tenant_path(data_dir: str | Path, tenant_id: str, user_id: str) -> Path:
            """
            Constructs the standardized data path for a given user within a tenant.
            Conforms to Genesis Spec Part IV, Section 4.2.

            Args:
                data_dir: The root data directory from AegisConfig.
                tenant_id: The tenant's unique identifier.
                user_id: The user's unique identifier.

            Returns:
                A Path object to the user's data directory.
            """
            return Path(data_dir) / tenant_id / user_id
    ''',
    "aegis/agents/__init__.py": '''
        # File: aegis/agents/__init__.py
        # Purpose: Agents subpackage.

        from .base import BaseAgent

        __all__ = ["BaseAgent"]
    ''',
    "aegis/agents/base.py": '''
        # File: aegis/agents/base.py
        # Purpose: Defines the Abstract Base Class for all Aegis agents.

        from abc import ABC, abstractmethod

        from aegis.schemas import AgentID, AegisMessage

        class BaseAgent(ABC):
            """
            Abstract base class for all Aegis agents, enforcing a common contract.
            Conforms to Genesis Spec Part II, Section 2.3, with a concrete __init__.
            """

            def __init__(self, agent_id: AgentID, subscriptions: list[str] | None = None):
                """
                Initializes the agent.

                Args:
                    agent_id: The canonical ID of the agent.
                    subscriptions: A list of message actions or channels this agent listens to.
                """
                self.agent_id: AgentID = agent_id
                self.subscriptions: list[str] = subscriptions or []

            @abstractmethod
            async def handle_message(self, message: AegisMessage) -> AegisMessage | None:
                """
                Process an incoming message and optionally return a response message.

                This is the primary message handling logic for any agent.

                Args:
                    message: The incoming AegisMessage to process.

                Returns:
                    An optional AegisMessage to be sent as a response, or None.
                """
                ...

            @abstractmethod
            async def startup(self) -> None:
                """
                Agent initialization logic.

                Called once when the system starts. Use for loading configuration,
                connecting to resources, or subscribing to message bus channels.
                """
                ...

            @abstractmethod
            async def shutdown(self) -> None:
                """
                Graceful teardown logic.

                Called once when the system is shutting down. Use for releasing
                resources or performing cleanup tasks.
                """
                ...
    ''',
    "aegis/config/__init__.py": '''
        # File: aegis/config/__init__.py
        # Purpose: Config subpackage; re-exports key objects.

        from .loader import AegisConfig, APIConfig, RedisConfig, load_config

        __all__ = ["load_config", "AegisConfig", "RedisConfig", "APIConfig"]
    ''',
    "aegis/config/loader.py": '''
        # File: aegis/config/loader.py
        # Purpose: Handles loading config from YAML and merging with ENV overrides.

        import os
        from pathlib import Path
        from typing import Any

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

        class AegisConfig(BaseModel):
            """Typed configuration model for the entire Aegis system."""
            project_name: str = "aegis"
            version: str = "0.1.0"
            log_level: str = "INFO"
            data_dir: str = "aegis_data"
            redis: RedisConfig = RedisConfig()
            api: APIConfig = APIConfig()
            agent_timeout_s: int = 30

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
                print(f"Configuration validation error:\\n{e}")
                raise
    ''',
    "aegis/bus/__init__.py": '''
        # File: aegis/bus/__init__.py
        # Purpose: Placeholder for CHUNK-002 (Redis Message Bus).

        """
        This package will contain the Redis-based message bus implementation.
        (Target: CHUNK-002)
        """
    ''',
    "aegis/storage/__init__.py": '''
        # File: aegis/storage/__init__.py
        # Purpose: Placeholder for the storage layer.

        """
        This package will contain the data storage and retrieval logic, likely
        interacting with the file system and a vector database.
        """
    ''',
    "aegis/utils/__init__.py": '''
        # File: aegis/utils/__init__.py
        # Purpose: Placeholder for shared utility functions.

        """
        This package will contain shared utility functions, such as custom logging
        formatters, decorators, or other helper classes.
        """
    ''',
    "aegis/services/__init__.py": '''
        # File: aegis/services/__init__.py
        # Purpose: Placeholder for external-facing services (e.g., Janus API).

        """
        This package will contain services exposed to the outside world,
        such as the FastAPI application for the Janus agent.
        """
    ''',
    "tests/__init__.py": '''
        # File: tests/__init__.py
        # Purpose: Test package initializer.

        """
        Unit and integration tests for the Aegis system.
        Run with `pytest`.
        """
    ''',
    "tests/test_message.py": '''
        # File: tests/test_message.py
        # Purpose: Unit tests for AegisMessage serialization and defaults.

        import pytest
        from uuid import UUID
        from datetime import datetime, timedelta, timezone

        from aegis.schemas import AegisMessage, MessageType, Priority

        # Helper for consistent UTC timestamps
        def get_utc_now():
            if hasattr(timezone, 'utc'):
                return datetime.now(timezone.utc)
            else:
                return datetime.utcnow()

        def test_aegis_message_creation_with_required_fields():
            """Verify that a message can be created with only the required fields."""
            msg = AegisMessage(
                source_agent="test_source",
                target_agent="test_target",
                message_type=MessageType.REQUEST,
                tenant_id="t-1",
                user_id="u-1",
                action="test.action",
            )
            assert msg.source_agent == "test_source"
            assert msg.action == "test.action"
            assert msg.priority == Priority.NORMAL # Default value
            assert msg.payload == {} # Default value

        def test_aegis_message_auto_generates_fields():
            """Check that message_id and timestamp are auto-generated."""
            msg1 = AegisMessage(
                source_agent="test", target_agent="test", message_type="request",
                tenant_id="t", user_id="u", action="a"
            )
            msg2 = AegisMessage(
                source_agent="test", target_agent="test", message_type="request",
                tenant_id="t", user_id="u", action="a"
            )

            # Verify message_id is a valid UUID string
            assert isinstance(UUID(msg1.message_id), UUID)
            assert msg1.message_id != msg2.message_id

            # Verify timestamp is a recent datetime object
            assert isinstance(msg1.timestamp, datetime)
            assert get_utc_now() - msg1.timestamp < timedelta(seconds=2)

        def test_aegis_message_serialization_deserialization_roundtrip():
            """Ensure a message can be serialized to JSON and back without data loss."""
            original_msg = AegisMessage(
                source_agent="forge",
                target_agent="oracle",
                message_type=MessageType.REQUEST,
                tenant_id="tenant-abc",
                user_id="user-123",
                action="generate.code",
                payload={"language": "python", "spec": "create a function"},
                priority=Priority.HIGH,
                correlation_id="corr-456"
            )

            # Pydantic v2 serialization
            json_str = original_msg.model_dump_json()
            
            # Pydantic v2 deserialization
            rehydrated_msg = AegisMessage.model_validate_json(json_str)

            assert original_msg == rehydrated_msg
            assert rehydrated_msg.priority == Priority.HIGH
            assert rehydrated_msg.payload["language"] == "python"

        def test_invalid_message_type_raises_error():
            """Verify that an invalid message_type fails validation."""
            with pytest.raises(ValueError):
                AegisMessage(
                    source_agent="test", target_agent="test", message_type="INVALID_TYPE",
                    tenant_id="t", user_id="u", action="a"
                )
    ''',
    "tests/test_common.py": '''
        # File: tests/test_common.py
        # Purpose: Unit tests for common enums and helpers.

        from pathlib import Path
        import pytest
        from aegis.schemas import AgentID, TierName, stream_name, tenant_path

        def test_agent_id_enum_contains_all_agents():
            """Verify AgentID has all 7 council agents + observer."""
            expected_agents = {
                "ORCHESTRATOR", "FORGE", "ORACLE", "WARDEN",
                "LEXICON", "JANUS", "IDENTITY", "OBSERVER"
            }
            assert set(AgentID.__members__.keys()) == expected_agents

        @pytest.mark.parametrize("agent_id, expected_stream", [
            (AgentID.WARDEN, "aegis:stream:warden"),
            (AgentID.ORCHESTRATOR, "aegis:stream:t_orchestrator"),
            ("forge", "aegis:stream:forge"), # Also test with raw string
        ])
        def test_stream_name_helper(agent_id, expected_stream):
            """Test the stream name generation helper function."""
            assert stream_name(agent_id) == expected_stream

        def test_tier_name_enum_has_correct_values():
            """Verify TierName values match the spec."""
            assert TierName.L0.value == "l0_identity.yaml"
            assert TierName.L1.value == "l1_context"

        def test_tenant_path_helper():
            """Test the tenant path generation helper."""
            base_dir = "/tmp/aegis_test"
            tenant = "tenant-xyz"
            user = "user-789"
            
            expected = Path(f"{base_dir}/{tenant}/{user}")
            
            assert tenant_path(base_dir, tenant, user) == expected
            assert tenant_path(Path(base_dir), tenant, user) == expected
    ''',
    "tests/test_config.py": '''
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
    ''',
    "tests/test_base_agent.py": '''
        # File: tests/test_base_agent.py
        # Purpose: Tests BaseAgent ABC contract enforcement.

        import pytest
        from aegis.agents import BaseAgent
        from aegis.schemas import AgentID, AegisMessage

        # Define a minimal concrete implementation for testing
        class ConcreteAgent(BaseAgent):
            async def handle_message(self, message: AegisMessage) -> AegisMessage | None:
                return None
            async def startup(self) -> None:
                pass
            async def shutdown(self) -> None:
                pass

        def test_concrete_agent_instantiation():
            """Verify a correct concrete class can be instantiated."""
            agent = ConcreteAgent(agent_id=AgentID.FORGE, subscriptions=["test.action"])
            assert agent.agent_id == AgentID.FORGE
            assert agent.subscriptions == ["test.action"]

        def test_missing_handle_message_raises_type_error():
            """Test that failing to implement handle_message raises TypeError."""
            with pytest.raises(TypeError, match="Can't instantiate abstract class"):
                class IncompleteAgent(BaseAgent):
                    # Missing handle_message
                    async def startup(self) -> None: pass
                    async def shutdown(self) -> None: pass
                
                IncompleteAgent(agent_id=AgentID.FORGE)

        def test_missing_startup_raises_type_error():
            """Test that failing to implement startup raises TypeError."""
            with pytest.raises(TypeError, match="Can't instantiate abstract class"):
                class IncompleteAgent(BaseAgent):
                    async def handle_message(self, message: AegisMessage) -> None: pass
                    # Missing startup
                    async def shutdown(self) -> None: pass

                IncompleteAgent(agent_id=AgentID.FORGE)

        def test_missing_shutdown_raises_type_error():
            """Test that failing to implement shutdown raises TypeError."""
            with pytest.raises(TypeError, match="Can't instantiate abstract class"):
                class IncompleteAgent(BaseAgent):
                    async def handle_message(self, message: AegisMessage) -> None: pass
                    async def startup(self) -> None: pass
                    # Missing shutdown

                IncompleteAgent(agent_id=AgentID.FORGE)
    '''
}

def main():
    """
    Main function to create the CHUNK-001 project structure.
    """
    print("--- Starting Project Aegis CHUNK-001 Assembly ---")
    root = Path(".")
    
    total_files = len(FILE_MANIFEST)
    files_created = 0
    
    for file_path_str, content in FILE_MANIFEST.items():
        try:
            file_path = root / file_path_str
            
            # Ensure parent directory exists
            file_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Write the file content
            print(f"Writing file: {file_path}")
            file_path.write_text(
                textwrap.dedent(content).strip() + "\n",
                encoding="utf-8",
                newline="\n",
            )
            files_created += 1
        except Exception as e:
            print(f"!!! ERROR creating file {file_path_str}: {e}")
            
    print("\n--- Assembly Complete ---")
    if files_created == total_files:
        print(f"Successfully created {files_created}/{total_files} files.")
        print("\nNext steps:")
        print("1. Create a virtual environment: python -m venv .venv")
        print("2. Activate it: source .venv/bin/activate")
        print("3. Install dependencies: pip install -e '.[dev]'")
        print("4. Run the startup check: aegis")
        print("5. Run tests: pytest")
    else:
        print(f"Warning: Only {files_created}/{total_files} files were created due to errors.")

if __name__ == "__main__":
    main()