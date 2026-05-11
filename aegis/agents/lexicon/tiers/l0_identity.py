# aegis/agents/lexicon/tiers/l0_identity.py
# Implements: Part IV §4.2 — L0 Core Identity Tier
"""
L0 Core Identity Tier.
Stable user principles, values, and preferences stored as human-editable YAML.
USER-EDITABLE ONLY — agents may suggest but never directly modify.
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from aegis.agents.lexicon.storage import get_l0_path

logger = logging.getLogger(__name__)


class L0IdentityTier:
    """
    Manages L0 Core Identity memory.

    Properties:
        - Format: YAML file (l0_identity.yaml)
        - Mutability: User-editable only
        - TTL: Permanent
    """

    def __init__(self, tenant_id: str, user_id: str, base_dir: Optional[str] = None):
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.base_dir = base_dir
        self._cache: Optional[Dict[str, Any]] = None
        self._path: Path = get_l0_path(tenant_id, user_id, base_dir)

    @property
    def path(self) -> Path:
        """Path to the L0 identity YAML file."""
        return self._path

    async def load(self) -> Dict[str, Any]:
        """
        Load L0 identity from YAML file.
        Results are cached until invalidated.

        Returns:
            Dictionary containing the full L0 identity structure.
        """
        if self._cache is not None:
            return self._cache

        if not self._path.exists():
            logger.warning(f"L0 identity file not found: {self._path}")
            return {}

        try:
            content = self._path.read_text(encoding="utf-8")
            data = yaml.safe_load(content) or {}
            self._cache = data
            logger.debug(f"L0 identity loaded for user={self.user_id}")
            return data
        except yaml.YAMLError as e:
            logger.error(f"Failed to parse L0 identity YAML: {e}")
            return {}

    async def query(self, key: Optional[str] = None) -> Any:
        """
        Query L0 identity data.

        Args:
            key: Optional dot-notation key (e.g., 'identity.display_name').
                 If None, returns the entire L0 structure.

        Returns:
            The value at the specified key, or the full structure.
        """
        data = await self.load()
        if key is None:
            return data

        # Support dot-notation access
        parts = key.split(".")
        current = data
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return None
        return current

    async def get_context_fragments(self, query: str) -> List[Dict[str, Any]]:
        """
        Retrieve L0 content as context fragments for the Context Router.
        L0 is always fully included (it's the user's constitution).

        Args:
            query: The search query (used for metadata, L0 is always fully returned).

        Returns:
            List of context fragments from L0.
        """
        data = await self.load()
        if not data:
            return []

        # Serialize the full L0 as a readable string
        fragments = []

        # Identity section
        identity = data.get("identity", {})
        if identity:
            content = f"User Identity: {yaml.dump(identity, default_flow_style=False).strip()}"
            fragments.append({
                "tier": "L0",
                "content": content,
                "relevance": 1.0,  # L0 is always maximally relevant
                "metadata": {"section": "identity"}
            })

        # Principles
        principles = data.get("principles", [])
        if principles:
            content = "User Principles:\n" + "\n".join(f"- {p}" for p in principles)
            fragments.append({
                "tier": "L0",
                "content": content,
                "relevance": 1.0,
                "metadata": {"section": "principles"}
            })

        # Values
        values = data.get("values", [])
        if values:
            content = "User Values:\n" + "\n".join(f"- {v}" for v in values)
            fragments.append({
                "tier": "L0",
                "content": content,
                "relevance": 1.0,
                "metadata": {"section": "values"}
            })

        # Preferences
        preferences = data.get("preferences", {})
        if preferences:
            content = f"User Preferences: {yaml.dump(preferences, default_flow_style=False).strip()}"
            fragments.append({
                "tier": "L0",
                "content": content,
                "relevance": 1.0,
                "metadata": {"section": "preferences"}
            })

        # Domains
        domains = data.get("domains", [])
        if domains:
            content = "User Domains:\n" + yaml.dump(domains, default_flow_style=False).strip()
            fragments.append({
                "tier": "L0",
                "content": content,
                "relevance": 1.0,
                "metadata": {"section": "domains"}
            })

        return fragments

    def invalidate_cache(self) -> None:
        """Invalidate the cached L0 data, forcing a reload on next access."""
        self._cache = None
        logger.debug(f"L0 cache invalidated for user={self.user_id}")

    async def suggest_update(self, key: str, value: Any, rationale: str) -> Dict[str, Any]:
        """
        Suggest an update to L0 (requires user approval).
        Does NOT modify the file — returns a suggestion for the user.

        Args:
            key: The key to update (dot-notation).
            value: The proposed new value.
            rationale: Why this update is suggested.

        Returns:
            A suggestion dict for user review.
        """
        return {
            "type": "l0_update_suggestion",
            "key": key,
            "proposed_value": value,
            "rationale": rationale,
            "requires_user_approval": True,
            "current_value": await self.query(key),
        }
