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

**Acceptance Criteria:**

- [x] Project structure (`pyproject.toml`, `src/` layout)
- [x] `AegisMessage` schema (Part II §2.2) — full Pydantic v2 model with serialization, TTL, response creation
- [x] `BaseAgent` ABC (Part II §2.3) — enforces `handle_message`, `startup`, `shutdown`
- [x] Configuration loader — YAML + env var + CLI override precedence (RT-2 mitigation)
- [x] `aegis_config.yaml` template — all subsystem configs with documented defaults
- [x] `AMCPChunk` contract model (Part IX §9.4) — dependency checking, phase advancement
- [x] Unit tests — schemas, base agent, config loader, AMCP contract
- [x] CHANGELOG.md + README.md

## [0.2.0] — 2026-05-06
### Added
- `aegis/bus/` package: Redis Streams-based message bus infrastructure
- `RedisConnectionManager`: Async connection pool with health check and graceful shutdown
- `MessagePublisher`: XADD-based publishing to agent streams and broadcast
- `MessageSubscriber`: Consumer group reads, XACK acknowledgment, TTL expiry, pending message claiming via XAUTOCLAIM
- `constants.py`: Stream/group naming conventions (`aegis:stream:{agent_id}`, `aegis:group:{agent_id}`)
- Full unit test suite (connection, publisher, subscriber, constants)

**Acceptance Criteria:**
- [x] Redis connection manager with pool lifecycle
- [x] Stream publisher (XADD) for directed + broadcast messages
- [x] Stream subscriber with consumer groups (XREADGROUP)
- [x] Message acknowledgment (XACK)
- [x] Pending message claiming (XAUTOCLAIM)
- [x] Bus health check (PING)
- [x] AegisMessage serialization/deserialization on the wire
- [x] TTL expiration enforcement
- [x] Unit tests for all components

## [0.3.0] - 2026-05-07

### Added — CHUNK-003: Warden (Security)

-   **Protocol & Schemas (`src/aegis/schemas/warden.py`):** Full protocol contracts for all security authorization, including `WardenVerdict`, `WardenRequest`, and `WardenResponse`.
-   **RBAC Engine (`src/aegis/warden/permission_model.py`):** Implemented the core Role-Based Access Control engine. It evaluates permissions with support for wildcards, exact matches, and prefix-based inheritance (e.g., `file.*` grants `file.read`).
-   **Shell Allowlist (`src/aegis/warden/allowlist.py`):** Added the `AllowlistEngine` to mitigate RT-6 (Unbounded Shell Execution). It enforces a restrictive list of commands and unconditionally blocks dangerous patterns.
-   **Message Interceptor (`src/aegis/warden/interceptor.py`):** Created the universal `MessageInterceptor`, the enforcement point that validates every message in the system against security policies.
-   **Emergency Bypass (`src/aegis/warden/bypass.py`):** Implemented the `BypassManager` to mitigate RT-4 (Warden as SPOF), providing a time-limited, root-only bypass mechanism with full audit logging.
-   **Warden Agent (`src/aegis/agents/warden.py`):** Assembled the `WardenAgent` itself, which orchestrates all security subsystems and handles authorization requests on the message bus.
-   **Unit Tests (`tests/test_warden/`):** Added a comprehensive test suite with over 40 passing tests, validating the permission model, allowlist, interceptor, bypass manager, and agent message handling.

### Fixed
- Corrected initial `member` role permissions to include `file.read`, resolving a conflict between the spec and practical use-case testing.
- Refactored `PermissionModel.check_permission` logic to be more robust and prevent `IndexError` on edge cases.

### Dependencies
- No new external dependencies were added in this chunk.

**Acceptance Criteria:**

- [x] Warden agent implements BaseAgent ABC  
- [x] Permission model evaluates RBAC with wildcard, exact, and prefix matching  
- [x] Allowlist engine blocks dangerous patterns unconditionally (even for root)  
- [x] Escalation patterns trigger ESCALATE verdict for non-privileged users  
- [x] Emergency bypass activatable/deactivatable by root only  
- [x] Bypass auto-expires after configurable TTL  
- [x] Message interceptor handles passthrough, shell commands, and standard RBAC  
- [x] All security events logged at appropriate levels  
- [x] Full test coverage across all subsystems

## [0.4.0] - 2026-05-07
### Added — CHUNK-004: Identity Agent
- `src/aegis/schemas/identity.py` — Full protocol contracts (IdentityAction, IdentityRequest, IdentityResponse, domain models)
- `src/aegis/identity/store.py` — Async SQLite persistence (aiosqlite) with full Tenant/User/Role CRUD
- `src/aegis/identity/bootstrap.py` — First-run bootstrap sequence (§5.4, addresses RT-1)
- `src/aegis/identity/constants.py` — Default system role definitions (root/admin/member/observer)
- `src/aegis/agents/identity/agent.py` — Council-level Identity Agent with message routing
- Passphrase hashing (SHA-256 + salt) with local-trust fallback mode
- 35+ unit tests covering store, bootstrap, and agent message handling
### Dependencies
- Added: `aiosqlite>=0.19.0` to requirements.txt

Acceptance Criteria
- [x] Identity Agent conforms to BaseAgent ABC (Part II, §2.3)
- [x] Tenant/User/Role CRUD via SQLite (Part V, §5.1)
- [x] Default roles provisioned on tenant creation (Part V, §5.2)
- [x] IdentityAction protocol fully implemented (Part V, §5.3)
- [x] First-run bootstrap sequence handles empty store (Part V, §5.4 / RT-1)
- [x] Multi-tenant isolation — all queries scoped by tenant_id (Principle #5)
- [x] Root user protection (cannot delete, cannot reassign role)
- [x] Authentication with passphrase or local-trust mode
- [x] AegisMessage envelope for all inter-agent communication (Part II, §2.2)
- [x] Warden integration point ready (permissions exposed for consumption)
