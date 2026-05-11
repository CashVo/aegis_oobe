# aegis/agents/lexicon/governor.py
# Implements: Part IV §4.4 — Memory Governor & Promotion Pipeline
"""
Memory Governor — Manages the lifecycle of memories across tiers.

Promotion Pipeline:
    L5 → L3: At session end, reviews scratchpad for significant items.
    L3 → L1/L2: Periodically analyzes episodic memory for recurring patterns.
    L1/L2 → L0: Never automatic. May suggest updates for user approval.

Demotion / Eviction:
    L5: Expires at session end.
    L3: Subject to retention policies (default 365 days).
    L1/L2: Can be deprecated but never auto-deleted.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from aegis.schemas.lexicon import (
    GovernorDecision,
    GovernorStatus,
    MemoryGovernorAction,
)
from aegis.agents.lexicon.tiers.l3_episodic import L3EpisodicTier
from aegis.agents.lexicon.tiers.l5_scratchpad import L5ScratchpadTier
from aegis.agents.lexicon.storage import get_sessions_dir

logger = logging.getLogger(__name__)


class MemoryGovernor:
    """
    Manages the lifecycle of memories across tiers.
    Handles promotions, demotions, evictions, and L0 update suggestions.
    """

    def __init__(
        self,
        tenant_id: str,
        user_id: str,
        l3: L3EpisodicTier,
        base_dir: Optional[str] = None,
        retention_days: int = 365,
    ):
        self.tenant_id = tenant_id
        self.user_id = user_id
        self._l3 = l3
        self._base_dir = base_dir
        self._retention_days = retention_days
        self._last_promotion_run: Optional[datetime] = None
        self._last_eviction_run: Optional[datetime] = None
        self._pending_decisions: List[GovernorDecision] = []

    async def process_session_end(
        self,
        l5: L5ScratchpadTier,
        significance_threshold: float = 0.3,
    ) -> List[GovernorDecision]:
        """
        Process session end: review L5 scratchpad and promote significant items to L3.

        Promotion Pipeline (L5 → L3):
            At session end, the Governor reviews L5 scratchpad contents.
            Significant decisions, outcomes, and events are promoted to L3.

        Args:
            l5: The L5 scratchpad tier for the ending session.
            significance_threshold: Minimum significance score to promote (0.0–1.0).

        Returns:
            List of GovernorDecisions made during this promotion pass.
        """
        decisions: List[GovernorDecision] = []

        # Get snapshot of L5 before clearing
        snapshot = await l5.snapshot()
        entries = snapshot.get("entries", {})

        if not entries:
            logger.debug("No L5 entries to evaluate for promotion.")
            await l5.clear()
            return decisions

        # Save snapshot to sessions directory for audit trail
        await self._save_session_snapshot(snapshot)

        # Evaluate each entry for promotion significance
        for key, value in entries.items():
            significance = self._evaluate_significance(key, value)

            if significance >= significance_threshold:
                # Promote to L3
                content = self._format_for_l3(key, value)
                entry_id = await self._l3.append(
                    content=content,
                    event_type="session_promoted",
                    tags=["l5_promotion", f"session:{l5.session_id}"],
                    source=f"l5:{l5.session_id}",
                    session_id=l5.session_id,
                )

                decision = GovernorDecision(
                    source_tier="L5",
                    target_tier="L3",
                    action=MemoryGovernorAction.PROMOTE,
                    content_id=entry_id,
                    rationale=f"Significant session entry (score={significance:.2f}): {key}",
                )
                decisions.append(decision)
                logger.debug(f"L5→L3 promotion: {key} (significance={significance:.2f})")

        # Clear the scratchpad
        await l5.clear()

        self._last_promotion_run = datetime.now(timezone.utc)
        logger.info(
            f"Session end processed: {len(decisions)} entries promoted from L5→L3 "
            f"(out of {len(entries)} total)"
        )

        return decisions

    def _evaluate_significance(self, key: str, value: Any) -> float:
        """
        Evaluate the significance of a scratchpad entry for promotion.
        Uses heuristics based on key naming and content characteristics.

        Args:
            key: The scratchpad key.
            value: The scratchpad value.

        Returns:
            Significance score (0.0–1.0).
        """
        score = 0.0

        # Key-based heuristics
        high_signal_keys = ["decision", "outcome", "result", "conclusion", "action", "plan"]
        medium_signal_keys = ["note", "insight", "observation", "context", "summary"]
        low_signal_keys = ["temp", "scratch", "draft", "wip", "debug"]

        key_lower = key.lower()
        if any(k in key_lower for k in high_signal_keys):
            score += 0.5
        elif any(k in key_lower for k in medium_signal_keys):
            score += 0.3
        elif any(k in key_lower for k in low_signal_keys):
            score -= 0.2

        # Content-based heuristics
        content_str = json.dumps(value) if not isinstance(value, str) else value
        content_length = len(content_str)

        # Longer content tends to be more significant
        if content_length > 500:
            score += 0.3
        elif content_length > 100:
            score += 0.2
        elif content_length > 20:
            score += 0.1

        # Structured data (dicts/lists) often represents organized thought
        if isinstance(value, (dict, list)) and len(str(value)) > 50:
            score += 0.1

        return max(0.0, min(1.0, score))

    def _format_for_l3(self, key: str, value: Any) -> str:
        """Format a scratchpad entry for storage in L3 episodic memory."""
        if isinstance(value, str):
            return f"[Session Note — {key}]: {value}"
        else:
            return f"[Session Data — {key}]: {json.dumps(value, indent=2)}"

    async def _save_session_snapshot(self, snapshot: Dict[str, Any]) -> None:
        """Save a session snapshot to the sessions directory for audit."""
        sessions_dir = get_sessions_dir(self.tenant_id, self.user_id, self._base_dir)
        sessions_dir.mkdir(parents=True, exist_ok=True)

        session_id = snapshot.get("session_id", "unknown")
        snapshot_path = sessions_dir / f"{session_id}.json"

        try:
            snapshot_path.write_text(
                json.dumps(snapshot, indent=2, default=str),
                encoding="utf-8",
            )
            logger.debug(f"Session snapshot saved: {snapshot_path}")
        except Exception as e:
            logger.error(f"Failed to save session snapshot: {e}")

    async def run_eviction(self) -> int:
        """
        Run the eviction process for L3 entries past retention period.

        Returns:
            Number of entries evicted.
        """
        evicted = await self._l3.evict_expired()
        self._last_eviction_run = datetime.now(timezone.utc)
        return evicted

    async def get_status(self) -> GovernorStatus:
        """Get the current status of the Memory Governor."""
        l3_count = await self._l3.count()

        return GovernorStatus(
            pending_promotions=len(
                [d for d in self._pending_decisions if d.action == MemoryGovernorAction.PROMOTE]
            ),
            pending_demotions=len(
                [d for d in self._pending_decisions if d.action == MemoryGovernorAction.DEMOTE]
            ),
            last_promotion_run=self._last_promotion_run,
            last_eviction_run=self._last_eviction_run,
            l3_entry_count=l3_count,
            l3_retention_days=self._retention_days,
        )

    async def suggest_l0_update(
        self, key: str, value: Any, rationale: str
    ) -> GovernorDecision:
        """
        Create a suggestion for L0 update (requires user approval).
        L0 is NEVER automatically modified.

        Args:
            key: The L0 key to update.
            value: The proposed value.
            rationale: Why this update is suggested.

        Returns:
            A GovernorDecision with requires_user_approval=True.
        """
        decision = GovernorDecision(
            source_tier="governor",
            target_tier="L0",
            action=MemoryGovernorAction.SUGGEST_L0_UPDATE,
            content_id=key,
            rationale=rationale,
            requires_user_approval=True,
        )
        self._pending_decisions.append(decision)
        logger.info(f"L0 update suggested: {key} — {rationale}")
        return decision
