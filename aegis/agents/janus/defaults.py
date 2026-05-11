# aegis/agents/janus/defaults.py
"""
Default Governance Policies — Loaded on first initialization.

Implements: Part XIV, CHUNK-007 — Default policies deliverable.
Implements: Part XIII — Red Team mitigations (RT-4, RT-6).

These policies provide baseline security and operational guardrails
that align with the Red Team Assessment findings.
"""

from aegis.schemas.janus import PolicyRule


# =============================================================================
# SECURITY POLICIES — Shell & Tool Execution
# =============================================================================

POLICY_SHELL_ALLOWLIST = PolicyRule(
    rule_id="SYS-SEC-001",
    name="Shell Command Allowlist Enforcement",
    description=(
        "Only allow execution of shell commands that are in the approved allowlist. "
        "Addresses RT-6 (Unbounded Shell Execution) from the Red Team Assessment. "
        "Allowlist: git, ls, cat, echo, mkdir, cp, mv, rm (files only), python, pip, pytest."
    ),
    condition='action == "forge.execute_tool" and resource == "tool:execute_shell_command"',
    action_on_match="escalate",
    priority=900,
    active=True,
    tenant_id=None,
    tags=["security", "shell", "rt-6"],
)

POLICY_DENY_DANGEROUS_SHELL = PolicyRule(
    rule_id="SYS-SEC-002",
    name="Deny Dangerous Shell Patterns",
    description=(
        "Deny shell commands that match dangerous patterns: sudo, rm -rf /, "
        "chmod 777, eval, curl|bash, wget|sh, and similar."
    ),
    condition='action == "forge.execute_tool" and resource == "tool:execute_shell_command" and command_dangerous == "true"',
    action_on_match="deny",
    priority=950,
    active=True,
    tenant_id=None,
    tags=["security", "shell", "critical"],
)

POLICY_FILE_WRITE_LOGGING = PolicyRule(
    rule_id="SYS-SEC-003",
    name="Log All File Write Operations",
    description="Log every file_write tool invocation for audit trail.",
    condition='action == "forge.execute_tool" and resource == "tool:file_write"',
    action_on_match="log",
    priority=100,
    active=True,
    tenant_id=None,
    tags=["security", "audit", "file"],
)

POLICY_FILE_DELETE_ESCALATE = PolicyRule(
    rule_id="SYS-SEC-004",
    name="Escalate File Deletion",
    description="Escalate file_delete operations for confirmation unless user has admin role.",
    condition='action == "forge.execute_tool" and resource == "tool:file_delete" and role != "admin" and role != "root"',
    action_on_match="escalate",
    priority=500,
    active=True,
    tenant_id=None,
    tags=["security", "file", "escalation"],
)


# =============================================================================
# ACCESS CONTROL POLICIES
# =============================================================================

POLICY_DENY_CROSS_TENANT = PolicyRule(
    rule_id="SYS-AC-001",
    name="Deny Cross-Tenant Access",
    description=(
        "Deny any request where the requesting user's tenant_id does not match "
        "the target resource's tenant_id. Implements Part V multi-tenant isolation."
    ),
    condition='cross_tenant == "true"',
    action_on_match="deny",
    priority=1000,
    active=True,
    tenant_id=None,
    tags=["security", "multi-tenant", "critical"],
)

POLICY_ROOT_ONLY_SYSTEM_CONFIG = PolicyRule(
    rule_id="SYS-AC-002",
    name="System Config Requires Root",
    description="Only root users can modify system-level configuration.",
    condition='action == "system.config" and role != "root"',
    action_on_match="deny",
    priority=900,
    active=True,
    tenant_id=None,
    tags=["security", "access-control", "config"],
)

POLICY_ADMIN_USER_MANAGEMENT = PolicyRule(
    rule_id="SYS-AC-003",
    name="User Management Requires Admin or Root",
    description="User create/update/delete operations require admin or root role.",
    condition='action startswith "identity." and action != "identity.authenticate" and role not_in ["admin", "root"]',
    action_on_match="deny",
    priority=800,
    active=True,
    tenant_id=None,
    tags=["security", "access-control", "identity"],
)


# =============================================================================
# MEMORY / LEXICON POLICIES
# =============================================================================

POLICY_L0_WRITE_PROTECTION = PolicyRule(
    rule_id="SYS-MEM-001",
    name="L0 Memory is User-Editable Only",
    description=(
        "Deny any agent-initiated write to L0 (Core Identity) memory. "
        "Only user-initiated actions (via TOrchestrator with explicit approval) are allowed. "
        "Implements Part IV §4.4 — L0 is user-editable only."
    ),
    condition='action == "lexicon.store_memory" and target_tier == "L0" and user_initiated != "true"',
    action_on_match="deny",
    priority=950,
    active=True,
    tenant_id=None,
    tags=["memory", "l0", "critical"],
)

POLICY_MEMORY_PROMOTION_LOG = PolicyRule(
    rule_id="SYS-MEM-002",
    name="Log Memory Promotions",
    description="Log all memory promotion events for auditability.",
    condition='action == "lexicon.promote_memory"',
    action_on_match="log",
    priority=100,
    active=True,
    tenant_id=None,
    tags=["memory", "audit", "promotion"],
)


# =============================================================================
# OPERATIONAL POLICIES
# =============================================================================

POLICY_RATE_LIMIT_ORACLE = PolicyRule(
    rule_id="SYS-OPS-001",
    name="Oracle Rate Limit Warning",
    description="Warn when Oracle request rate exceeds threshold (evaluated by Warden context).",
    condition='action startswith "oracle." and rate_exceeded == "true"',
    action_on_match="warn",
    priority=400,
    active=True,
    tenant_id=None,
    tags=["operational", "oracle", "rate-limit"],
)

POLICY_SKILL_TIMEOUT_ENFORCEMENT = PolicyRule(
    rule_id="SYS-OPS-002",
    name="Skill Execution Timeout Enforcement",
    description="Log skills that approach their timeout threshold (>80% of allotted time).",
    condition='action == "forge.execute_skill" and near_timeout == "true"',
    action_on_match="warn",
    priority=200,
    active=True,
    tenant_id=None,
    tags=["operational", "forge", "timeout"],
)

POLICY_ALLOW_OBSERVER_BROADCAST = PolicyRule(
    rule_id="SYS-OPS-003",
    name="Allow Observer Broadcast Subscription",
    description="Always allow the Observer agent to subscribe to broadcast channels.",
    condition='action == "bus.subscribe" and source_agent == "observer"',
    action_on_match="allow",
    priority=800,
    active=True,
    tenant_id=None,
    tags=["operational", "observer"],
)


# =============================================================================
# AGGREGATE: All Default Policies
# =============================================================================

DEFAULT_POLICIES: list[PolicyRule] = [
    # Security — Shell/Tool
    POLICY_SHELL_ALLOWLIST,
    POLICY_DENY_DANGEROUS_SHELL,
    POLICY_FILE_WRITE_LOGGING,
    POLICY_FILE_DELETE_ESCALATE,
    # Access Control
    POLICY_DENY_CROSS_TENANT,
    POLICY_ROOT_ONLY_SYSTEM_CONFIG,
    POLICY_ADMIN_USER_MANAGEMENT,
    # Memory
    POLICY_L0_WRITE_PROTECTION,
    POLICY_MEMORY_PROMOTION_LOG,
    # Operational
    POLICY_RATE_LIMIT_ORACLE,
    POLICY_SKILL_TIMEOUT_ENFORCEMENT,
    POLICY_ALLOW_OBSERVER_BROADCAST,
]
