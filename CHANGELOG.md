# File: CHANGELOG.md
# Purpose: Record of all major changes to the Aegis system architecture

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

-----

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

-----

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

**What This Chunk Enables:**

- Universal, synchronous security interception for all inter-agent messages  
- Role-Based Access Control (RBAC) with 4 default roles (root, admin, member, observer)  
- Shell command allowlist enforcement (mitigates RT-6: Unbounded Shell Execution)  
- Emergency bypass mode for root users during Warden recovery (mitigates RT-4: Warden as SPOF)  
- TTL-bounded bypass with automatic deactivation and full audit logging  
- Metrics tracking for all authorization decisions

-----

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

### What This Chunk Enables

- Full identity lifecycle management for the system  
- Warden can now query permissions via Identity Agent  
- System Manager can trigger bootstrap on first launch  
- Foundation for UC-5 (User Onboarding) — partial

-----

## [0.5.0] — 2026-05-07
### Added — CHUNK-005: Observer Service
- ObserverAgent: Non-council agent for system-wide monitoring
- Structured logging via structlog (JSON-formatted, contextual)
- HeartbeatMonitor: Tracks agent liveness, detects failures, fires alerts
- MetricsCollector: In-memory time-series aggregation with ring buffers
- HealthServer: Lightweight aiohttp endpoint (/health, /health/ready, /health/live)
- FallbackLogger: stderr JSON output when Observer is unavailable (RT-3 mitigation)
- Self-monitoring heartbeat loop (RT-3: Observer Blind Spot addressed)
- ObserverAction protocol enum for bus communication
- Full Pydantic schemas: HeartbeatEvent, LogEvent, MetricEvent, SystemHealthReport
- Comprehensive test suite (5 test modules, 30+ test cases)


**Acceptance Criteria:**
- [x] Observer agent subscribes to `aegis:stream:broadcast` and `aegis:stream:observer`
- [x] Structured logging with structlog (JSON, contextual fields: tenant_id, user_id, correlation_id, agent_id)
- [x] Heartbeat monitoring with configurable thresholds (degraded → unresponsive)
- [x] Health endpoint exposed via HTTP for Mission Control UI
- [x] Self-monitoring via internal heartbeat loop
- [x] Stderr fallback logging when Observer is down (RT-3 mitigation)
- [x] Performance metrics collection (message latency, tool execution times)
- [x] Alert callback system for health state transitions
- [x] Inherits from BaseAgent (CHUNK-001), communicates via Redis bus (CHUNK-002)

**Dependencies Used:** CHUNK-001 (schemas, BaseAgent), CHUNK-002 (Redis bus patterns)
**New External Deps:** `structlog>=24.1.0`, `aiohttp>=3.9.0`

-----

## [0.6.0] — 2026-05-07
### Added — CHUNK-006: Lexicon (Memory Control Plane)
- Lexicon Agent with full message dispatch (assemble_context, store, search, promote, query_tier, session_end)
- L0 Core Identity tier (YAML, user-editable only, cache with invalidation)
- L1 Domain Knowledge tier (SQLite, keyword search, category filtering, deprecation)
- L2 Workflow Calibration tier (SQLite, confidence scoring, reinforcement pattern)
- L3 Episodic Memory tier (SQLite + FTS5 full-text search, append-only, retention eviction)
- L4 Artifact Index tier (SQLite, metadata pointers, validation tracking)
- L5 Session Scratchpad tier (Redis-backed with local cache fallback, TTL, snapshots)
- Context Router: parallel tier queries, relevance ranking, token budget enforcement
- Memory Governor: L5→L3 promotion pipeline, significance heuristics, eviction, L0 update suggestions
- Storage manager: path resolution, SQLite schema init (WAL mode, indexes, FTS5 triggers)
- Full test suite: 40+ unit/integration tests across all tiers, router, governor, and agent

**What This Chunk Enables:**
- Any agent can request assembled context from user memory (L0–L5) within a token budget
- Memory CRUD operations scoped by tenant/user
- Session lifecycle management (scratchpad → episodic promotion)
- Foundation for UC-2 (context-aware responses using personal memory)
- Foundation for UC-5 (user onboarding initializes memory tiers)
- Ready for CHUNK-008 (Oracle) to consume context packets

**Acceptance Criteria:**
- [x] Lexicon agent handles all LexiconAction message types
- [x] All 6 memory tiers (L0–L5) implemented with correct storage formats
- [x] Context Router assembles multi-tier context within token budgets
- [x] Memory Governor promotes L5→L3 at session end with significance filtering
- [x] L0 is protected (user-editable only, agents can only suggest)
- [x] L3 FTS5 full-text search operational
- [x] L3 retention/eviction enforced
- [x] Multi-tenant data isolation (all operations scoped by tenant_id + user_id)
- [x] Storage auto-initialization for new users
- [x] Tests pass for all tiers, router, governor, and agent integration

**What This Chunk Enables:**
- Any agent can request assembled context from user memory (L0–L5) within a token budget
- Memory CRUD operations scoped by tenant/user
- Session lifecycle management (scratchpad → episodic promotion)
- Foundation for UC-2 (context-aware responses using personal memory)
- Foundation for UC-5 (user onboarding initializes memory tiers)
- Ready for CHUNK-008 (Oracle) to consume context packets

-----

## [0.7.0] — 2026-05-07

### Added — CHUNK-007: Janus (Governance Engine)

- **Janus Agent** (`src/aegis/agents/janus/agent.py`)
  - Full protocol handler for all JanusActions (evaluate, add, list, update, delete, get)
  - Default policy seeding on first initialization
  - Verdict determination with priority-based severity ordering
  - AegisMessage-compliant request/response cycle

- **Policy Evaluation Engine** (`engine.py`)
  - Safe DSL interpreter — NO eval()/exec() usage
  - Supported operators: ==, !=, in, not_in, contains, startswith, endswith
  - Logical operators: and, or, not with parenthesized grouping
  - Dot-notation context field resolution (e.g., `request.action`)
  - Tokenization cache for performance
  - Comprehensive error handling via PolicyEvalError

- **Policy Storage** (`storage.py`)
  - SQLite-backed persistence with WAL mode
  - Full CRUD: add, get, update, delete, list
  - Tenant-scoped + system-wide policy queries
  - Priority-ordered retrieval for evaluation
  - Tag-based filtering

- **Default Policies** (`defaults.py`) — 12 baseline governance rules:
  - Security: Shell allowlist (RT-6), dangerous pattern deny, file write logging, file delete escalation
  - Access Control: Cross-tenant deny, root-only config, admin-only user management
  - Memory: L0 write protection (Part IV §4.4), promotion logging
  - Operational: Oracle rate limiting, skill timeout warnings, Observer broadcast allow

- **Protocol Schemas** (`src/aegis/schemas/janus.py`)
  - JanusAction, PolicyRule, JanusRequest, JanusResponse, PolicyEvalResult

- **Test Suite** — 40+ test cases covering engine DSL, storage CRUD, and agent integration

**Acceptance Criteria Met**
- [x] Janus agent implements BaseAgent interface (Part II §2.3)
- [x] Policy storage with CRUD operations
- [x] Policy evaluation engine with safe condition parsing
- [x] Default policies seeded on empty store
- [x] Red Team mitigations addressed (RT-4 via Warden consult, RT-6 via shell policies)
- [x] Multi-tenant policy scoping
- [x] Priority-based verdict determination

**Summary:** Janus is now a fully operational governance engine with a safe, custom DSL evaluator (no `eval()`), SQLite persistence, 12 default security policies aligned with your Red Team findings, and a clean agent protocol. The Warden can now consult Janus for policy decisions via `aegis:stream:janus`, and TOrchestrator can query governance rules before executing sensitive operations.

-----

## [0.8.0] — 2026-05-11
### Added — CHUNK-008: Oracle (LLM Gateway)
- Oracle agent with full AegisMessage envelope handling (Part II §2.1, §2.3)
- Model Registry with preference-based selection ("fast", "capable", "local") and dynamic registration
- Prompt Engine with context packet assembly from Lexicon (Part IV §4.3 integration)
- Token Manager with word-based estimation, optional tiktoken, and per-tenant usage tracking
- SQLite-backed Response Cache with TTL expiration, hit counting, and auto-cleanup
- Sliding-window Rate Limiter (per-minute + per-hour, per-tenant/user)
- Ollama Provider (primary, local-first) — chat completion + embedding via /api/chat and /api/embed
- OpenAI-Compatible Provider (secondary) — /v1/chat/completions + /v1/embeddings
- Structured output (JSON-mode) support via OracleAction.STRUCTURED
- Classification action via OracleAction.CLASSIFY with dedicated prompt template
- Embedding generation via OracleAction.EMBED
- Comprehensive unit test suite (agent, registry, prompt engine, tokens, cache)
- Oracle configuration fragment for aegis_config.yaml

**Acceptance Criteria Checklist**
- [x] Oracle agent subscribes to `aegis:stream:oracle` and processes `AegisMessage` envelopes
- [x] Model registry supports preference-based selection and dynamic registration
- [x] Prompt template engine assembles system + context + user prompts
- [x] Token budget manager validates requests against context windows
- [x] Response cache reduces redundant LLM calls (SQLite-backed, TTL)
- [x] Rate limiter enforces per-tenant/user request limits
- [x] Ollama provider implements generation + embedding (local-first)
- [x] OpenAI-compatible provider supports external API fallback
- [x] All four Oracle actions implemented: QUERY, STRUCTURED, EMBED, CLASSIFY
- [x] Warden authorization integration point in agent flow
- [x] Lexicon ContextPacket integration in prompt assembly
- [x] UC-1 (partial): Basic question answering path complete
- [x] UC-2 (partial): Context-aware query path with Lexicon integration complete

**What This Enables**
The Oracle is now the **live LLM inference backbone**. CHUNK-009 (The Forge) can route `invoke_oracle` calls through the bus, and CHUNK-010 (TOrchestrator) can dispatch user queries for AI-powered responses. The full QUERY → context-assembly → inference → cache pipeline is operational.
