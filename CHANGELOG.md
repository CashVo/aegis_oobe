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
