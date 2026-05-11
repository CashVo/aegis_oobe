# aegis/agents/lexicon/agent.py
# Implements: Part II §2.1 (Lexicon role), Part IV (full), Part VI §6.3
"""
Lexicon Agent — The Aegis Memory Control Plane.

Role: Memory Governor. Manages all tiers of memory (L0–L5), context assembly,
memory lifecycle, and external memory exposure via MCP.

Subscribes to: aegis:stream:lexicon
Publishes to: aegis:stream:broadcast (memory events)
"""

import logging
from typing import Any, Dict, Optional

from aegis.agents.lexicon.context_router import ContextRouter
from aegis.agents.lexicon.governor import MemoryGovernor
from aegis.agents.lexicon.storage import ensure_user_storage
from aegis.agents.lexicon.tiers.l0_identity import L0IdentityTier
from aegis.agents.lexicon.tiers.l1_domain import L1DomainTier
from aegis.agents.lexicon.tiers.l2_workflow import L2WorkflowTier
from aegis.agents.lexicon.tiers.l3_episodic import L3EpisodicTier
from aegis.agents.lexicon.tiers.l4_artifacts import L4ArtifactTier
from aegis.agents.lexicon.tiers.l5_scratchpad import L5ScratchpadTier
from aegis.schemas.lexicon import (
    ContextRequest,
    LexiconAction,
    LexiconRequest,
    LexiconResponse,
    MemorySearchRequest,
    MemoryStoreRequest,
    MemoryPromoteRequest,
)

logger = logging.getLogger(__name__)


class LexiconAgent:
    """
    The Lexicon Memory Control Plane agent.

    Responsibilities:
        - Manage all memory tiers (L0–L5)
        - Assemble context for other agents via the Context Router
        - Execute the Memory Governor promotion/eviction pipeline
        - Handle memory CRUD operations

    Integration:
        - Subscribes to: aegis:stream:lexicon
        - Publishes to: aegis:stream:broadcast
    """

    agent_id: str = "lexicon"
    subscriptions: list = ["aegis:stream:lexicon"]

    def __init__(
        self,
        redis_client: Optional[Any] = None,
        base_dir: Optional[str] = None,
    ):
        """
        Initialize the Lexicon agent.

        Args:
            redis_client: Async Redis client for L5 scratchpad and bus communication.
            base_dir: Override for the base data directory.
        """
        self._redis = redis_client
        self._base_dir = base_dir
        self._user_contexts: Dict[str, Dict[str, Any]] = {}
        # Cache: {tenant_id:user_id -> {l0, l1, l2, l3, l4, router, governor}}

    async def startup(self) -> None:
        """Agent initialization logic."""
        logger.info("Lexicon agent starting up...")
        # Lexicon is ready to handle messages once startup completes
        logger.info("Lexicon agent ready.")

    async def shutdown(self) -> None:
        """Graceful teardown logic."""
        logger.info("Lexicon agent shutting down...")
        # Clean up any active L5 sessions
        for context_key, ctx in self._user_contexts.items():
            if "l5_sessions" in ctx:
                for session_id, l5 in ctx["l5_sessions"].items():
                    try:
                        governor = ctx.get("governor")
                        if governor:
                            await governor.process_session_end(l5)
                    except Exception as e:
                        logger.error(f"Error during L5 cleanup for {context_key}: {e}")
        logger.info("Lexicon agent stopped.")

    async def handle_message(self, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Process an incoming message directed to Lexicon.

        Args:
            message: The AegisMessage payload (dict form).

        Returns:
            Response dict or None.
        """
        try:
            # Extract request from message payload
            payload = message.get("payload", {})
            action_str = payload.get("action") or message.get("action", "")

            # Parse as LexiconRequest
            request = LexiconRequest(
                action=LexiconAction(action_str.replace("lexicon.", "")),
                tenant_id=message.get("tenant_id", payload.get("tenant_id", "")),
                user_id=message.get("user_id", payload.get("user_id", "")),
                payload=payload,
            )

            return await self._dispatch(request)

        except Exception as e:
            logger.error(f"Lexicon message handling error: {e}", exc_info=True)
            return LexiconResponse(
                success=False,
                action=LexiconAction.ASSEMBLE_CONTEXT,
                error=str(e),
            ).model_dump()

    async def _dispatch(self, request: LexiconRequest) -> Dict[str, Any]:
        """Dispatch a LexiconRequest to the appropriate handler."""
        handlers = {
            LexiconAction.ASSEMBLE_CONTEXT: self._handle_assemble_context,
            LexiconAction.STORE_MEMORY: self._handle_store_memory,
            LexiconAction.SEARCH_MEMORY: self._handle_search_memory,
            LexiconAction.PROMOTE_MEMORY: self._handle_promote_memory,
            LexiconAction.QUERY_TIER: self._handle_query_tier,
            LexiconAction.GET_GOVERNOR_STATUS: self._handle_governor_status,
            LexiconAction.SESSION_END: self._handle_session_end,
        }

        handler = handlers.get(request.action)
        if not handler:
            return LexiconResponse(
                success=False,
                action=request.action,
                error=f"Unknown action: {request.action}",
            ).model_dump()

        return await handler(request)

    async def _get_user_context(
        self, tenant_id: str, user_id: str
    ) -> Dict[str, Any]:
        """
        Get or initialize the memory context for a specific tenant/user.
        Lazily initializes tier objects and ensures storage exists.
        """
        context_key = f"{tenant_id}:{user_id}"

        if context_key not in self._user_contexts:
            # Ensure storage structure exists
            await ensure_user_storage(tenant_id, user_id, self._base_dir)

            # Initialize tier objects
            l0 = L0IdentityTier(tenant_id, user_id, self._base_dir)
            l1 = L1DomainTier(tenant_id, user_id, self._base_dir)
            l2 = L2WorkflowTier(tenant_id, user_id, self._base_dir)
            l3 = L3EpisodicTier(tenant_id, user_id, self._base_dir)
            l4 = L4ArtifactTier(tenant_id, user_id, self._base_dir)

            router = ContextRouter(l0=l0, l1=l1, l2=l2, l3=l3, l4=l4)
            governor = MemoryGovernor(tenant_id, user_id, l3, self._base_dir)

            self._user_contexts[context_key] = {
                "l0": l0,
                "l1": l1,
                "l2": l2,
                "l3": l3,
                "l4": l4,
                "router": router,
                "governor": governor,
                "l5_sessions": {},  # session_id -> L5ScratchpadTier
            }

        return self._user_contexts[context_key]

    def _get_or_create_l5(
        self, ctx: Dict[str, Any], session_id: str, tenant_id: str, user_id: str
    ) -> L5ScratchpadTier:
        """Get or create an L5 scratchpad for a specific session."""
        if session_id not in ctx["l5_sessions"]:
            l5 = L5ScratchpadTier(
                tenant_id=tenant_id,
                user_id=user_id,
                session_id=session_id,
                redis_client=self._redis,
            )
            ctx["l5_sessions"][session_id] = l5
            ctx["router"].set_l5(l5)
        return ctx["l5_sessions"][session_id]

    # ─────────────────────────────────────────────
    # Action Handlers
    # ─────────────────────────────────────────────

    async def _handle_assemble_context(
        self, request: LexiconRequest
    ) -> Dict[str, Any]:
        """Handle ASSEMBLE_CONTEXT: assemble context from memory tiers."""
        ctx = await self._get_user_context(request.tenant_id, request.user_id)
        router: ContextRouter = ctx["router"]

        # Build ContextRequest from payload
        payload = request.payload
        context_request = ContextRequest(
            query=payload.get("query", ""),
            tenant_id=request.tenant_id,
            user_id=request.user_id,
            scope=payload.get("scope", ["L0", "L1", "L2", "L3"]),
            token_budget=payload.get("token_budget", 4000),
            session_id=payload.get("session_id"),
        )

        # If session_id provided, ensure L5 is available
        if context_request.session_id:
            self._get_or_create_l5(
                ctx, context_request.session_id, request.tenant_id, request.user_id
            )

        packet = await router.assemble(context_request)

        return LexiconResponse(
            success=True,
            action=LexiconAction.ASSEMBLE_CONTEXT,
            data=packet.model_dump(),
        ).model_dump()

    async def _handle_store_memory(self, request: LexiconRequest) -> Dict[str, Any]:
        """Handle STORE_MEMORY: store a new memory entry in the appropriate tier."""
        ctx = await self._get_user_context(request.tenant_id, request.user_id)
        payload = request.payload

        tier = payload.get("tier", "L3")
        content = payload.get("content", "")
        tags = payload.get("tags", [])
        source = payload.get("source")
        metadata = payload.get("metadata", {})
        session_id = payload.get("session_id")

        if not content:
            return LexiconResponse(
                success=False,
                action=LexiconAction.STORE_MEMORY,
                error="Content is required for memory storage.",
            ).model_dump()

        entry_id = None

        if tier == "L1":
            entry_id = await ctx["l1"].store(
                content=content,
                category=metadata.get("category", "general"),
                tags=tags,
                source=source,
                metadata=metadata,
            )
        elif tier == "L2":
            entry_id = await ctx["l2"].store(
                content=content,
                pattern_type=metadata.get("pattern_type", "general"),
                tags=tags,
                source=source,
                metadata=metadata,
                confidence=metadata.get("confidence", 0.5),
            )
        elif tier == "L3":
            entry_id = await ctx["l3"].append(
                content=content,
                event_type=metadata.get("event_type", "general"),
                tags=tags,
                source=source,
                session_id=session_id,
                metadata=metadata,
            )
        elif tier == "L4":
            entry_id = await ctx["l4"].store(
                name=metadata.get("name", "Unnamed artifact"),
                artifact_type=metadata.get("artifact_type", "file"),
                path_or_uri=content,
                description=metadata.get("description"),
                tags=tags,
                metadata=metadata,
            )
        elif tier == "L5":
            if not session_id:
                return LexiconResponse(
                    success=False,
                    action=LexiconAction.STORE_MEMORY,
                    error="session_id is required for L5 storage.",
                ).model_dump()
            l5 = self._get_or_create_l5(ctx, session_id, request.tenant_id, request.user_id)
            key = metadata.get("key", f"entry_{len(await l5.get_all())}")
            await l5.set(key, content)
            entry_id = f"l5:{session_id}:{key}"
        elif tier == "L0":
            return LexiconResponse(
                success=False,
                action=LexiconAction.STORE_MEMORY,
                error="L0 is user-editable only. Use SUGGEST_L0_UPDATE via the governor.",
            ).model_dump()
        else:
            return LexiconResponse(
                success=False,
                action=LexiconAction.STORE_MEMORY,
                error=f"Unknown tier: {tier}",
            ).model_dump()

        return LexiconResponse(
            success=True,
            action=LexiconAction.STORE_MEMORY,
            data={"entry_id": entry_id, "tier": tier},
        ).model_dump()

    async def _handle_search_memory(self, request: LexiconRequest) -> Dict[str, Any]:
        """Handle SEARCH_MEMORY: search across memory tiers."""
        ctx = await self._get_user_context(request.tenant_id, request.user_id)
        payload = request.payload

        query = payload.get("query", "")
        tiers = payload.get("tiers", ["L1", "L2", "L3"])
        limit = payload.get("limit", 20)
        tags = payload.get("tags")

        if not query:
            return LexiconResponse(
                success=False,
                action=LexiconAction.SEARCH_MEMORY,
                error="Query is required for memory search.",
            ).model_dump()

        results: Dict[str, list] = {}

        for tier_name in tiers:
            if tier_name == "L1":
                results["L1"] = await ctx["l1"].search(query, tags=tags, limit=limit)
            elif tier_name == "L2":
                results["L2"] = await ctx["l2"].search(query, limit=limit)
            elif tier_name == "L3":
                results["L3"] = await ctx["l3"].search_fts(query, limit=limit)
            elif tier_name == "L4":
                results["L4"] = await ctx["l4"].search(query, tags=tags, limit=limit)

        return LexiconResponse(
            success=True,
            action=LexiconAction.SEARCH_MEMORY,
            data={"results": results, "query": query, "tiers_searched": tiers},
        ).model_dump()

    async def _handle_promote_memory(self, request: LexiconRequest) -> Dict[str, Any]:
        """Handle PROMOTE_MEMORY: promote an entry from one tier to another."""
        ctx = await self._get_user_context(request.tenant_id, request.user_id)
        payload = request.payload

        source_tier = payload.get("source_tier", "")
        target_tier = payload.get("target_tier", "")
        entry_id = payload.get("entry_id", "")
        rationale = payload.get("rationale", "Manual promotion")

        if target_tier == "L0":
            # L0 updates require user approval — create suggestion only
            governor: MemoryGovernor = ctx["governor"]
            decision = await governor.suggest_l0_update(
                key=entry_id,
                value=payload.get("content", ""),
                rationale=rationale,
            )
            return LexiconResponse(
                success=True,
                action=LexiconAction.PROMOTE_MEMORY,
                data={
                    "decision": decision.model_dump(),
                    "note": "L0 update suggested. Requires user approval.",
                },
            ).model_dump()

        # For L3→L1 or L3→L2 promotions
        if source_tier == "L3" and target_tier in ("L1", "L2"):
            # Fetch the L3 entry
            entry = await ctx["l3"].get_by_id(entry_id)
            if not entry:
                return LexiconResponse(
                    success=False,
                    action=LexiconAction.PROMOTE_MEMORY,
                    error=f"Entry {entry_id} not found in {source_tier}.",
                ).model_dump()

            # Store in target tier
            if target_tier == "L1":
                new_id = await ctx["l1"].store(
                    content=entry["content"],
                    category=payload.get("category", "promoted"),
                    tags=entry.get("tags", []) + ["promoted_from_l3"],
                    source=f"promotion:{entry_id}",
                )
            else:  # L2
                new_id = await ctx["l2"].store(
                    content=entry["content"],
                    pattern_type=payload.get("pattern_type", "observed"),
                    tags=entry.get("tags", []) + ["promoted_from_l3"],
                    source=f"promotion:{entry_id}",
                )

            return LexiconResponse(
                success=True,
                action=LexiconAction.PROMOTE_MEMORY,
                data={
                    "new_entry_id": new_id,
                    "source_tier": source_tier,
                    "target_tier": target_tier,
                    "rationale": rationale,
                },
            ).model_dump()

        return LexiconResponse(
            success=False,
            action=LexiconAction.PROMOTE_MEMORY,
            error=f"Unsupported promotion path: {source_tier} → {target_tier}",
        ).model_dump()

    async def _handle_query_tier(self, request: LexiconRequest) -> Dict[str, Any]:
        """Handle QUERY_TIER: direct query against a specific tier."""
        ctx = await self._get_user_context(request.tenant_id, request.user_id)
        payload = request.payload

        tier = payload.get("tier", "")
        query = payload.get("query", "")

        if tier == "L0":
            key = payload.get("key")  # Optional dot-notation key
            data = await ctx["l0"].query(key)
            return LexiconResponse(
                success=True,
                action=LexiconAction.QUERY_TIER,
                data={"tier": "L0", "result": data},
            ).model_dump()
        elif tier == "L1":
            results = await ctx["l1"].search(query, limit=payload.get("limit", 20))
            return LexiconResponse(
                success=True,
                action=LexiconAction.QUERY_TIER,
                data={"tier": "L1", "results": results},
            ).model_dump()
        elif tier == "L2":
            results = await ctx["l2"].search(query, limit=payload.get("limit", 20))
            return LexiconResponse(
                success=True,
                action=LexiconAction.QUERY_TIER,
                data={"tier": "L2", "results": results},
            ).model_dump()
        elif tier == "L3":
            results = await ctx["l3"].search_fts(query, limit=payload.get("limit", 20))
            return LexiconResponse(
                success=True,
                action=LexiconAction.QUERY_TIER,
                data={"tier": "L3", "results": results},
            ).model_dump()
        elif tier == "L4":
            results = await ctx["l4"].search(query, limit=payload.get("limit", 20))
            return LexiconResponse(
                success=True,
                action=LexiconAction.QUERY_TIER,
                data={"tier": "L4", "results": results},
            ).model_dump()
        else:
            return LexiconResponse(
                success=False,
                action=LexiconAction.QUERY_TIER,
                error=f"Unknown or unsupported tier for direct query: {tier}",
            ).model_dump()

    async def _handle_governor_status(
        self, request: LexiconRequest
    ) -> Dict[str, Any]:
        """Handle GET_GOVERNOR_STATUS: return Memory Governor status."""
        ctx = await self._get_user_context(request.tenant_id, request.user_id)
        governor: MemoryGovernor = ctx["governor"]
        status = await governor.get_status()

        return LexiconResponse(
            success=True,
            action=LexiconAction.GET_GOVERNOR_STATUS,
            data=status.model_dump(),
        ).model_dump()

    async def _handle_session_end(self, request: LexiconRequest) -> Dict[str, Any]:
        """Handle SESSION_END: trigger L5→L3 promotion pipeline."""
        ctx = await self._get_user_context(request.tenant_id, request.user_id)
        payload = request.payload
        session_id = payload.get("session_id", "")

        if not session_id:
            return LexiconResponse(
                success=False,
                action=LexiconAction.SESSION_END,
                error="session_id is required.",
            ).model_dump()

        l5 = ctx["l5_sessions"].get(session_id)
        if not l5:
            return LexiconResponse(
                success=True,
                action=LexiconAction.SESSION_END,
                data={"note": "No active L5 scratchpad for this session.", "promoted": 0},
            ).model_dump()

        governor: MemoryGovernor = ctx["governor"]
        decisions = await governor.process_session_end(l5)

        # Remove the session from active L5 sessions
        del ctx["l5_sessions"][session_id]
        ctx["router"].remove_l5()

        return LexiconResponse(
            success=True,
            action=LexiconAction.SESSION_END,
            data={
                "session_id": session_id,
                "promoted": len(decisions),
                "decisions": [d.model_dump() for d in decisions],
            },
        ).model_dump()

    # ─────────────────────────────────────────────
    # Public API (for direct invocation by other agents in-process)
    # ─────────────────────────────────────────────

    async def assemble_context(self, request: ContextRequest) -> Dict[str, Any]:
        """
        Public convenience method for context assembly.
        Can be called directly by other agents without going through the bus.
        """
        lexicon_request = LexiconRequest(
            action=LexiconAction.ASSEMBLE_CONTEXT,
            tenant_id=request.tenant_id,
            user_id=request.user_id,
            payload={
                "query": request.query,
                "scope": request.scope,
                "token_budget": request.token_budget,
                "session_id": request.session_id,
            },
        )
        return await self._handle_assemble_context(lexicon_request)

    async def initialize_user_memory(self, tenant_id: str, user_id: str) -> None:
        """
        Initialize memory storage for a new user.
        Called during user onboarding (UC-5).
        """
        await ensure_user_storage(tenant_id, user_id, self._base_dir)
        await self._get_user_context(tenant_id, user_id)
        logger.info(f"Memory initialized for user: tenant={tenant_id}, user={user_id}")
