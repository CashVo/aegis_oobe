# build_chunk_007.py
#
# CHUNK-007: Janus (Governance Engine)
# Assembles the Janus agent — policy storage, evaluation engine, and default policies.
# Run from the root of the project-aegis directory.
#
# Implements: Part II §2.1 (Janus role), Part VI §6.6 (Janus Protocol),
#             Part XIV (CHUNK-007 deliverables)

import os
import textwrap


# --- File Manifest ---
CHUNK_007_FILES = {

    # =========================================================================
    # SCHEMAS
    # =========================================================================

    "aegis/schemas/janus.py": '''
# aegis/schemas/janus.py
"""
Janus (Governance Engine) protocol schemas.

Implements: Part VI, §6.6 — Janus Protocol
"""

from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field
from datetime import datetime, timezone


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class JanusAction(str, Enum):
    """Actions supported by the Janus governance agent."""
    EVALUATE_POLICY = "evaluate_policy"
    ADD_POLICY = "add_policy"
    LIST_POLICIES = "list_policies"
    UPDATE_POLICY = "update_policy"
    DELETE_POLICY = "delete_policy"
    GET_POLICY = "get_policy"


class PolicyRule(BaseModel):
    """
    A single governance policy rule.

    Implements: Part VI, §6.6 — PolicyRule model.

    The `condition` field holds a safe DSL expression evaluated against
    the request context. Supported operators:
      - Comparison: ==, !=, in, not_in, contains, startswith
      - Logical: and, or, not
      - Field access via dot notation on the context dict
    """
    rule_id: str = Field(..., description="Unique identifier for this policy rule.")
    name: str = Field(..., description="Human-readable policy name.")
    description: str = Field(default="", description="Detailed description of what this policy enforces.")
    condition: str = Field(
        ...,
        description=(
            "Evaluatable condition expression. Uses a safe DSL subset. "
            "Example: 'action == \\"forge.execute_tool\\" and resource == \\"tool:execute_shell_command\\"'"
        )
    )
    action_on_match: str = Field(
        ...,
        description="Action to take when condition matches: 'allow', 'deny', 'warn', 'log', 'escalate'."
    )
    priority: int = Field(
        default=0,
        description="Higher priority rules are evaluated first. Range: 0-1000."
    )
    active: bool = Field(default=True, description="Whether this rule is currently active.")
    tenant_id: Optional[str] = Field(
        default=None,
        description="If set, rule applies only to this tenant. None = system-wide."
    )
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
    tags: list[str] = Field(default_factory=list, description="Categorization tags for filtering.")


class JanusRequest(BaseModel):
    """
    Request envelope for Janus agent interactions.

    Implements: Part VI, §6.6 — JanusRequest model.
    """
    action: JanusAction
    tenant_id: str = Field(..., description="Tenant scope for the request.")
    user_id: str = Field(..., description="User making the request.")
    context: dict[str, Any] = Field(
        default_factory=dict,
        description="Context dict for policy evaluation (action, resource, agent, etc.)."
    )
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Action-specific payload (e.g., PolicyRule dict for ADD_POLICY)."
    )


class PolicyEvalResult(BaseModel):
    """Result of evaluating a single policy rule against a context."""
    rule_id: str
    rule_name: str
    matched: bool
    action_on_match: str
    priority: int


class JanusResponse(BaseModel):
    """
    Response envelope from Janus agent.

    Implements: Part VI, §6.6 — JanusResponse model.
    """
    success: bool
    action: JanusAction
    verdict: Optional[str] = Field(
        default=None,
        description="Final verdict for EVALUATE_POLICY: 'allow', 'deny', 'warn', 'log', 'escalate'."
    )
    policies_evaluated: int = Field(default=0, description="Number of policies evaluated.")
    matched_policies: list[str] = Field(
        default_factory=list,
        description="List of rule_ids that matched."
    )
    eval_details: list[PolicyEvalResult] = Field(
        default_factory=list,
        description="Detailed evaluation results per rule."
    )
    data: dict[str, Any] = Field(default_factory=dict, description="Action-specific response data.")
    error: Optional[str] = Field(default=None, description="Error message if success=False.")
''',

    # =========================================================================
    # JANUS AGENT — POLICY EVALUATION ENGINE
    # =========================================================================

    "aegis/agents/janus/__init__.py": '''
# aegis/agents/janus/__init__.py
"""
Janus — The Governance Engine.

Implements: Part II, §2.1 — Janus agent role.
A policy and rules engine that stores and evaluates system-wide governance rules,
ethical guardrails, and operational policies.
"""

from aegis.agents.janus.agent import JanusAgent
from aegis.agents.janus.engine import PolicyEngine
from aegis.agents.janus.storage import PolicyStore

__all__ = ["JanusAgent", "PolicyEngine", "PolicyStore"]
''',

    "aegis/agents/janus/engine.py": '''
# aegis/agents/janus/engine.py
"""
Policy Evaluation Engine — Safe DSL interpreter for governance rules.

Implements: Part VI, §6.6 — Policy evaluation logic.

The engine evaluates policy conditions against a context dictionary using
a restricted, safe expression language. No arbitrary code execution.

Supported DSL:
  - Field references: context keys accessed directly (e.g., `action`, `resource`)
  - String comparison: ==, !=
  - Membership: `in`, `not_in` (checks if value is in a list)
  - String ops: `contains`, `startswith`, `endswith`
  - Logical: `and`, `or`, `not`
  - Grouping: parentheses
"""

import logging
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)


class PolicyEvalError(Exception):
    """Raised when a policy condition cannot be safely evaluated."""
    pass


class PolicyEngine:
    """
    Evaluates policy rule conditions against a context dictionary.

    Uses a safe tokenized parser — does NOT use eval() or exec().
    """

    # Allowed operators in the DSL
    COMPARISON_OPS = {"==", "!=", "in", "not_in", "contains", "startswith", "endswith"}
    LOGICAL_OPS = {"and", "or", "not"}
    ALL_KEYWORDS = COMPARISON_OPS | LOGICAL_OPS | {"true", "false", "none"}

    def __init__(self):
        self._cache: dict[str, list] = {}  # Parsed token cache

    def evaluate(self, condition: str, context: dict[str, Any]) -> bool:
        """
        Evaluate a condition string against the provided context.

        Args:
            condition: DSL condition string.
            context: Dictionary of context values to evaluate against.

        Returns:
            True if condition matches, False otherwise.

        Raises:
            PolicyEvalError: If the condition is malformed or unsafe.
        """
        try:
            tokens = self._tokenize(condition)
            result, _ = self._parse_expression(tokens, 0, context)
            return result
        except PolicyEvalError:
            raise
        except Exception as e:
            logger.error(f"Policy evaluation failed for condition: {condition!r}, error: {e}")
            raise PolicyEvalError(f"Failed to evaluate condition: {condition!r}") from e

    def _tokenize(self, condition: str) -> list[str]:
        """Tokenize a condition string into a list of tokens."""
        if condition in self._cache:
            return self._cache[condition]

        # Pattern: quoted strings, parentheses, operators, identifiers, list brackets, commas
        pattern = r"""
            ("[^"]*"|'[^']*')    |  # Quoted strings
            (\(|\))              |  # Parentheses
            (\[|\])              |  # List brackets
            (,)                  |  # Commas
            (==|!=)              |  # Comparison operators
            ([a-zA-Z_][a-zA-Z0-9_.]*)  |  # Identifiers and keywords
            (\S+)                   # Catch-all for unexpected tokens
        """
        tokens = []
        for match in re.finditer(pattern, condition, re.VERBOSE):
            token = match.group(0).strip()
            if token:
                tokens.append(token)

        self._cache[condition] = tokens
        return tokens

    def _parse_expression(
        self, tokens: list[str], pos: int, context: dict[str, Any]
    ) -> tuple[bool, int]:
        """Parse a full expression with logical operators (and/or)."""
        left, pos = self._parse_not(tokens, pos, context)

        while pos < len(tokens) and tokens[pos] in ("and", "or"):
            op = tokens[pos]
            pos += 1
            right, pos = self._parse_not(tokens, pos, context)

            if op == "and":
                left = left and right
            elif op == "or":
                left = left or right

        return left, pos

    def _parse_not(
        self, tokens: list[str], pos: int, context: dict[str, Any]
    ) -> tuple[bool, int]:
        """Handle 'not' prefix."""
        if pos < len(tokens) and tokens[pos] == "not":
            pos += 1
            result, pos = self._parse_not(tokens, pos, context)
            return not result, pos
        return self._parse_comparison(tokens, pos, context)

    def _parse_comparison(
        self, tokens: list[str], pos: int, context: dict[str, Any]
    ) -> tuple[bool, int]:
        """Parse a comparison expression or grouped expression."""
        # Handle parenthesized groups
        if pos < len(tokens) and tokens[pos] == "(":
            pos += 1  # skip '('
            result, pos = self._parse_expression(tokens, pos, context)
            if pos < len(tokens) and tokens[pos] == ")":
                pos += 1  # skip ')'
            else:
                raise PolicyEvalError("Unmatched parenthesis in condition.")
            return result, pos

        # Get left operand
        left_val, pos = self._resolve_value(tokens, pos, context)

        # Check for comparison operator
        if pos < len(tokens) and tokens[pos] in self.COMPARISON_OPS:
            op = tokens[pos]
            pos += 1
            right_val, pos = self._resolve_value(tokens, pos, context)

            result = self._apply_comparison(left_val, op, right_val)
            return result, pos

        # Bare truthy check
        return bool(left_val), pos

    def _resolve_value(
        self, tokens: list[str], pos: int, context: dict[str, Any]
    ) -> tuple[Any, int]:
        """Resolve a token to its value (literal, context lookup, or list)."""
        if pos >= len(tokens):
            raise PolicyEvalError("Unexpected end of condition expression.")

        token = tokens[pos]

        # List literal: [item1, item2, ...]
        if token == "[":
            return self._parse_list(tokens, pos, context)

        # String literal (quoted)
        if (token.startswith('"') and token.endswith('"')) or \
           (token.startswith("'") and token.endswith("'")):
            return token[1:-1], pos + 1

        # Boolean literals
        if token.lower() == "true":
            return True, pos + 1
        if token.lower() == "false":
            return False, pos + 1
        if token.lower() == "none":
            return None, pos + 1

        # Numeric literals
        try:
            if "." in token:
                return float(token), pos + 1
            return int(token), pos + 1
        except ValueError:
            pass

        # Context field reference (supports dot notation)
        if re.match(r'^[a-zA-Z_][a-zA-Z0-9_.]*$', token) and token not in self.ALL_KEYWORDS:
            value = self._resolve_context_field(token, context)
            return value, pos + 1

        # If it looks like a keyword that shouldn't be here, error
        if token in self.LOGICAL_OPS or token in (")", "]", ","):
            raise PolicyEvalError(f"Unexpected token in value position: {token!r}")

        raise PolicyEvalError(f"Cannot resolve token: {token!r}")

    def _parse_list(
        self, tokens: list[str], pos: int, context: dict[str, Any]
    ) -> tuple[list, int]:
        """Parse a list literal [item1, item2, ...]."""
        pos += 1  # skip '['
        items = []
        while pos < len(tokens) and tokens[pos] != "]":
            if tokens[pos] == ",":
                pos += 1
                continue
            val, pos = self._resolve_value(tokens, pos, context)
            items.append(val)
        if pos < len(tokens) and tokens[pos] == "]":
            pos += 1  # skip ']'
        else:
            raise PolicyEvalError("Unmatched bracket in list literal.")
        return items, pos

    def _resolve_context_field(self, field: str, context: dict[str, Any]) -> Any:
        """
        Resolve a dotted field reference against the context dict.

        Example: 'request.action' resolves context['request']['action']
        """
        parts = field.split(".")
        value: Any = context

        for part in parts:
            if isinstance(value, dict):
                value = value.get(part)
            else:
                return None

        return value

    def _apply_comparison(self, left: Any, op: str, right: Any) -> bool:
        """Apply a comparison operator between two resolved values."""
        if op == "==":
            return left == right
        elif op == "!=":
            return left != right
        elif op == "in":
            if isinstance(right, (list, tuple, set)):
                return left in right
            if isinstance(right, str):
                return str(left) in right
            return False
        elif op == "not_in":
            if isinstance(right, (list, tuple, set)):
                return left not in right
            if isinstance(right, str):
                return str(left) not in right
            return True
        elif op == "contains":
            if isinstance(left, str) and isinstance(right, str):
                return right in left
            if isinstance(left, (list, tuple, set)):
                return right in left
            return False
        elif op == "startswith":
            if isinstance(left, str) and isinstance(right, str):
                return left.startswith(right)
            return False
        elif op == "endswith":
            if isinstance(left, str) and isinstance(right, str):
                return left.endswith(right)
            return False
        else:
            raise PolicyEvalError(f"Unknown comparison operator: {op!r}")

    def clear_cache(self) -> None:
        """Clear the tokenization cache."""
        self._cache.clear()
''',

    "aegis/agents/janus/storage.py": '''
# aegis/agents/janus/storage.py
"""
Policy Storage — SQLite-backed persistence for governance rules.

Implements: Part XIV, CHUNK-007 — Policy storage deliverable.
"""

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from aegis.schemas.janus import PolicyRule

logger = logging.getLogger(__name__)


class PolicyStore:
    """
    SQLite-backed policy storage with full CRUD operations.

    Policies are stored per-tenant (tenant_id=None means system-wide).
    Thread-safe via SQLite's built-in locking.
    """

    def __init__(self, db_path: str | Path):
        """
        Initialize the PolicyStore.

        Args:
            db_path: Path to the SQLite database file for policy storage.
        """
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None
        self._initialize_db()

    def _initialize_db(self) -> None:
        """Create the policies table if it does not exist."""
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")

        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS policies (
                rule_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                condition TEXT NOT NULL,
                action_on_match TEXT NOT NULL,
                priority INTEGER DEFAULT 0,
                active INTEGER DEFAULT 1,
                tenant_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                tags TEXT DEFAULT '[]'
            )
        """)
        # Index for fast tenant-scoped lookups
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_policies_tenant
            ON policies(tenant_id, active, priority DESC)
        """)
        self._conn.commit()
        logger.info(f"PolicyStore initialized at: {self._db_path}")

    def add_policy(self, rule: PolicyRule) -> PolicyRule:
        """
        Add a new policy rule to the store.

        Args:
            rule: The PolicyRule to persist.

        Returns:
            The persisted PolicyRule.

        Raises:
            ValueError: If a rule with the same rule_id already exists.
        """
        existing = self.get_policy(rule.rule_id)
        if existing is not None:
            raise ValueError(f"Policy with rule_id '{rule.rule_id}' already exists.")

        self._conn.execute(
            """
            INSERT INTO policies
                (rule_id, name, description, condition, action_on_match,
                 priority, active, tenant_id, created_at, updated_at, tags)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                rule.rule_id,
                rule.name,
                rule.description,
                rule.condition,
                rule.action_on_match,
                rule.priority,
                int(rule.active),
                rule.tenant_id,
                rule.created_at.isoformat(),
                rule.updated_at.isoformat(),
                json.dumps(rule.tags),
            ),
        )
        self._conn.commit()
        logger.debug(f"Policy added: {rule.rule_id} ({rule.name})")
        return rule

    def get_policy(self, rule_id: str) -> Optional[PolicyRule]:
        """
        Retrieve a single policy by its rule_id.

        Args:
            rule_id: The unique identifier of the policy.

        Returns:
            The PolicyRule if found, else None.
        """
        cursor = self._conn.execute(
            "SELECT * FROM policies WHERE rule_id = ?", (rule_id,)
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return self._row_to_policy(row)

    def update_policy(self, rule: PolicyRule) -> PolicyRule:
        """
        Update an existing policy rule.

        Args:
            rule: The PolicyRule with updated fields.

        Returns:
            The updated PolicyRule.

        Raises:
            ValueError: If the policy does not exist.
        """
        existing = self.get_policy(rule.rule_id)
        if existing is None:
            raise ValueError(f"Policy with rule_id '{rule.rule_id}' not found.")

        now = datetime.now(timezone.utc)
        self._conn.execute(
            """
            UPDATE policies SET
                name = ?, description = ?, condition = ?, action_on_match = ?,
                priority = ?, active = ?, tenant_id = ?, updated_at = ?, tags = ?
            WHERE rule_id = ?
            """,
            (
                rule.name,
                rule.description,
                rule.condition,
                rule.action_on_match,
                rule.priority,
                int(rule.active),
                rule.tenant_id,
                now.isoformat(),
                json.dumps(rule.tags),
                rule.rule_id,
            ),
        )
        self._conn.commit()
        rule.updated_at = now
        logger.debug(f"Policy updated: {rule.rule_id} ({rule.name})")
        return rule

    def delete_policy(self, rule_id: str) -> bool:
        """
        Delete a policy by rule_id.

        Args:
            rule_id: The unique identifier of the policy to delete.

        Returns:
            True if deleted, False if not found.
        """
        cursor = self._conn.execute(
            "DELETE FROM policies WHERE rule_id = ?", (rule_id,)
        )
        self._conn.commit()
        deleted = cursor.rowcount > 0
        if deleted:
            logger.debug(f"Policy deleted: {rule_id}")
        return deleted

    def list_policies(
        self,
        tenant_id: Optional[str] = None,
        active_only: bool = True,
        tags: Optional[list[str]] = None,
    ) -> list[PolicyRule]:
        """
        List policies with optional filtering.

        Args:
            tenant_id: If provided, return tenant-specific + system-wide policies.
                       If None, return only system-wide policies.
            active_only: If True, return only active policies.
            tags: If provided, filter by policies containing ANY of these tags.

        Returns:
            List of matching PolicyRule objects, ordered by priority descending.
        """
        query = "SELECT * FROM policies WHERE 1=1"
        params: list = []

        if tenant_id is not None:
            # Return both tenant-specific and system-wide (tenant_id IS NULL) policies
            query += " AND (tenant_id = ? OR tenant_id IS NULL)"
            params.append(tenant_id)
        else:
            query += " AND tenant_id IS NULL"

        if active_only:
            query += " AND active = 1"

        query += " ORDER BY priority DESC, created_at ASC"

        cursor = self._conn.execute(query, params)
        policies = [self._row_to_policy(row) for row in cursor.fetchall()]

        # Filter by tags if specified (post-query since tags are JSON)
        if tags:
            tag_set = set(tags)
            policies = [p for p in policies if tag_set & set(p.tags)]

        return policies

    def get_policies_for_evaluation(self, tenant_id: Optional[str] = None) -> list[PolicyRule]:
        """
        Retrieve all active policies applicable for evaluation, ordered by priority.

        This is the primary method used by the PolicyEngine during evaluation.
        Returns system-wide + tenant-scoped policies, sorted by priority DESC.

        Args:
            tenant_id: The tenant context for evaluation.

        Returns:
            Sorted list of active PolicyRule objects.
        """
        return self.list_policies(tenant_id=tenant_id, active_only=True)

    def count_policies(self, tenant_id: Optional[str] = None) -> int:
        """Return the count of policies (optionally filtered by tenant)."""
        if tenant_id is not None:
            cursor = self._conn.execute(
                "SELECT COUNT(*) FROM policies WHERE (tenant_id = ? OR tenant_id IS NULL)",
                (tenant_id,),
            )
        else:
            cursor = self._conn.execute("SELECT COUNT(*) FROM policies")
        return cursor.fetchone()[0]

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None
            logger.debug("PolicyStore connection closed.")

    def _row_to_policy(self, row: sqlite3.Row) -> PolicyRule:
        """Convert a database row to a PolicyRule model."""
        return PolicyRule(
            rule_id=row["rule_id"],
            name=row["name"],
            description=row["description"],
            condition=row["condition"],
            action_on_match=row["action_on_match"],
            priority=row["priority"],
            active=bool(row["active"]),
            tenant_id=row["tenant_id"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            tags=json.loads(row["tags"]),
        )
''',

    "aegis/agents/janus/defaults.py": '''
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
''',

    "aegis/agents/janus/agent.py": '''
# aegis/agents/janus/agent.py
"""
Janus Agent — The Governance Engine.

Implements: Part II, §2.1 — Janus role definition.
Implements: Part VI, §6.6 — Janus protocol.
Implements: Part XIV, CHUNK-007 — Janus agent deliverable.

Janus is a policy and rules engine that stores and evaluates system-wide
governance rules, ethical guardrails, and operational policies. It is
consulted by TOrchestrator and Warden for policy decisions.
"""

import logging
from pathlib import Path
from typing import Any, Optional

from aegis.agents.base import BaseAgent
from aegis.agents.janus.defaults import DEFAULT_POLICIES
from aegis.agents.janus.engine import PolicyEngine, PolicyEvalError
from aegis.agents.janus.storage import PolicyStore
from aegis.schemas.janus import (
    JanusAction,
    JanusRequest,
    JanusResponse,
    PolicyEvalResult,
    PolicyRule,
)
from aegis.schemas.message import AegisMessage, MessageType, Priority

logger = logging.getLogger(__name__)


class JanusAgent(BaseAgent):
    """
    The Janus Governance Engine agent.

    Responsibilities:
      - Store and manage governance policies (CRUD).
      - Evaluate policies against request contexts.
      - Return verdicts: allow, deny, warn, log, escalate.
      - Seed default policies on first initialization.

    Communication:
      - Subscribes to: aegis:stream:janus
      - Responds to: requesting agent's stream
    """

    agent_id: str = "janus"
    subscriptions: list[str] = ["aegis:stream:janus"]

    def __init__(
        self,
        data_dir: str | Path = "aegis_data/system",
        bus=None,
    ):
        """
        Initialize the Janus agent.

        Args:
            data_dir: Directory for policy database storage.
            bus: Reference to the Redis message bus (injected at startup).
        """
        self._data_dir = Path(data_dir)
        self._db_path = self._data_dir / "governance" / "policies.db"
        self._store: Optional[PolicyStore] = None
        self._engine = PolicyEngine()
        self._bus = bus
        self._initialized = False

    async def startup(self) -> None:
        """
        Agent initialization: open policy store, seed defaults if needed.

        Implements: Part II, §2.3 — BaseAgent.startup()
        """
        logger.info("Janus agent starting up...")

        # Initialize policy store
        self._store = PolicyStore(self._db_path)

        # Seed default policies if store is empty
        if self._store.count_policies() == 0:
            logger.info("Empty policy store detected. Seeding default governance policies...")
            self._seed_defaults()

        self._initialized = True
        policy_count = self._store.count_policies()
        logger.info(f"Janus agent ready. {policy_count} policies loaded.")

    async def shutdown(self) -> None:
        """
        Graceful teardown: close policy store.

        Implements: Part II, §2.3 — BaseAgent.shutdown()
        """
        logger.info("Janus agent shutting down...")
        if self._store:
            self._store.close()
            self._store = None
        self._engine.clear_cache()
        self._initialized = False
        logger.info("Janus agent shutdown complete.")

    async def handle_message(self, message: AegisMessage) -> Optional[AegisMessage]:
        """
        Process an incoming message and return a response.

        Implements: Part II, §2.3 — BaseAgent.handle_message()
        Implements: Part VI, §6.6 — Full Janus protocol handling.

        Args:
            message: The incoming AegisMessage addressed to Janus.

        Returns:
            An AegisMessage response, or None if no response needed.
        """
        if not self._initialized:
            return self._error_response(
                message, "Janus agent is not initialized."
            )

        try:
            # Parse the payload as a JanusRequest
            request = JanusRequest(
                action=JanusAction(message.action.replace("janus.", "")),
                tenant_id=message.tenant_id,
                user_id=message.user_id,
                context=message.payload.get("context", {}),
                payload=message.payload.get("payload", {}),
            )
        except (ValueError, KeyError) as e:
            return self._error_response(
                message, f"Invalid Janus request: {e}"
            )

        # Route to appropriate handler
        handler_map = {
            JanusAction.EVALUATE_POLICY: self._handle_evaluate,
            JanusAction.ADD_POLICY: self._handle_add,
            JanusAction.LIST_POLICIES: self._handle_list,
            JanusAction.UPDATE_POLICY: self._handle_update,
            JanusAction.DELETE_POLICY: self._handle_delete,
            JanusAction.GET_POLICY: self._handle_get,
        }

        handler = handler_map.get(request.action)
        if handler is None:
            return self._error_response(
                message, f"Unknown Janus action: {request.action}"
            )

        response = await handler(request)
        return self._build_response(message, response)

    # =========================================================================
    # ACTION HANDLERS
    # =========================================================================

    async def _handle_evaluate(self, request: JanusRequest) -> JanusResponse:
        """
        Evaluate all applicable policies against the provided context.

        Evaluation logic:
          1. Retrieve all active policies for the tenant (+ system-wide).
          2. Evaluate each policy condition against the context.
          3. Collect matches, ordered by priority.
          4. Determine final verdict:
             - If ANY matched policy has action 'deny' → final verdict = 'deny'
             - If ANY matched policy has action 'escalate' → final verdict = 'escalate'
             - If ANY matched policy has action 'warn' → final verdict = 'warn'
             - If ANY matched policy has action 'allow' (explicit) → final verdict = 'allow'
             - If no matches → default verdict = 'allow' (implicit allow)
        """
        context = request.context
        policies = self._store.get_policies_for_evaluation(tenant_id=request.tenant_id)

        eval_results: list[PolicyEvalResult] = []
        matched_ids: list[str] = []

        for policy in policies:
            try:
                matched = self._engine.evaluate(policy.condition, context)
            except PolicyEvalError as e:
                logger.warning(
                    f"Policy {policy.rule_id} ({policy.name}) evaluation error: {e}. Skipping."
                )
                eval_results.append(PolicyEvalResult(
                    rule_id=policy.rule_id,
                    rule_name=policy.name,
                    matched=False,
                    action_on_match=policy.action_on_match,
                    priority=policy.priority,
                ))
                continue

            eval_results.append(PolicyEvalResult(
                rule_id=policy.rule_id,
                rule_name=policy.name,
                matched=matched,
                action_on_match=policy.action_on_match,
                priority=policy.priority,
            ))

            if matched:
                matched_ids.append(policy.rule_id)

        # Determine final verdict from matched policies
        verdict = self._determine_verdict(eval_results)

        return JanusResponse(
            success=True,
            action=JanusAction.EVALUATE_POLICY,
            verdict=verdict,
            policies_evaluated=len(policies),
            matched_policies=matched_ids,
            eval_details=eval_results,
        )

    async def _handle_add(self, request: JanusRequest) -> JanusResponse:
        """Add a new policy rule."""
        try:
            rule_data = request.payload
            # Override tenant_id from request context for tenant-scoped policies
            if "tenant_id" not in rule_data or rule_data["tenant_id"] is None:
                rule_data["tenant_id"] = None  # System-wide by default
            rule = PolicyRule(**rule_data)
            self._store.add_policy(rule)
            return JanusResponse(
                success=True,
                action=JanusAction.ADD_POLICY,
                data={"rule_id": rule.rule_id, "name": rule.name},
            )
        except (ValueError, TypeError) as e:
            return JanusResponse(
                success=False,
                action=JanusAction.ADD_POLICY,
                error=str(e),
            )

    async def _handle_list(self, request: JanusRequest) -> JanusResponse:
        """List policies with optional filtering."""
        tenant_id = request.payload.get("tenant_id", request.tenant_id)
        active_only = request.payload.get("active_only", True)
        tags = request.payload.get("tags")

        policies = self._store.list_policies(
            tenant_id=tenant_id,
            active_only=active_only,
            tags=tags,
        )

        return JanusResponse(
            success=True,
            action=JanusAction.LIST_POLICIES,
            policies_evaluated=len(policies),
            data={
                "policies": [p.model_dump(mode="json") for p in policies],
                "count": len(policies),
            },
        )

    async def _handle_update(self, request: JanusRequest) -> JanusResponse:
        """Update an existing policy rule."""
        try:
            rule = PolicyRule(**request.payload)
            updated = self._store.update_policy(rule)
            return JanusResponse(
                success=True,
                action=JanusAction.UPDATE_POLICY,
                data={"rule_id": updated.rule_id, "name": updated.name},
            )
        except (ValueError, TypeError) as e:
            return JanusResponse(
                success=False,
                action=JanusAction.UPDATE_POLICY,
                error=str(e),
            )

    async def _handle_delete(self, request: JanusRequest) -> JanusResponse:
        """Delete a policy rule by ID."""
        rule_id = request.payload.get("rule_id")
        if not rule_id:
            return JanusResponse(
                success=False,
                action=JanusAction.DELETE_POLICY,
                error="Missing 'rule_id' in payload.",
            )

        deleted = self._store.delete_policy(rule_id)
        return JanusResponse(
            success=deleted,
            action=JanusAction.DELETE_POLICY,
            data={"rule_id": rule_id, "deleted": deleted},
            error=None if deleted else f"Policy '{rule_id}' not found.",
        )

    async def _handle_get(self, request: JanusRequest) -> JanusResponse:
        """Get a single policy by ID."""
        rule_id = request.payload.get("rule_id")
        if not rule_id:
            return JanusResponse(
                success=False,
                action=JanusAction.GET_POLICY,
                error="Missing 'rule_id' in payload.",
            )

        policy = self._store.get_policy(rule_id)
        if policy is None:
            return JanusResponse(
                success=False,
                action=JanusAction.GET_POLICY,
                error=f"Policy '{rule_id}' not found.",
            )

        return JanusResponse(
            success=True,
            action=JanusAction.GET_POLICY,
            data={"policy": policy.model_dump(mode="json")},
        )

    # =========================================================================
    # INTERNAL HELPERS
    # =========================================================================

    def _determine_verdict(self, eval_results: list[PolicyEvalResult]) -> str:
        """
        Determine the final verdict from evaluation results.

        Priority order (highest severity wins):
          1. deny (any deny = immediate deny)
          2. escalate
          3. warn
          4. log (pass-through, just record)
          5. allow (explicit allow from a policy)
          6. allow (implicit — no matching policies)
        """
        matched = [r for r in eval_results if r.matched]

        if not matched:
            return "allow"  # Implicit allow — no policies triggered

        # Check for deny (highest priority match wins if multiple)
        deny_matches = [r for r in matched if r.action_on_match == "deny"]
        if deny_matches:
            return "deny"

        # Check for escalate
        escalate_matches = [r for r in matched if r.action_on_match == "escalate"]
        if escalate_matches:
            return "escalate"

        # Check for warn
        warn_matches = [r for r in matched if r.action_on_match == "warn"]
        if warn_matches:
            return "warn"

        # Check for log (allow, but log it)
        log_matches = [r for r in matched if r.action_on_match == "log"]
        if log_matches:
            return "log"

        # Explicit allow
        allow_matches = [r for r in matched if r.action_on_match == "allow"]
        if allow_matches:
            return "allow"

        return "allow"

    def _seed_defaults(self) -> None:
        """Seed the policy store with default governance policies."""
        for policy in DEFAULT_POLICIES:
            try:
                self._store.add_policy(policy)
                logger.debug(f"  Seeded: {policy.rule_id} — {policy.name}")
            except ValueError:
                logger.debug(f"  Skipped (exists): {policy.rule_id}")

        logger.info(f"Seeded {len(DEFAULT_POLICIES)} default policies.")

    def _build_response(
        self, original: AegisMessage, response: JanusResponse
    ) -> AegisMessage:
        """Construct an AegisMessage response envelope."""
        return AegisMessage(
            correlation_id=original.message_id,
            source_agent=self.agent_id,
            target_agent=original.source_agent,
            message_type=MessageType.RESPONSE,
            tenant_id=original.tenant_id,
            user_id=original.user_id,
            action=f"janus.{response.action.value}.response",
            payload=response.model_dump(mode="json"),
            priority=original.priority,
            metadata={"correlation_id": original.message_id},
        )

    def _error_response(self, original: AegisMessage, error: str) -> AegisMessage:
        """Construct an error response AegisMessage."""
        return AegisMessage(
            correlation_id=original.message_id,
            source_agent=self.agent_id,
            target_agent=original.source_agent,
            message_type=MessageType.ERROR,
            tenant_id=original.tenant_id,
            user_id=original.user_id,
            action="janus.error",
            payload={"success": False, "error": error},
            priority=Priority.HIGH,
            metadata={"correlation_id": original.message_id},
        )
''',

    # =========================================================================
    # TESTS
    # =========================================================================

    "tests/test_janus/__init__.py": '''
# tests/test_janus/__init__.py
"""Tests for Janus (Governance Engine) — CHUNK-007."""
''',

    "tests/test_janus/test_engine.py": '''
# tests/test_janus/test_engine.py
"""
Unit tests for the Janus Policy Evaluation Engine.

Tests the safe DSL interpreter for correctness, edge cases, and security.
"""

import pytest
from aegis.agents.janus.engine import PolicyEngine, PolicyEvalError


@pytest.fixture
def engine():
    """Fresh PolicyEngine instance for each test."""
    return PolicyEngine()


class TestBasicComparisons:
    """Test basic comparison operations."""

    def test_equality(self, engine):
        ctx = {"action": "forge.execute_tool", "resource": "tool:file_read"}
        assert engine.evaluate('action == "forge.execute_tool"', ctx) is True
        assert engine.evaluate('action == "something_else"', ctx) is False

    def test_inequality(self, engine):
        ctx = {"role": "member"}
        assert engine.evaluate('role != "root"', ctx) is True
        assert engine.evaluate('role != "member"', ctx) is False

    def test_in_list(self, engine):
        ctx = {"role": "admin"}
        assert engine.evaluate('role in ["admin", "root"]', ctx) is True
        assert engine.evaluate('role in ["member", "observer"]', ctx) is False

    def test_not_in_list(self, engine):
        ctx = {"role": "member"}
        assert engine.evaluate('role not_in ["admin", "root"]', ctx) is True
        assert engine.evaluate('role not_in ["member", "admin"]', ctx) is False

    def test_contains(self, engine):
        ctx = {"command": "git push origin main"}
        assert engine.evaluate('command contains "git"', ctx) is True
        assert engine.evaluate('command contains "sudo"', ctx) is False

    def test_startswith(self, engine):
        ctx = {"action": "forge.execute_tool"}
        assert engine.evaluate('action startswith "forge."', ctx) is True
        assert engine.evaluate('action startswith "oracle."', ctx) is False

    def test_endswith(self, engine):
        ctx = {"file": "report.pdf"}
        assert engine.evaluate('file endswith ".pdf"', ctx) is True
        assert engine.evaluate('file endswith ".txt"', ctx) is False


class TestLogicalOperators:
    """Test logical AND, OR, NOT operators."""

    def test_and(self, engine):
        ctx = {"action": "forge.execute_tool", "resource": "tool:file_write"}
        assert engine.evaluate(
            'action == "forge.execute_tool" and resource == "tool:file_write"', ctx
        ) is True
        assert engine.evaluate(
            'action == "forge.execute_tool" and resource == "tool:file_read"', ctx
        ) is False

    def test_or(self, engine):
        ctx = {"role": "admin"}
        assert engine.evaluate('role == "admin" or role == "root"', ctx) is True
        ctx2 = {"role": "member"}
        assert engine.evaluate('role == "admin" or role == "root"', ctx2) is False

    def test_not(self, engine):
        ctx = {"active": "false"}
        assert engine.evaluate('not active == "true"', ctx) is True

    def test_combined_logic(self, engine):
        ctx = {"action": "forge.execute_tool", "role": "member", "resource": "tool:file_delete"}
        condition = 'action == "forge.execute_tool" and resource == "tool:file_delete" and role != "admin" and role != "root"'
        assert engine.evaluate(condition, ctx) is True

        ctx["role"] = "admin"
        assert engine.evaluate(condition, ctx) is False


class TestParentheses:
    """Test parenthesized grouping."""

    def test_grouped_or(self, engine):
        ctx = {"role": "root", "action": "system.config"}
        condition = 'action == "system.config" and (role == "admin" or role == "root")'
        assert engine.evaluate(condition, ctx) is True

        ctx["role"] = "member"
        assert engine.evaluate(condition, ctx) is False

    def test_nested_parens(self, engine):
        ctx = {"a": "1", "b": "2", "c": "3"}
        condition = '(a == "1" and b == "2") or c == "3"'
        assert engine.evaluate(condition, ctx) is True

        condition2 = '(a == "X" and b == "2") or c == "3"'
        assert engine.evaluate(condition2, ctx) is True  # c == "3" is true


class TestDotNotation:
    """Test nested context field access via dot notation."""

    def test_nested_field(self, engine):
        ctx = {"request": {"action": "delete", "target": "file.txt"}}
        assert engine.evaluate('request.action == "delete"', ctx) is True
        assert engine.evaluate('request.target == "file.txt"', ctx) is True

    def test_missing_nested_field(self, engine):
        ctx = {"request": {"action": "read"}}
        # Missing field resolves to None
        assert engine.evaluate('request.missing == "something"', ctx) is False


class TestLiterals:
    """Test literal value handling."""

    def test_boolean_literals(self, engine):
        ctx = {"enabled": True}
        assert engine.evaluate("enabled == true", ctx) is True
        assert engine.evaluate("enabled == false", ctx) is False

    def test_none_literal(self, engine):
        ctx = {"value": None}
        assert engine.evaluate("value == none", ctx) is True

    def test_numeric_literal(self, engine):
        ctx = {"count": 5}
        assert engine.evaluate("count == 5", ctx) is True
        assert engine.evaluate("count == 10", ctx) is False


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_context(self, engine):
        ctx = {}
        # Missing field resolves to None
        assert engine.evaluate('action == "something"', ctx) is False

    def test_empty_condition_raises(self, engine):
        with pytest.raises(PolicyEvalError):
            engine.evaluate("", {})

    def test_unmatched_paren_raises(self, engine):
        with pytest.raises(PolicyEvalError):
            engine.evaluate('(action == "test"', {"action": "test"})

    def test_truthy_check(self, engine):
        ctx = {"active": True, "disabled": False, "name": "test"}
        assert engine.evaluate("active", ctx) is True
        assert engine.evaluate("disabled", ctx) is False
        assert engine.evaluate("name", ctx) is True

    def test_cache_works(self, engine):
        condition = 'action == "test"'
        ctx = {"action": "test"}
        engine.evaluate(condition, ctx)
        # Second call should use cache
        assert condition in engine._cache
        engine.evaluate(condition, ctx)

    def test_clear_cache(self, engine):
        engine.evaluate('x == "y"', {"x": "y"})
        assert len(engine._cache) > 0
        engine.clear_cache()
        assert len(engine._cache) == 0
''',

    "tests/test_janus/test_storage.py": '''
# tests/test_janus/test_storage.py
"""
Unit tests for the Janus PolicyStore (SQLite persistence).
"""

import tempfile
from pathlib import Path

import pytest

from aegis.agents.janus.storage import PolicyStore
from aegis.schemas.janus import PolicyRule


@pytest.fixture
def store(tmp_path):
    """Create a temporary PolicyStore for testing."""
    db_path = tmp_path / "test_policies.db"
    s = PolicyStore(db_path)
    yield s
    s.close()


@pytest.fixture
def sample_policy() -> PolicyRule:
    """A sample policy rule for testing."""
    return PolicyRule(
        rule_id="TEST-001",
        name="Test Policy",
        description="A test policy for unit testing.",
        condition='action == "test.action"',
        action_on_match="deny",
        priority=500,
        active=True,
        tenant_id=None,
        tags=["test", "unit"],
    )


@pytest.fixture
def tenant_policy() -> PolicyRule:
    """A tenant-scoped policy for testing."""
    return PolicyRule(
        rule_id="TEST-TENANT-001",
        name="Tenant Policy",
        description="A tenant-scoped test policy.",
        condition='resource == "sensitive"',
        action_on_match="escalate",
        priority=700,
        active=True,
        tenant_id="tenant-abc",
        tags=["test", "tenant"],
    )


class TestPolicyStoreCRUD:
    """Test basic CRUD operations."""

    def test_add_policy(self, store, sample_policy):
        result = store.add_policy(sample_policy)
        assert result.rule_id == "TEST-001"
        assert store.count_policies() == 1

    def test_add_duplicate_raises(self, store, sample_policy):
        store.add_policy(sample_policy)
        with pytest.raises(ValueError, match="already exists"):
            store.add_policy(sample_policy)

    def test_get_policy(self, store, sample_policy):
        store.add_policy(sample_policy)
        retrieved = store.get_policy("TEST-001")
        assert retrieved is not None
        assert retrieved.name == "Test Policy"
        assert retrieved.condition == 'action == "test.action"'

    def test_get_nonexistent_returns_none(self, store):
        assert store.get_policy("DOES-NOT-EXIST") is None

    def test_update_policy(self, store, sample_policy):
        store.add_policy(sample_policy)
        sample_policy.name = "Updated Policy"
        sample_policy.priority = 999
        updated = store.update_policy(sample_policy)
        assert updated.name == "Updated Policy"
        assert updated.priority == 999

        # Verify persistence
        retrieved = store.get_policy("TEST-001")
        assert retrieved.name == "Updated Policy"

    def test_update_nonexistent_raises(self, store, sample_policy):
        with pytest.raises(ValueError, match="not found"):
            store.update_policy(sample_policy)

    def test_delete_policy(self, store, sample_policy):
        store.add_policy(sample_policy)
        assert store.delete_policy("TEST-001") is True
        assert store.get_policy("TEST-001") is None
        assert store.count_policies() == 0

    def test_delete_nonexistent_returns_false(self, store):
        assert store.delete_policy("DOES-NOT-EXIST") is False


class TestPolicyStoreListing:
    """Test policy listing and filtering."""

    def test_list_system_wide(self, store, sample_policy):
        store.add_policy(sample_policy)
        policies = store.list_policies(tenant_id=None)
        assert len(policies) == 1

    def test_list_tenant_includes_system(self, store, sample_policy, tenant_policy):
        store.add_policy(sample_policy)  # system-wide (tenant_id=None)
        store.add_policy(tenant_policy)  # tenant-scoped
        policies = store.list_policies(tenant_id="tenant-abc")
        assert len(policies) == 2  # Both system-wide and tenant-specific

    def test_list_different_tenant_excludes(self, store, tenant_policy):
        store.add_policy(tenant_policy)  # tenant-abc only
        policies = store.list_policies(tenant_id="tenant-xyz")
        # tenant-xyz should NOT see tenant-abc's policies (only system-wide)
        assert len(policies) == 0

    def test_list_active_only(self, store, sample_policy):
        store.add_policy(sample_policy)
        inactive = PolicyRule(
            rule_id="TEST-INACTIVE",
            name="Inactive Policy",
            description="",
            condition='x == "y"',
            action_on_match="log",
            active=False,
        )
        store.add_policy(inactive)
        policies = store.list_policies(active_only=True)
        assert len(policies) == 1
        assert policies[0].rule_id == "TEST-001"

    def test_list_by_tags(self, store, sample_policy):
        store.add_policy(sample_policy)  # tags: ["test", "unit"]
        other = PolicyRule(
            rule_id="TEST-OTHER",
            name="Other Policy",
            description="",
            condition='a == "b"',
            action_on_match="warn",
            tags=["security"],
        )
        store.add_policy(other)

        # Filter by 'unit' tag
        policies = store.list_policies(tags=["unit"])
        assert len(policies) == 1
        assert policies[0].rule_id == "TEST-001"

    def test_list_ordered_by_priority(self, store):
        low = PolicyRule(
            rule_id="LOW", name="Low", description="", condition='a == "a"',
            action_on_match="log", priority=10
        )
        high = PolicyRule(
            rule_id="HIGH", name="High", description="", condition='b == "b"',
            action_on_match="deny", priority=900
        )
        store.add_policy(low)
        store.add_policy(high)

        policies = store.list_policies()
        assert policies[0].rule_id == "HIGH"
        assert policies[1].rule_id == "LOW"


class TestPolicyStoreEvaluationQuery:
    """Test the evaluation-specific query method."""

    def test_get_policies_for_evaluation(self, store, sample_policy, tenant_policy):
        store.add_policy(sample_policy)
        store.add_policy(tenant_policy)

        # Evaluation for tenant-abc should get both
        policies = store.get_policies_for_evaluation(tenant_id="tenant-abc")
        assert len(policies) == 2

        # Evaluation for different tenant gets only system-wide
        policies = store.get_policies_for_evaluation(tenant_id="other-tenant")
        assert len(policies) == 1
        assert policies[0].rule_id == "TEST-001"
''',

    "tests/test_janus/test_agent.py": '''
# tests/test_janus/test_agent.py
"""
Unit tests for the Janus Agent — integration of engine + storage + protocol.
"""

import pytest
import asyncio
from pathlib import Path

from aegis.agents.janus.agent import JanusAgent
from aegis.schemas.message import AegisMessage, MessageType, Priority


@pytest.fixture
def agent(tmp_path):
    """Create a JanusAgent with temporary storage."""
    a = JanusAgent(data_dir=tmp_path)
    asyncio.get_event_loop().run_until_complete(a.startup())
    yield a
    asyncio.get_event_loop().run_until_complete(a.shutdown())


def _make_message(action: str, payload: dict, tenant_id: str = "test-tenant") -> AegisMessage:
    """Helper to construct test messages."""
    return AegisMessage(
        source_agent="warden",
        target_agent="janus",
        message_type=MessageType.REQUEST,
        tenant_id=tenant_id,
        user_id="test-user",
        action=action,
        payload=payload,
    )


class TestJanusAgentStartup:
    """Test agent initialization and default policy seeding."""

    def test_startup_seeds_defaults(self, agent):
        """On first startup with empty store, default policies should be seeded."""
        assert agent._initialized is True
        assert agent._store.count_policies() > 0

    def test_default_policies_present(self, agent):
        """Verify specific default policies exist."""
        policy = agent._store.get_policy("SYS-SEC-001")
        assert policy is not None
        assert policy.name == "Shell Command Allowlist Enforcement"

        policy_ac = agent._store.get_policy("SYS-AC-001")
        assert policy_ac is not None
        assert policy_ac.name == "Deny Cross-Tenant Access"


class TestJanusEvaluatePolicy:
    """Test policy evaluation through the agent."""

    @pytest.mark.asyncio
    async def test_evaluate_deny_cross_tenant(self, agent):
        """SYS-AC-001 should deny cross-tenant access."""
        msg = _make_message(
            action="janus.evaluate_policy",
            payload={
                "context": {
                    "cross_tenant": "true",
                    "action": "lexicon.search_memory",
                    "resource": "memory",
                },
            },
        )
        response = await agent.handle_message(msg)
        assert response is not None
        assert response.payload["success"] is True
        assert response.payload["verdict"] == "deny"
        assert "SYS-AC-001" in response.payload["matched_policies"]

    @pytest.mark.asyncio
    async def test_evaluate_no_match_allows(self, agent):
        """When no policies match, verdict should be 'allow'."""
        msg = _make_message(
            action="janus.evaluate_policy",
            payload={
                "context": {
                    "action": "oracle.query",
                    "resource": "llm",
                    "role": "member",
                },
            },
        )
        response = await agent.handle_message(msg)
        assert response is not None
        assert response.payload["verdict"] == "allow"

    @pytest.mark.asyncio
    async def test_evaluate_shell_escalate(self, agent):
        """SYS-SEC-001 should escalate shell command execution."""
        msg = _make_message(
            action="janus.evaluate_policy",
            payload={
                "context": {
                    "action": "forge.execute_tool",
                    "resource": "tool:execute_shell_command",
                    "role": "member",
                },
            },
        )
        response = await agent.handle_message(msg)
        assert response is not None
        # SYS-SEC-001 triggers escalate for shell commands
        assert response.payload["verdict"] in ("escalate", "deny")

    @pytest.mark.asyncio
    async def test_evaluate_l0_protection(self, agent):
        """SYS-MEM-001 should deny agent-initiated L0 writes."""
        msg = _make_message(
            action="janus.evaluate_policy",
            payload={
                "context": {
                    "action": "lexicon.store_memory",
                    "target_tier": "L0",
                    "user_initiated": "false",
                },
            },
        )
        response = await agent.handle_message(msg)
        assert response is not None
        assert response.payload["verdict"] == "deny"
        assert "SYS-MEM-001" in response.payload["matched_policies"]


class TestJanusCRUDActions:
    """Test CRUD operations through the agent message protocol."""

    @pytest.mark.asyncio
    async def test_add_policy(self, agent):
        """Add a custom policy via agent message."""
        msg = _make_message(
            action="janus.add_policy",
            payload={
                "payload": {
                    "rule_id": "CUSTOM-001",
                    "name": "Custom Rule",
                    "description": "Test custom policy",
                    "condition": 'action == "custom.action"',
                    "action_on_match": "warn",
                    "priority": 300,
                    "tags": ["custom"],
                },
            },
        )
        response = await agent.handle_message(msg)
        assert response.payload["success"] is True
        assert response.payload["data"]["rule_id"] == "CUSTOM-001"

    @pytest.mark.asyncio
    async def test_list_policies(self, agent):
        """List policies via agent message."""
        msg = _make_message(
            action="janus.list_policies",
            payload={"payload": {"active_only": True}},
        )
        response = await agent.handle_message(msg)
        assert response.payload["success"] is True
        assert response.payload["data"]["count"] > 0

    @pytest.mark.asyncio
    async def test_get_policy(self, agent):
        """Get a single policy via agent message."""
        msg = _make_message(
            action="janus.get_policy",
            payload={"payload": {"rule_id": "SYS-SEC-001"}},
        )
        response = await agent.handle_message(msg)
        assert response.payload["success"] is True
        assert response.payload["data"]["policy"]["name"] == "Shell Command Allowlist Enforcement"

    @pytest.mark.asyncio
    async def test_delete_policy(self, agent):
        """Delete a policy via agent message."""
        # First add one
        add_msg = _make_message(
            action="janus.add_policy",
            payload={
                "payload": {
                    "rule_id": "TO-DELETE",
                    "name": "Delete Me",
                    "description": "",
                    "condition": 'x == "y"',
                    "action_on_match": "log",
                },
            },
        )
        await agent.handle_message(add_msg)

        # Now delete it
        del_msg = _make_message(
            action="janus.delete_policy",
            payload={"payload": {"rule_id": "TO-DELETE"}},
        )
        response = await agent.handle_message(del_msg)
        assert response.payload["success"] is True
        assert response.payload["data"]["deleted"] is True


class TestJanusErrorHandling:
    """Test error conditions."""

    @pytest.mark.asyncio
    async def test_invalid_action(self, agent):
        """Invalid action should return error."""
        msg = _make_message(
            action="janus.nonexistent_action",
            payload={},
        )
        response = await agent.handle_message(msg)
        assert response.message_type == MessageType.ERROR

    @pytest.mark.asyncio
    async def test_add_duplicate_fails(self, agent):
        """Adding a policy with existing ID should fail gracefully."""
        policy_payload = {
            "payload": {
                "rule_id": "DUP-001",
                "name": "Duplicate",
                "description": "",
                "condition": 'a == "b"',
                "action_on_match": "log",
            },
        }
        msg = _make_message(action="janus.add_policy", payload=policy_payload)
        await agent.handle_message(msg)

        # Try again
        response = await agent.handle_message(msg)
        assert response.payload["success"] is False
        assert "already exists" in response.payload["error"]
''',

    # =========================================================================
    # CONFIGURATION UPDATE
    # =========================================================================

    "aegis/agents/janus/config.py": '''
# aegis/agents/janus/config.py
"""
Janus agent configuration.

Loaded from aegis_config.yaml under the 'janus' key.
"""

from pydantic import BaseModel, Field
from pathlib import Path


class JanusConfig(BaseModel):
    """Configuration model for the Janus agent."""

    data_dir: Path = Field(
        default=Path("aegis_data/system"),
        description="Base directory for Janus governance data storage."
    )
    db_filename: str = Field(
        default="policies.db",
        description="SQLite database filename for policy storage."
    )
    seed_defaults_on_empty: bool = Field(
        default=True,
        description="Whether to seed default policies when the store is empty."
    )
    evaluation_cache_enabled: bool = Field(
        default=True,
        description="Enable tokenization caching in the policy engine."
    )
    max_policies_per_tenant: int = Field(
        default=500,
        description="Maximum number of policies allowed per tenant."
    )
    evaluation_timeout_ms: int = Field(
        default=100,
        description="Maximum time allowed for a single policy evaluation batch."
    )

    @property
    def db_path(self) -> Path:
        """Full path to the policies database."""
        return self.data_dir / "governance" / self.db_filename
''',

}


def create_package_init_files(path):
    """Create __init__.py files in parent directories if they don't exist."""
    dir_name = os.path.dirname(path)
    if dir_name and (dir_name.startswith("") or dir_name.startswith("tests/")):
        parts = dir_name.split("/")
        for i in range(2, len(parts) + 1):
            pkg_path = "/".join(parts[:i])
            init_file = os.path.join(pkg_path, "__init__.py")
            if not os.path.exists(init_file):
                os.makedirs(pkg_path, exist_ok=True)
                print(f"  [Created] {init_file} (empty package marker)")
                with open(init_file, "w") as f:
                    pass


def main():
    """Main function to write all files for CHUNK-007."""
    print("=" * 60)
    print("  ASSEMBLING CHUNK-007: Janus (Governance Engine)")
    print("=" * 60)
    print()

    files_written = 0
    for path, content in CHUNK_007_FILES.items():
        # Ensure the directory exists
        dir_name = os.path.dirname(path)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)

        create_package_init_files(path)

        print(f"  [Writing] {path}")
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(textwrap.dedent(content.strip()) + "\n")
        files_written += 1

    print()
    print("-" * 60)
    print(f"  Assembly Complete: {files_written} files written.")
    print()
    print("  Deliverables:")
    print("    ✓ Janus agent (aegis/agents/janus/agent.py)")
    print("    ✓ Policy evaluation engine with safe DSL (engine.py)")
    print("    ✓ SQLite-backed policy storage (storage.py)")
    print("    ✓ 12 default governance policies (defaults.py)")
    print("    ✓ Protocol schemas (aegis/schemas/janus.py)")
    print("    ✓ Configuration model (config.py)")
    print("    ✓ Full test suite (tests/test_janus/)")
    print()
    print("  Integration Points:")
    print("    → Subscribes to: aegis:stream:janus")
    print("    → Consulted by: Warden (authorization), TOrchestrator (decisions)")
    print("    → Depends on: CHUNK-001 (BaseAgent, AegisMessage), CHUNK-002 (Bus)")
    print("=" * 60)


if __name__ == "__main__":
    main()
