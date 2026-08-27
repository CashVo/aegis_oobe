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
        # Call parent init for heartbeat and bus support
        super().__init__(agent_id=self.agent_id, subscriptions=self.subscriptions)
        
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
