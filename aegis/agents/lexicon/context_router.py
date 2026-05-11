# aegis/agents/lexicon/context_router.py
# Implements: Part IV §4.3 — Context Router
"""
Context Router — Lexicon's primary interface for serving other agents.
Assembles context from multiple memory tiers, ranked by relevance,
within a specified token budget.
"""

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

from aegis.schemas.lexicon import (
    ContextFragment,
    ContextPacket,
    ContextRequest,
)
from aegis.agents.lexicon.tiers.l0_identity import L0IdentityTier
from aegis.agents.lexicon.tiers.l1_domain import L1DomainTier
from aegis.agents.lexicon.tiers.l2_workflow import L2WorkflowTier
from aegis.agents.lexicon.tiers.l3_episodic import L3EpisodicTier
from aegis.agents.lexicon.tiers.l4_artifacts import L4ArtifactTier
from aegis.agents.lexicon.tiers.l5_scratchpad import L5ScratchpadTier

logger = logging.getLogger(__name__)

# Approximate token estimation: ~4 chars per token (conservative)
CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    """Estimate token count from text length (conservative approximation)."""
    return len(text) // CHARS_PER_TOKEN + 1


class ContextRouter:
    """
    Assembles context from memory tiers based on a ContextRequest.

    Behavior (from spec §4.3):
        1. Receives a ContextRequest specifying query, scope, token_budget, tenant/user.
        2. Queries each requested tier in parallel.
        3. Ranks and selects results by relevance.
        4. Assembles a ContextPacket that fits within the token_budget.
        5. Returns the ContextPacket.
    """

    def __init__(
        self,
        l0: L0IdentityTier,
        l1: L1DomainTier,
        l2: L2WorkflowTier,
        l3: L3EpisodicTier,
        l4: L4ArtifactTier,
        l5: Optional[L5ScratchpadTier] = None,
    ):
        self._tiers = {
            "L0": l0,
            "L1": l1,
            "L2": l2,
            "L3": l3,
            "L4": l4,
        }
        if l5:
            self._tiers["L5"] = l5

    def set_l5(self, l5: L5ScratchpadTier) -> None:
        """Set or update the L5 scratchpad tier (session-dependent)."""
        self._tiers["L5"] = l5

    def remove_l5(self) -> None:
        """Remove the L5 tier reference (session ended)."""
        self._tiers.pop("L5", None)

    async def assemble(self, request: ContextRequest) -> ContextPacket:
        """
        Assemble a context packet from memory tiers.

        Args:
            request: The ContextRequest specifying what context to assemble.

        Returns:
            A ContextPacket containing ranked fragments within the token budget.
        """
        start_time = time.time()

        # Determine which tiers to query
        tiers_to_query = []
        for tier_name in request.scope:
            if tier_name in self._tiers:
                tiers_to_query.append(tier_name)
            else:
                logger.debug(f"Tier {tier_name} not available, skipping")

        # Include L5 if session_id provided and L5 is available
        if request.session_id and "L5" in self._tiers and "L5" not in tiers_to_query:
            tiers_to_query.append("L5")

        # Query all tiers in parallel
        tasks = []
        tier_names = []
        for tier_name in tiers_to_query:
            tier = self._tiers[tier_name]
            tasks.append(tier.get_context_fragments(request.query))
            tier_names.append(tier_name)

        # Gather results
        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

        # Collect all fragments
        all_fragments: List[Dict[str, Any]] = []
        for tier_name, result in zip(tier_names, raw_results):
            if isinstance(result, Exception):
                logger.error(f"Error querying tier {tier_name}: {result}")
                continue
            all_fragments.extend(result)

        # Sort by relevance (descending)
        all_fragments.sort(key=lambda f: f.get("relevance", 0), reverse=True)

        # Assemble within token budget
        assembled_fragments: List[ContextFragment] = []
        total_tokens = 0

        for frag_data in all_fragments:
            content = frag_data.get("content", "")
            token_count = estimate_tokens(content)

            if total_tokens + token_count > request.token_budget:
                # Try to truncate if it's the first fragment and we have nothing yet
                if not assembled_fragments:
                    available_chars = (request.token_budget - total_tokens) * CHARS_PER_TOKEN
                    if available_chars > 100:  # Minimum useful content
                        content = content[:available_chars] + "..."
                        token_count = estimate_tokens(content)
                    else:
                        continue
                else:
                    continue

            fragment = ContextFragment(
                tier=frag_data.get("tier", "unknown"),
                content=content,
                relevance=frag_data.get("relevance", 0.0),
                metadata=frag_data.get("metadata", {}),
                token_count=token_count,
            )
            assembled_fragments.append(fragment)
            total_tokens += token_count

        assembly_time_ms = (time.time() - start_time) * 1000

        packet = ContextPacket(
            tenant_id=request.tenant_id,
            user_id=request.user_id,
            fragments=assembled_fragments,
            total_tokens=total_tokens,
            tiers_queried=tiers_to_query,
            assembly_time_ms=round(assembly_time_ms, 2),
        )

        logger.info(
            f"Context assembled: {len(assembled_fragments)} fragments, "
            f"{total_tokens} tokens, {assembly_time_ms:.1f}ms "
            f"(budget={request.token_budget}, tiers={tiers_to_query})"
        )

        return packet
