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
