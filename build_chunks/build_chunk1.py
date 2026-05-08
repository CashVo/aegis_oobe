# AMCP Assembly-Only Build — CHUNK-001: Base Layout & Schemas

```python
# build_chunk_001.py
#
# Project Aegis — AMCP Assembly: CHUNK-001 (Base Layout & Schemas)
# Run from the root of your project-aegis directory.
# Creates the foundational project structure, schemas, and configuration system.
#
# Implements: Part I (Core Principles), Part II §2.2-2.3, Part III §3.3 (partial),
#             Part IX §9.4, Part XIV (CHUNK-001 deliverables)

import os
import textwrap

# --- File Manifest ---
CHUNK_1_FILES = {

    # ===================================================================
    # PROJECT ROOT FILES
    # ===================================================================

    "pyproject.toml": '''
[build-system]
requires = ["setuptools>=68.0", "wheel"]
build-backend = "setuptools.backends._legacy:_Backend"

[project]
name = "project-aegis"
version = "0.1.0"
description = "Project Aegis — A local-first, multi-agent AI system."
readme = "README.md"
license = {text = "Proprietary"}
requires-python = ">=3.11"
authors = [
    {name = "Cash Vo", email = "cash@aegis.local"}
]

dependencies = [
    "pydantic>=2.5.0",
    "pyyaml>=6.0",
    "redis>=5.0.0",
    "structlog>=23.2.0",
    "click>=8.1.0",
    "fastapi>=0.104.0",
    "uvicorn>=0.24.0",
    "apscheduler>=4.0.0a4",
    "httpx>=0.25.0",
    "mcp>=0.1.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.4.0",
    "pytest-asyncio>=0.23.0",
    "pytest-cov>=4.1.0",
    "ruff>=0.1.0",
]

[project.scripts]
aegis = "aegis.cli:main"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"

[tool.ruff]
line-length = 100
target-version = "py311"
''',

    "requirements.txt": '''
# Project Aegis — Core Dependencies
pydantic>=2.5.0
pyyaml>=6.0
redis>=5.0.0
structlog>=23.2.0
click>=8.1.0
fastapi>=0.104.0
uvicorn>=0.24.0
apscheduler>=4.0.0a4
httpx>=0.25.0

# Dev Dependencies
pytest>=7.4.0
pytest-asyncio>=0.23.0
pytest-cov>=4.1.0
ruff>=0.1.0
''',

    "aegis_config.yaml": '''
# ═══════════════════════════════════════════════════════════════
# Project Aegis — Master Configuration
# ═══════════════════════════════════════════════════════════════
# Precedence: CLI flags > Environment Variables > This File > Defaults
# Env var override pattern: AEGIS_<SECTION>_<KEY> (e.g., AEGIS_REDIS_HOST)
# ═══════════════════════════════════════════════════════════════

system:
  name: "Project Aegis"
  version: "0.1.0"
  environment: "development"  # development | staging | production
  debug: true
  log_level: "DEBUG"  # DEBUG | INFO | WARNING | ERROR | CRITICAL
  data_dir: "aegis_data"  # Root directory for all persistent data

redis:
  host: "localhost"
  port: 6379
  db: 0
  password: null  # Set via AEGIS_REDIS_PASSWORD env var in production
  socket_timeout: 5
  retry_on_timeout: true
  stream_max_len: 10000  # Max entries per stream before trimming
  consumer_group: "aegis_agents"

agents:
  message_ttl_seconds: 300  # Default TTL for inter-agent messages
  heartbeat_interval_seconds: 30
  restart_max_retries: 3
  restart_backoff_seconds: 5
  startup_order:
    - "observer"
    - "warden"
    - "identity"
    - "lexicon"
    - "janus"
    - "oracle"
    - "forge"
    - "torchestrator"

oracle:
  default_model: "local"  # Model alias (configured per deployment)
  temperature: 0.7
  max_tokens: 2000
  request_timeout_seconds: 120
  cache_enabled: true
  cache_ttl_seconds: 3600

lexicon:
  context_token_budget: 4000
  l3_retention_days: 365
  l5_session_ttl_seconds: 7200  # 2 hours
  promotion_check_interval_seconds: 3600

forge:
  tool_timeout_seconds: 30
  skill_timeout_seconds: 120
  shell_allowlist:
    - "git"
    - "ls"
    - "cat"
    - "echo"
    - "mkdir"
    - "cp"
    - "mv"
    - "rm"
    - "python"
    - "pip"

scheduler:
  job_store_path: "aegis_data/scheduler_jobs.db"
  misfire_grace_seconds: 60

web:
  host: "localhost"
  port: 8420
  cors_origins:
    - "http://localhost:8420"
''',

    "CHANGELOG.md": '''
# Changelog

All notable changes to Project Aegis will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-05-05

### Added
- **CHUNK-001: Base Layout & Schemas** — Foundation layer.
  - Project structure with `pyproject.toml` and `src/` layout.
  - `AegisMessage` schema with full Pydantic v2 model (Part II §2.2).
  - `BaseAgent` abstract base class (Part II §2.3).
  - Configuration loader with YAML + env var + CLI override precedence (RT-2).
  - `aegis_config.yaml` master configuration template.
  - `AMCPChunk` contract model (Part IX §9.4).
  - Unit tests for all foundation components.
''',

    "README.md": '''
# Project Aegis

> A local-first, multi-agent AI system engineered for deliberate success.

**Version:** 0.1.0 (Genesis Build)
**Author:** Cash Vo
**Architecture:** Event-driven, multi-agent, multi-tenant

---

## Core Principles

1. **Local-First** — All computation runs on your machine. No mandatory cloud.
2. **Event-Driven & Asynchronous** — Redis Streams message bus.
3. **Multi-Agent Architecture** — 7 specialized council agents.
4. **Multi-Tenant by Design** — Data partitioned from day zero.
5. **Security as First-Class Citizen** — Every operation is Warden-gated.

## Quick Start

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\\Scripts\\activate  # Windows

# Install in development mode
pip install -e ".[dev]"

# Verify installation
python -m aegis.main
```

## Project Structure

```
project-aegis/
├── src/aegis/          # Source code
│   ├── schemas/        # Pydantic message contracts
│   ├── agents/         # Agent base classes and implementations
│   ├── config/         # Configuration loading system
│   └── main.py         # System entry point
├── tests/              # Test suite
├── aegis_config.yaml   # Master configuration
└── aegis_data/         # Runtime data (created at startup)
```

## Build Protocol

This project is built using the **Aegis Master Construction Protocol (AMCP)**.
See the Genesis OOBE Directive for full specification.

## License

Proprietary — Cash Vo. All rights reserved.
''',

    # ===================================================================
    # SOURCE: src/aegis/
    # ===================================================================

    "src/aegis/__init__.py": '''
"""
Project Aegis — A local-first, multi-agent AI system.

This is the top-level package for the Aegis system.
"""

__version__ = "0.1.0"
__project__ = "Project Aegis"
''',

    "src/aegis/__main__.py": '''
"""
Allows running Aegis via: python -m aegis
"""
from aegis.main import main

if __name__ == "__main__":
    main()
''',

    "src/aegis/main.py": '''
"""
Project Aegis — System Entry Point

Implements: Part III §3.3 — System Manager entry point.
The System Manager will be fully built in CHUNK-011.
This module provides the bootstrap entry point.
"""

import sys


def main() -> None:
    """
    Main entry point for the Aegis system.

    In CHUNK-001, this validates that the foundation is correctly installed.
    Full System Manager bootstrap logic will be implemented in CHUNK-011.
    """
    from aegis import __version__, __project__
    from aegis.config.loader import load_config

    print(f"{'═' * 60}")
    print(f"  {__project__} v{__version__}")
    print(f"  Status: Foundation Installed (CHUNK-001)")
    print(f"{'═' * 60}")

    # Validate configuration loads correctly
    try:
        config = load_config()
        print(f"  ✓ Configuration loaded: {config.system.name}")
        print(f"  ✓ Environment: {config.system.environment}")
        print(f"  ✓ Data directory: {config.system.data_dir}")
        print(f"  ✓ Redis target: {config.redis.host}:{config.redis.port}")
        print(f"{'═' * 60}")
        print(f"  System Manager not yet active (pending CHUNK-011).")
        print(f"  Run 'pytest' to verify all foundation tests pass.")
        print(f"{'═' * 60}")
    except Exception as e:
        print(f"  ✗ Configuration error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
''',

    # ===================================================================
    # SOURCE: src/aegis/schemas/
    # ===================================================================

    "src/aegis/schemas/__init__.py": '''
"""
Aegis Schemas Package

Canonical Pydantic models for all inter-agent communication contracts.
"""

from aegis.schemas.message import (
    AegisMessage,
    MessageType,
    Priority,
)
from aegis.schemas.amcp import AMCPChunk, AMCPStatus

__all__ = [
    "AegisMessage",
    "MessageType",
    "Priority",
    "AMCPChunk",
    "AMCPStatus",
]
''',

    "src/aegis/schemas/message.py": '''
"""
Aegis Message Schema — The Universal Agent Communication Envelope

Implements: Part II, §2.2 — Agent Communication Contract

All inter-agent messages on the Redis Streams bus conform to this standard
envelope. This is the atomic unit of communication in the Aegis system.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    """Return current UTC datetime (timezone-aware)."""
    return datetime.now(timezone.utc)


class MessageType(str, Enum):
    """
    Categorizes the purpose of an inter-agent message.

    - REQUEST: Agent is asking another agent to perform an action.
    - RESPONSE: Agent is replying to a previous REQUEST.
    - EVENT: Agent is broadcasting a state change or notification.
    - ERROR: Agent is reporting a failure condition.
    """
    REQUEST = "request"
    RESPONSE = "response"
    EVENT = "event"
    ERROR = "error"


class Priority(str, Enum):
    """
    Message priority levels for processing order.

    Higher priority messages are processed before lower priority
    messages in agent queues.
    """
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class AegisMessage(BaseModel):
    """
    The universal message envelope for all inter-agent communication.

    Every message published to the Redis Streams bus MUST conform to this
    schema. This ensures type safety, traceability, and consistent
    processing across all agents.

    Attributes:
        message_id: Unique identifier for this specific message instance.
        correlation_id: Links a RESPONSE back to its originating REQUEST.
            Enables request-response tracking across async boundaries.
        source_agent: The agent_id of the sender.
        target_agent: The agent_id of the intended recipient.
            Use "broadcast" for system-wide events.
        message_type: Categorizes the message purpose.
        tenant_id: Scopes the message to a specific tenant (multi-tenancy).
        user_id: Scopes the message to a specific user within the tenant.
        action: The specific operation being requested or reported.
            Convention: "{agent}.{verb}" (e.g., "forge.execute_tool").
        payload: Arbitrary data associated with the action.
        priority: Processing priority level.
        timestamp: UTC timestamp of message creation.
        ttl_seconds: Time-to-live. Message expires after this duration.
            Expired messages should be discarded by consumers.
        metadata: Additional context for tracing, debugging, or routing.
            Common keys: session_id, trace_id, retry_count.
    """

    message_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="Unique identifier for this message instance."
    )
    correlation_id: Optional[str] = Field(
        default=None,
        description="Links response to originating request."
    )
    source_agent: str = Field(
        ...,
        description="Agent ID of the sender."
    )
    target_agent: str = Field(
        ...,
        description="Agent ID of the recipient. Use 'broadcast' for all."
    )
    message_type: MessageType = Field(
        ...,
        description="The category of this message."
    )
    tenant_id: str = Field(
        ...,
        description="Tenant scope for multi-tenancy isolation."
    )
    user_id: str = Field(
        ...,
        description="User scope within the tenant."
    )
    action: str = Field(
        ...,
        description="The operation: '{agent}.{verb}' convention."
    )
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Action-specific data."
    )
    priority: Priority = Field(
        default=Priority.NORMAL,
        description="Processing priority."
    )
    timestamp: datetime = Field(
        default_factory=_utcnow,
        description="UTC creation timestamp."
    )
    ttl_seconds: Optional[int] = Field(
        default=300,
        description="Time-to-live in seconds. None = no expiry."
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Tracing and routing metadata."
    )

    def is_expired(self) -> bool:
        """Check if this message has exceeded its TTL."""
        if self.ttl_seconds is None:
            return False
        elapsed = (datetime.now(timezone.utc) - self.timestamp).total_seconds()
        return elapsed > self.ttl_seconds

    def create_response(
        self,
        source_agent: str,
        payload: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> "AegisMessage":
        """
        Create a response message correlated to this request.

        Args:
            source_agent: The agent creating the response.
            payload: Response data.
            error: Error message if this is an error response.

        Returns:
            A new AegisMessage with correlation_id set and appropriate type.
        """
        msg_type = MessageType.ERROR if error else MessageType.RESPONSE
        response_payload = payload or {}
        if error:
            response_payload["error"] = error

        return AegisMessage(
            correlation_id=self.message_id,
            source_agent=source_agent,
            target_agent=self.source_agent,
            message_type=msg_type,
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            action=f"{self.action}.response",
            payload=response_payload,
            priority=self.priority,
            metadata={
                **self.metadata,
                "original_action": self.action,
            },
        )

    def to_bus_dict(self) -> dict[str, str]:
        """
        Serialize to a flat dict suitable for Redis Streams XADD.

        Redis Streams require field values to be strings.
        We store the full model as a JSON string under the 'data' key.
        """
        return {"data": self.model_dump_json()}

    @classmethod
    def from_bus_dict(cls, data: dict[str, str]) -> "AegisMessage":
        """
        Deserialize from a Redis Streams entry.

        Args:
            data: Dict with 'data' key containing JSON string.

        Returns:
            Reconstructed AegisMessage instance.
        """
        return cls.model_validate_json(data["data"])
''',

    "src/aegis/schemas/amcp.py": '''
"""
AMCP Chunk Contract Schema

Implements: Part IX, §9.4 — AMCP Chunk Contract

Defines the data model for tracking AMCP build chunk status.
Used by the build system to enforce sequencing and dependencies.
"""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class AMCPStatus(str, Enum):
    """Status progression of an AMCP chunk through the build pipeline."""
    START = "START"
    ARCHITECT = "ARCHITECT"
    AUTOFILE = "AUTOFILE"
    ASSEMBLE = "ASSEMBLE"
    RELEASE = "RELEASE"


class AMCPChunk(BaseModel):
    """
    Represents a single AMCP build chunk.

    Each chunk is an atomic unit of work in the Aegis build plan.
    Chunks have strict dependency ordering — a chunk cannot begin
    AUTOFILE until all its dependencies have reached RELEASE status.

    Attributes:
        chunk_id: Unique identifier (e.g., "CHUNK-001").
        name: Human-readable name (e.g., "Base Layout & Schemas").
        description: What this chunk delivers.
        dependencies: List of chunk_ids that must be RELEASED first.
        acceptance_criteria: Conditions that must be true to RELEASE.
        files_manifest: Expected file paths produced by this chunk.
        status: Current AMCP phase status.
    """

    chunk_id: str = Field(
        ...,
        description="Unique chunk identifier (e.g., 'CHUNK-001')."
    )
    name: str = Field(
        ...,
        description="Human-readable chunk name."
    )
    description: str = Field(
        default="",
        description="What this chunk delivers to the system."
    )
    dependencies: list[str] = Field(
        default_factory=list,
        description="Chunk IDs that must reach RELEASE before this chunk starts."
    )
    acceptance_criteria: list[str] = Field(
        default_factory=list,
        description="All conditions must be true to RELEASE."
    )
    files_manifest: list[str] = Field(
        default_factory=list,
        description="File paths this chunk produces."
    )
    status: AMCPStatus = Field(
        default=AMCPStatus.START,
        description="Current build phase status."
    )

    def can_start(self, released_chunks: set[str]) -> bool:
        """
        Check if all dependencies are satisfied.

        Args:
            released_chunks: Set of chunk_ids that have reached RELEASE.

        Returns:
            True if all dependencies are in the released set.
        """
        return all(dep in released_chunks for dep in self.dependencies)

    def advance(self) -> Optional["AMCPStatus"]:
        """
        Advance to the next AMCP phase.

        Returns:
            The new status, or None if already at RELEASE.
        """
        progression = list(AMCPStatus)
        current_idx = progression.index(self.status)
        if current_idx < len(progression) - 1:
            self.status = progression[current_idx + 1]
            return self.status
        return None
''',

    # ===================================================================
    # SOURCE: src/aegis/agents/
    # ===================================================================

    "src/aegis/agents/__init__.py": '''
"""
Aegis Agents Package

Base classes and implementations for all Aegis council agents.
"""

from aegis.agents.base import BaseAgent

__all__ = ["BaseAgent"]
''',

    "src/aegis/agents/base.py": '''
"""
Aegis Base Agent — Abstract Base Class for All Council Agents

Implements: Part II, §2.3 — Agent Base Class

Every agent in the Aegis system inherits from this ABC. It enforces
the contract that all agents must implement message handling, startup,
and shutdown lifecycle methods.
"""

from abc import ABC, abstractmethod
from typing import Optional

from aegis.schemas.message import AegisMessage


class BaseAgent(ABC):
    """
    Abstract base class for all Aegis agents.

    All council agents (TOrchestrator, Forge, Oracle, Warden, Lexicon,
    Janus, Identity) and service agents (Observer) inherit from this class.

    Subclasses MUST implement:
        - handle_message: Process incoming messages from the bus.
        - startup: Initialize the agent (subscribe to channels, load state).
        - shutdown: Graceful teardown (unsubscribe, flush state).

    Attributes:
        agent_id: Unique identifier for this agent instance.
            Convention: lowercase, no spaces (e.g., "warden", "torchestrator").
        subscriptions: List of Redis Stream channels this agent listens to.
            Every agent subscribes to at minimum its own stream:
            "aegis:stream:{agent_id}"
    """

    agent_id: str
    subscriptions: list[str]

    def __init__(self, agent_id: str, subscriptions: Optional[list[str]] = None):
        """
        Initialize the base agent.

        Args:
            agent_id: Unique identifier for this agent.
            subscriptions: List of bus channels to subscribe to.
                Defaults to ["aegis:stream:{agent_id}", "aegis:stream:broadcast"].
        """
        self.agent_id = agent_id
        self.subscriptions = subscriptions or [
            f"aegis:stream:{agent_id}",
            "aegis:stream:broadcast",
        ]

    @abstractmethod
    async def handle_message(self, message: AegisMessage) -> Optional[AegisMessage]:
        """
        Process an incoming message and optionally return a response.

        This is the core logic of the agent. Called by the message bus
        consumer loop whenever a message arrives on a subscribed channel.

        Args:
            message: The incoming AegisMessage from the bus.

        Returns:
            An optional AegisMessage response to publish back to the bus.
            Return None if no response is needed (e.g., for EVENT messages).
        """
        ...

    @abstractmethod
    async def startup(self) -> None:
        """
        Agent initialization logic.

        Called by the System Manager during ordered system startup.
        Responsibilities:
            - Subscribe to message bus channels.
            - Load any persistent state.
            - Initialize internal resources.
            - Register with Observer for health monitoring.
        """
        ...

    @abstractmethod
    async def shutdown(self) -> None:
        """
        Graceful teardown logic.

        Called by the System Manager during ordered system shutdown.
        Responsibilities:
            - Unsubscribe from bus channels.
            - Flush any pending state to storage.
            - Release resources (connections, file handles).
            - Deregister from Observer.
        """
        ...

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(agent_id='{self.agent_id}')>"
''',

    # ===================================================================
    # SOURCE: src/aegis/config/
    # ===================================================================

    "src/aegis/config/__init__.py": '''
"""
Aegis Configuration Package

Provides the configuration loading system with layered precedence:
CLI flags > Environment Variables > YAML file > Defaults
"""

from aegis.config.loader import load_config, AegisConfig

__all__ = ["load_config", "AegisConfig"]
''',

    "src/aegis/config/loader.py": '''
"""
Aegis Configuration Loader

Implements: Part XIII, RT-2 — Configuration Sprawl Mitigation

Provides a layered configuration system with strict precedence:
    1. CLI flags (highest priority — applied at runtime)
    2. Environment variables (AEGIS_<SECTION>_<KEY>)
    3. YAML file (aegis_config.yaml)
    4. Defaults (lowest priority — defined in Pydantic models)

The YAML file is the single source of truth for persistent configuration.
Environment variables provide deployment-time overrides without modifying
the YAML file. CLI flags provide session-scoped overrides.
"""

import os
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field


# ═══════════════════════════════════════════════════════════════
# Configuration Models
# ═══════════════════════════════════════════════════════════════


class SystemConfig(BaseModel):
    """Top-level system configuration."""
    name: str = "Project Aegis"
    version: str = "0.1.0"
    environment: str = "development"
    debug: bool = True
    log_level: str = "DEBUG"
    data_dir: str = "aegis_data"


class RedisConfig(BaseModel):
    """Redis connection and behavior configuration."""
    host: str = "localhost"
    port: int = 6379
    db: int = 0
    password: Optional[str] = None
    socket_timeout: int = 5
    retry_on_timeout: bool = True
    stream_max_len: int = 10000
    consumer_group: str = "aegis_agents"


class AgentsConfig(BaseModel):
    """Agent lifecycle and communication configuration."""
    message_ttl_seconds: int = 300
    heartbeat_interval_seconds: int = 30
    restart_max_retries: int = 3
    restart_backoff_seconds: int = 5
    startup_order: list[str] = Field(default_factory=lambda: [
        "observer",
        "warden",
        "identity",
        "lexicon",
        "janus",
        "oracle",
        "forge",
        "torchestrator",
    ])


class OracleConfig(BaseModel):
    """Oracle (LLM Gateway) configuration."""
    default_model: str = "local"
    temperature: float = 0.7
    max_tokens: int = 2000
    request_timeout_seconds: int = 120
    cache_enabled: bool = True
    cache_ttl_seconds: int = 3600


class LexiconConfig(BaseModel):
    """Lexicon (Memory) configuration."""
    context_token_budget: int = 4000
    l3_retention_days: int = 365
    l5_session_ttl_seconds: int = 7200
    promotion_check_interval_seconds: int = 3600


class ForgeConfig(BaseModel):
    """Forge (Execution) configuration."""
    tool_timeout_seconds: int = 30
    skill_timeout_seconds: int = 120
    shell_allowlist: list[str] = Field(default_factory=lambda: [
        "git", "ls", "cat", "echo", "mkdir", "cp", "mv", "rm", "python", "pip"
    ])


class SchedulerConfig(BaseModel):
    """Scheduler configuration."""
    job_store_path: str = "aegis_data/scheduler_jobs.db"
    misfire_grace_seconds: int = 60


class WebConfig(BaseModel):
    """Web UI (Mission Control) configuration."""
    host: str = "localhost"
    port: int = 8420
    cors_origins: list[str] = Field(default_factory=lambda: [
        "http://localhost:8420"
    ])


class AegisConfig(BaseModel):
    """
    Master configuration model for the entire Aegis system.

    Aggregates all subsystem configurations into a single,
    validated, type-safe object.
    """
    system: SystemConfig = Field(default_factory=SystemConfig)
    redis: RedisConfig = Field(default_factory=RedisConfig)
    agents: AgentsConfig = Field(default_factory=AgentsConfig)
    oracle: OracleConfig = Field(default_factory=OracleConfig)
    lexicon: LexiconConfig = Field(default_factory=LexiconConfig)
    forge: ForgeConfig = Field(default_factory=ForgeConfig)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    web: WebConfig = Field(default_factory=WebConfig)


# ═══════════════════════════════════════════════════════════════
# Environment Variable Override Logic
# ═══════════════════════════════════════════════════════════════

# Env var pattern: AEGIS_<SECTION>_<KEY> (uppercase)
# Example: AEGIS_REDIS_HOST=192.168.1.100 overrides redis.host

_ENV_PREFIX = "AEGIS_"


def _apply_env_overrides(config_dict: dict) -> dict:
    """
    Apply environment variable overrides to the configuration dictionary.

    Scans for env vars matching the pattern AEGIS_<SECTION>_<KEY> and
    applies them to the corresponding config section and key.

    Type coercion is applied based on the existing value type in the dict.
    """
    for env_key, env_value in os.environ.items():
        if not env_key.startswith(_ENV_PREFIX):
            continue

        # Strip prefix and split: AEGIS_REDIS_HOST -> ["redis", "host"]
        parts = env_key[len(_ENV_PREFIX):].lower().split("_", 1)
        if len(parts) != 2:
            continue

        section, key = parts

        if section in config_dict and isinstance(config_dict[section], dict):
            if key in config_dict[section]:
                existing = config_dict[section][key]
                # Type coercion based on existing value
                config_dict[section][key] = _coerce_type(env_value, existing)
            else:
                # New key from env — store as string
                config_dict[section][key] = env_value

    return config_dict


def _coerce_type(value: str, reference):
    """Coerce a string env var value to match the type of the reference value."""
    if reference is None:
        return value if value.lower() != "null" else None
    if isinstance(reference, bool):
        return value.lower() in ("true", "1", "yes")
    if isinstance(reference, int):
        return int(value)
    if isinstance(reference, float):
        return float(value)
    if isinstance(reference, list):
        # Env var lists are comma-separated
        return [v.strip() for v in value.split(",")]
    return value


# ═══════════════════════════════════════════════════════════════
# Configuration Loader
# ═══════════════════════════════════════════════════════════════

_DEFAULT_CONFIG_PATHS = [
    Path("aegis_config.yaml"),
    Path("config/aegis_config.yaml"),
    Path.home() / ".aegis" / "aegis_config.yaml",
]


def find_config_file(explicit_path: Optional[str] = None) -> Optional[Path]:
    """
    Locate the configuration YAML file.

    Search order:
        1. Explicit path (if provided via CLI flag or env var).
        2. AEGIS_CONFIG_PATH environment variable.
        3. Default locations (cwd, ./config/, ~/.aegis/).

    Args:
        explicit_path: CLI-provided path to config file.

    Returns:
        Path to the config file, or None if not found.
    """
    # 1. Explicit path
    if explicit_path:
        p = Path(explicit_path)
        if p.exists():
            return p

    # 2. Env var
    env_path = os.environ.get("AEGIS_CONFIG_PATH")
    if env_path:
        p = Path(env_path)
        if p.exists():
            return p

    # 3. Default locations
    for default_path in _DEFAULT_CONFIG_PATHS:
        if default_path.exists():
            return default_path

    return None


def load_config(
    config_path: Optional[str] = None,
    cli_overrides: Optional[dict] = None,
) -> AegisConfig:
    """
    Load and assemble the Aegis configuration.

    Precedence (highest to lowest):
        1. cli_overrides dict
        2. Environment variables (AEGIS_<SECTION>_<KEY>)
        3. YAML file
        4. Pydantic model defaults

    Args:
        config_path: Optional explicit path to the YAML config file.
        cli_overrides: Optional dict of {section: {key: value}} from CLI flags.

    Returns:
        Fully resolved AegisConfig instance.

    Raises:
        FileNotFoundError: If config_path is explicitly provided but doesn't exist.
    """
    config_dict: dict = {}

    # Layer 1: Load YAML file (if found)
    yaml_path = find_config_file(config_path)
    if yaml_path:
        with open(yaml_path, "r") as f:
            loaded = yaml.safe_load(f)
            if loaded and isinstance(loaded, dict):
                config_dict = loaded
    elif config_path:
        # Explicit path was given but not found — that's an error
        raise FileNotFoundError(
            f"Configuration file not found: {config_path}"
        )

    # Layer 2: Apply environment variable overrides
    config_dict = _apply_env_overrides(config_dict)

    # Layer 3: Apply CLI overrides (highest priority)
    if cli_overrides:
        for section, values in cli_overrides.items():
            if section not in config_dict:
                config_dict[section] = {}
            if isinstance(values, dict):
                config_dict[section].update(values)

    # Construct and validate the final config
    return AegisConfig(**config_dict)
''',

    # ===================================================================
    # TESTS
    # ===================================================================

    "tests/__init__.py": '''
"""Aegis Test Suite"""
''',

    "tests/test_schemas.py": '''
"""
Unit Tests — Aegis Message Schema (CHUNK-001)

Validates the AegisMessage model, serialization, deserialization,
TTL expiry logic, and response creation.
"""

import time
from datetime import datetime, timezone, timedelta

import pytest

from aegis.schemas.message import AegisMessage, MessageType, Priority


class TestAegisMessage:
    """Tests for the AegisMessage Pydantic model."""

    def _make_message(self, **overrides) -> AegisMessage:
        """Helper to create a message with sensible defaults."""
        defaults = {
            "source_agent": "test_agent",
            "target_agent": "target_agent",
            "message_type": MessageType.REQUEST,
            "tenant_id": "tenant-001",
            "user_id": "user-001",
            "action": "test.action",
        }
        defaults.update(overrides)
        return AegisMessage(**defaults)

    def test_create_message_with_defaults(self):
        """Message should populate defaults for id, timestamp, priority, ttl."""
        msg = self._make_message()

        assert msg.message_id is not None
        assert len(msg.message_id) == 36  # UUID format
        assert msg.correlation_id is None
        assert msg.priority == Priority.NORMAL
        assert msg.ttl_seconds == 300
        assert msg.payload == {}
        assert msg.metadata == {}
        assert msg.timestamp is not None
        assert msg.timestamp.tzinfo is not None  # Timezone-aware

    def test_create_message_with_all_fields(self):
        """Message should accept all explicit field values."""
        msg = AegisMessage(
            message_id="custom-id",
            correlation_id="corr-123",
            source_agent="oracle",
            target_agent="forge",
            message_type=MessageType.RESPONSE,
            tenant_id="tenant-x",
            user_id="user-y",
            action="oracle.query.response",
            payload={"result": "Paris"},
            priority=Priority.HIGH,
            ttl_seconds=60,
            metadata={"session_id": "sess-001"},
        )

        assert msg.message_id == "custom-id"
        assert msg.correlation_id == "corr-123"
        assert msg.source_agent == "oracle"
        assert msg.target_agent == "forge"
        assert msg.message_type == MessageType.RESPONSE
        assert msg.priority == Priority.HIGH
        assert msg.ttl_seconds == 60
        assert msg.payload["result"] == "Paris"
        assert msg.metadata["session_id"] == "sess-001"

    def test_message_type_enum_values(self):
        """Verify all message type enum values."""
        assert MessageType.REQUEST == "request"
        assert MessageType.RESPONSE == "response"
        assert MessageType.EVENT == "event"
        assert MessageType.ERROR == "error"

    def test_priority_enum_values(self):
        """Verify all priority enum values."""
        assert Priority.LOW == "low"
        assert Priority.NORMAL == "normal"
        assert Priority.HIGH == "high"
        assert Priority.CRITICAL == "critical"

    def test_is_expired_false_within_ttl(self):
        """Message should not be expired within TTL window."""
        msg = self._make_message(ttl_seconds=300)
        assert msg.is_expired() is False

    def test_is_expired_true_after_ttl(self):
        """Message should be expired after TTL elapses."""
        past_time = datetime.now(timezone.utc) - timedelta(seconds=400)
        msg = self._make_message(ttl_seconds=300)
        msg.timestamp = past_time
        assert msg.is_expired() is True

    def test_is_expired_never_with_none_ttl(self):
        """Message with ttl_seconds=None should never expire."""
        past_time = datetime.now(timezone.utc) - timedelta(days=365)
        msg = self._make_message(ttl_seconds=None)
        msg.timestamp = past_time
        assert msg.is_expired() is False

    def test_create_response(self):
        """create_response should produce a correlated response message."""
        request = self._make_message(
            source_agent="torchestrator",
            target_agent="forge",
            action="forge.execute_tool",
        )

        response = request.create_response(
            source_agent="forge",
            payload={"result": "success"},
        )

        assert response.correlation_id == request.message_id
        assert response.source_agent == "forge"
        assert response.target_agent == "torchestrator"
        assert response.message_type == MessageType.RESPONSE
        assert response.action == "forge.execute_tool.response"
        assert response.payload["result"] == "success"
        assert response.tenant_id == request.tenant_id
        assert response.user_id == request.user_id

    def test_create_error_response(self):
        """create_response with error should produce an ERROR type message."""
        request = self._make_message()
        response = request.create_response(
            source_agent="forge",
            error="Tool not found: nonexistent_tool",
        )

        assert response.message_type == MessageType.ERROR
        assert response.payload["error"] == "Tool not found: nonexistent_tool"

    def test_to_bus_dict_serialization(self):
        """to_bus_dict should produce a dict with a 'data' JSON string."""
        msg = self._make_message()
        bus_dict = msg.to_bus_dict()

        assert "data" in bus_dict
        assert isinstance(bus_dict["data"], str)
        assert "test_agent" in bus_dict["data"]
        assert "test.action" in bus_dict["data"]

    def test_from_bus_dict_deserialization(self):
        """from_bus_dict should reconstruct the original message."""
        original = self._make_message(
            payload={"key": "value"},
            metadata={"trace": "123"},
        )
        bus_dict = original.to_bus_dict()
        restored = AegisMessage.from_bus_dict(bus_dict)

        assert restored.message_id == original.message_id
        assert restored.source_agent == original.source_agent
        assert restored.target_agent == original.target_agent
        assert restored.action == original.action
        assert restored.payload == original.payload
        assert restored.metadata == original.metadata
        assert restored.tenant_id == original.tenant_id

    def test_roundtrip_serialization(self):
        """Full JSON roundtrip should preserve all fields."""
        msg = self._make_message(
            priority=Priority.CRITICAL,
            ttl_seconds=60,
            payload={"nested": {"data": [1, 2, 3]}},
        )
        json_str = msg.model_dump_json()
        restored = AegisMessage.model_validate_json(json_str)

        assert restored == msg
''',

    "tests/test_base_agent.py": '''
"""
Unit Tests — BaseAgent ABC (CHUNK-001)

Validates that BaseAgent enforces the interface contract and
provides correct default behavior.
"""

from typing import Optional

import pytest

from aegis.agents.base import BaseAgent
from aegis.schemas.message import AegisMessage, MessageType


class ConcreteAgent(BaseAgent):
    """A minimal concrete implementation for testing the ABC."""

    def __init__(self, agent_id: str = "test_agent"):
        super().__init__(agent_id=agent_id)
        self.messages_handled: list[AegisMessage] = []
        self.started = False
        self.stopped = False

    async def handle_message(self, message: AegisMessage) -> Optional[AegisMessage]:
        self.messages_handled.append(message)
        return message.create_response(
            source_agent=self.agent_id,
            payload={"handled": True},
        )

    async def startup(self) -> None:
        self.started = True

    async def shutdown(self) -> None:
        self.stopped = True


class TestBaseAgent:
    """Tests for the BaseAgent abstract base class."""

    def test_cannot_instantiate_abc_directly(self):
        """BaseAgent should not be instantiable without implementing abstracts."""
        with pytest.raises(TypeError):
            BaseAgent(agent_id="bad")  # type: ignore

    def test_concrete_agent_instantiation(self):
        """A fully implemented subclass should instantiate correctly."""
        agent = ConcreteAgent("my_agent")
        assert agent.agent_id == "my_agent"

    def test_default_subscriptions(self):
        """Default subscriptions should include agent stream + broadcast."""
        agent = ConcreteAgent("warden")
        assert "aegis:stream:warden" in agent.subscriptions
        assert "aegis:stream:broadcast" in agent.subscriptions

    def test_custom_subscriptions(self):
        """Custom subscriptions should override defaults."""
        custom = ["aegis:stream:custom", "aegis:stream:special"]
        agent = ConcreteAgent.__new__(ConcreteAgent)
        BaseAgent.__init__(agent, agent_id="custom", subscriptions=custom)
        assert agent.subscriptions == custom

    @pytest.mark.asyncio
    async def test_startup(self):
        """Startup should execute agent initialization."""
        agent = ConcreteAgent()
        await agent.startup()
        assert agent.started is True

    @pytest.mark.asyncio
    async def test_shutdown(self):
        """Shutdown should execute agent teardown."""
        agent = ConcreteAgent()
        await agent.shutdown()
        assert agent.stopped is True

    @pytest.mark.asyncio
    async def test_handle_message(self):
        """handle_message should process and return a response."""
        agent = ConcreteAgent()
        msg = AegisMessage(
            source_agent="caller",
            target_agent="test_agent",
            message_type=MessageType.REQUEST,
            tenant_id="t1",
            user_id="u1",
            action="test.ping",
        )

        response = await agent.handle_message(msg)

        assert len(agent.messages_handled) == 1
        assert response is not None
        assert response.correlation_id == msg.message_id
        assert response.payload["handled"] is True

    def test_repr(self):
        """__repr__ should include class name and agent_id."""
        agent = ConcreteAgent("observer")
        assert "ConcreteAgent" in repr(agent)
        assert "observer" in repr(agent)
''',

    "tests/test_config.py": '''
"""
Unit Tests — Configuration Loader (CHUNK-001)

Validates YAML loading, environment variable overrides, CLI overrides,
type coercion, and default fallback behavior.
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from aegis.config.loader import (
    AegisConfig,
    load_config,
    find_config_file,
    _apply_env_overrides,
    _coerce_type,
)


class TestConfigDefaults:
    """Test that defaults are sensible when no config file exists."""

    def test_load_config_no_file_uses_defaults(self, tmp_path, monkeypatch):
        """With no config file and no env vars, defaults should apply."""
        monkeypatch.chdir(tmp_path)
        config = load_config()

        assert config.system.name == "Project Aegis"
        assert config.system.version == "0.1.0"
        assert config.system.environment == "development"
        assert config.redis.host == "localhost"
        assert config.redis.port == 6379
        assert config.agents.message_ttl_seconds == 300
        assert config.forge.tool_timeout_seconds == 30
        assert config.web.port == 8420

    def test_startup_order_default(self, tmp_path, monkeypatch):
        """Default agent startup order should match spec."""
        monkeypatch.chdir(tmp_path)
        config = load_config()

        expected_order = [
            "observer", "warden", "identity", "lexicon",
            "janus", "oracle", "forge", "torchestrator",
        ]
        assert config.agents.startup_order == expected_order


class TestConfigYAMLLoading:
    """Test YAML file loading."""

    def test_load_from_yaml(self, tmp_path, monkeypatch):
        """Config should load values from YAML file."""
        monkeypatch.chdir(tmp_path)
        config_content = """
system:
  name: "Test Aegis"
  environment: "production"
  debug: false
redis:
  host: "192.168.1.100"
  port: 6380
"""
        config_file = tmp_path / "aegis_config.yaml"
        config_file.write_text(config_content)

        config = load_config()

        assert config.system.name == "Test Aegis"
        assert config.system.environment == "production"
        assert config.system.debug is False
        assert config.redis.host == "192.168.1.100"
        assert config.redis.port == 6380

    def test_explicit_path(self, tmp_path):
        """Explicit config path should be used when provided."""
        config_content = """
system:
  name: "Explicit Config"
"""
        config_file = tmp_path / "custom_config.yaml"
        config_file.write_text(config_content)

        config = load_config(config_path=str(config_file))
        assert config.system.name == "Explicit Config"

    def test_explicit_path_not_found_raises(self):
        """Missing explicit path should raise FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            load_config(config_path="/nonexistent/path/config.yaml")


class TestEnvOverrides:
    """Test environment variable override logic."""

    def test_env_override_string(self):
        """String env var should override config value."""
        config_dict = {"redis": {"host": "localhost"}}
        with patch.dict(os.environ, {"AEGIS_REDIS_HOST": "10.0.0.1"}):
            result = _apply_env_overrides(config_dict)
        assert result["redis"]["host"] == "10.0.0.1"

    def test_env_override_int(self):
        """Integer env var should be coerced."""
        config_dict = {"redis": {"port": 6379}}
        with patch.dict(os.environ, {"AEGIS_REDIS_PORT": "6380"}):
            result = _apply_env_overrides(config_dict)
        assert result["redis"]["port"] == 6380
        assert isinstance(result["redis"]["port"], int)

    def test_env_override_bool(self):
        """Boolean env var should be coerced."""
        config_dict = {"system": {"debug": True}}
        with patch.dict(os.environ, {"AEGIS_SYSTEM_DEBUG": "false"}):
            result = _apply_env_overrides(config_dict)
        assert result["system"]["debug"] is False

    def test_env_override_null_password(self):
        """Null env var should set to None."""
        config_dict = {"redis": {"password": None}}
        with patch.dict(os.environ, {"AEGIS_REDIS_PASSWORD": "secret123"}):
            result = _apply_env_overrides(config_dict)
        assert result["redis"]["password"] == "secret123"


class TestCLIOverrides:
    """Test CLI override precedence."""

    def test_cli_overrides_yaml(self, tmp_path, monkeypatch):
        """CLI overrides should take precedence over YAML values."""
        monkeypatch.chdir(tmp_path)
        config_content = """
system:
  environment: "production"
redis:
  port: 6379
"""
        config_file = tmp_path / "aegis_config.yaml"
        config_file.write_text(config_content)

        config = load_config(cli_overrides={
            "system": {"environment": "testing"},
            "redis": {"port": 9999},
        })

        assert config.system.environment == "testing"
        assert config.redis.port == 9999

    def test_cli_overrides_env(self, tmp_path, monkeypatch):
        """CLI overrides should take precedence over env vars."""
        monkeypatch.chdir(tmp_path)
        config_file = tmp_path / "aegis_config.yaml"
        config_file.write_text("system:\\n  debug: true")

        with patch.dict(os.environ, {"AEGIS_SYSTEM_DEBUG": "false"}):
            config = load_config(cli_overrides={
                "system": {"debug": True},
            })

        assert config.system.debug is True


class TestCoerceType:
    """Test type coercion helper."""

    def test_coerce_int(self):
        assert _coerce_type("42", 0) == 42

    def test_coerce_float(self):
        assert _coerce_type("0.9", 0.0) == 0.9

    def test_coerce_bool_true(self):
        assert _coerce_type("true", False) is True
        assert _coerce_type("1", False) is True
        assert _coerce_type("yes", False) is True

    def test_coerce_bool_false(self):
        assert _coerce_type("false", True) is False
        assert _coerce_type("0", True) is False

    def test_coerce_list(self):
        assert _coerce_type("a, b, c", []) == ["a", "b", "c"]

    def test_coerce_none_to_null(self):
        assert _coerce_type("null", None) is None

    def test_coerce_none_to_value(self):
        assert _coerce_type("hello", None) == "hello"


class TestFindConfigFile:
    """Test config file discovery."""

    def test_finds_in_cwd(self, tmp_path, monkeypatch):
        """Should find aegis_config.yaml in current directory."""
        monkeypatch.chdir(tmp_path)
        config_file = tmp_path / "aegis_config.yaml"
        config_file.write_text("system:\\n  name: test")

        found = find_config_file()
        assert found == config_file

    def test_returns_none_when_not_found(self, tmp_path, monkeypatch):
        """Should return None when no config file exists."""
        monkeypatch.chdir(tmp_path)
        found = find_config_file()
        assert found is None

    def test_explicit_path_takes_priority(self, tmp_path, monkeypatch):
        """Explicit path should be checked first."""
        monkeypatch.chdir(tmp_path)
        # Create a config in cwd
        (tmp_path / "aegis_config.yaml").write_text("system:\\n  name: cwd")
        # Create an explicit config elsewhere
        explicit = tmp_path / "other" / "config.yaml"
        explicit.parent.mkdir()
        explicit.write_text("system:\\n  name: explicit")

        found = find_config_file(str(explicit))
        assert found == explicit
''',

    "tests/test_amcp.py": '''
"""
Unit Tests — AMCP Chunk Contract (CHUNK-001)

Validates the AMCPChunk model, dependency checking, and status advancement.
"""

import pytest

from aegis.schemas.amcp import AMCPChunk, AMCPStatus


class TestAMCPChunk:
    """Tests for the AMCPChunk model."""

    def test_create_chunk(self):
        """Should create a chunk with default START status."""
        chunk = AMCPChunk(
            chunk_id="CHUNK-001",
            name="Base Layout & Schemas",
            description="Foundation layer.",
            dependencies=[],
            acceptance_criteria=["Project structure exists", "Tests pass"],
            files_manifest=["src/aegis/__init__.py", "pyproject.toml"],
        )

        assert chunk.chunk_id == "CHUNK-001"
        assert chunk.status == AMCPStatus.START
        assert len(chunk.acceptance_criteria) == 2
        assert len(chunk.files_manifest) == 2

    def test_can_start_no_dependencies(self):
        """Chunk with no dependencies should always be startable."""
        chunk = AMCPChunk(chunk_id="CHUNK-001", name="First", dependencies=[])
        assert chunk.can_start(set()) is True

    def test_can_start_dependencies_met(self):
        """Chunk should start when all dependencies are released."""
        chunk = AMCPChunk(
            chunk_id="CHUNK-003",
            name="Warden",
            dependencies=["CHUNK-001", "CHUNK-002"],
        )
        released = {"CHUNK-001", "CHUNK-002", "CHUNK-004"}
        assert chunk.can_start(released) is True

    def test_cannot_start_dependencies_not_met(self):
        """Chunk should NOT start when dependencies are missing."""
        chunk = AMCPChunk(
            chunk_id="CHUNK-003",
            name="Warden",
            dependencies=["CHUNK-001", "CHUNK-002"],
        )
        released = {"CHUNK-001"}  # Missing CHUNK-002
        assert chunk.can_start(released) is False

    def test_advance_through_phases(self):
        """Should advance through all AMCP phases in order."""
        chunk = AMCPChunk(chunk_id="CHUNK-001", name="Test")

        assert chunk.status == AMCPStatus.START
        assert chunk.advance() == AMCPStatus.ARCHITECT
        assert chunk.advance() == AMCPStatus.AUTOFILE
        assert chunk.advance() == AMCPStatus.ASSEMBLE
        assert chunk.advance() == AMCPStatus.RELEASE

    def test_advance_at_release_returns_none(self):
        """Should return None when already at RELEASE (no further phase)."""
        chunk = AMCPChunk(chunk_id="CHUNK-001", name="Test")
        chunk.status = AMCPStatus.RELEASE
        assert chunk.advance() is None

    def test_status_enum_values(self):
        """Verify all AMCP status enum values."""
        assert AMCPStatus.START == "START"
        assert AMCPStatus.ARCHITECT == "ARCHITECT"
        assert AMCPStatus.AUTOFILE == "AUTOFILE"
        assert AMCPStatus.ASSEMBLE == "ASSEMBLE"
        assert AMCPStatus.RELEASE == "RELEASE"
''',
}


# ═══════════════════════════════════════════════════════════════
# Assembly Engine
# ═══════════════════════════════════════════════════════════════

def create_package_init_files(path: str) -> None:
    """
    Create __init__.py files in parent directories if they don't exist.

    Ensures Python package integrity for nested module paths.
    Only creates init files within src/ and tests/ trees.
    """
    dir_name = os.path.dirname(path)
    if dir_name and (dir_name.startswith("src/") or dir_name.startswith("tests/")):
        parts = dir_name.split("/")
        for i in range(2, len(parts) + 1):
            pkg_path = "/".join(parts[:i])
            init_file = os.path.join(pkg_path, "__init__.py")
            if not os.path.exists(init_file):
                with open(init_file, "w") as f:
                    pass
                print(f"  [Created] {init_file} (package marker)")


def main() -> None:
    """Main assembly function — writes all CHUNK-001 files to disk."""
    print("═" * 60)
    print("  ASSEMBLING: CHUNK-001 — Base Layout & Schemas")
    print("═" * 60)
    print()

    files_written = 0

    for path, content in CHUNK_1_FILES.items():
        # Ensure directory exists
        dir_name = os.path.dirname(path)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)

        # Create package __init__.py files as needed
        create_package_init_files(path)

        # Write the file
        clean_content = textwrap.dedent(content.strip()) + "\n"
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(clean_content)
        print(f"  [Writing] {path}")
        files_written += 1

    print()
    print("─" * 60)
    print(f"  ✓ Assembly Complete — {files_written} files written.")
    print()
    print("  Next steps:")
    print("    1. cd project-aegis")
    print("    2. python -m venv .venv && source .venv/bin/activate")
    print("    3. pip install -e '.[dev]'")
    print("    4. pytest -v")
    print("    5. python -m aegis.main")
    print("─" * 60)


if __name__ == "__main__":
    main()
```

Phase: RELEASE... ✓ COMPLETE

───────────────────────────────────────────────────────────────

## CHUNK-001 RELEASE Summary

| Criteria | Status |
|----------|--------|
| Project structure (`pyproject.toml`, `src/` layout) | ✅ |
| `AegisMessage` schema (Part II §2.2) — full Pydantic v2 model with serialization, TTL, response creation | ✅ |
| `BaseAgent` ABC (Part II §2.3) — enforces `handle_message`, `startup`, `shutdown` | ✅ |
| Configuration loader — YAML + env var + CLI override precedence (RT-2 mitigation) | ✅ |
| `aegis_config.yaml` template — all subsystem configs with documented defaults | ✅ |
| `AMCPChunk` contract model (Part IX §9.4) — dependency checking, phase advancement | ✅ |
| Unit tests — schemas, base agent, config loader, AMCP contract | ✅ |
| CHANGELOG.md + README.md | ✅ |

**Version:** `0.1.0`
**Files produced:** 18

───────────────────────────────────────────────────────────────
✓ **CHUNK-001 RELEASED.** Ready for CHUNK-002.
───────────────────────────────────────────────────────────────