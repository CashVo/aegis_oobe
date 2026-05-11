# aegis/schemas/oracle.py
# Implements: Part VI §6.2 — Oracle Protocol
"""
Oracle protocol schemas. Defines the canonical request/response contracts
for all LLM inference operations routed through The Oracle agent.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional, Union

from pydantic import BaseModel, Field

# Integration with CHUNK-006: Lexicon schemas for ContextPacket
try:
    from aegis.schemas.lexicon import ContextPacket
except ImportError:
    # Graceful degradation if Lexicon schemas not yet available
    ContextPacket = None  # type: ignore[assignment, misc]


class OracleAction(str, Enum):
    """Supported Oracle operations. Implements Part VI §6.2."""
    QUERY = "query"            # Standard LLM request
    STRUCTURED = "structured"  # JSON-mode / structured output
    EMBED = "embed"            # Embedding generation
    CLASSIFY = "classify"      # Classification task


class OracleRequest(BaseModel):
    """
    Canonical Oracle request contract.
    Implements: Part VI §6.2 — OracleRequest
    """
    action: OracleAction
    prompt: str
    system_prompt: Optional[str] = None
    context_packet: Optional[dict] = None  # Serialized ContextPacket from Lexicon
    llm_preference: Optional[str] = None  # "fast", "capable", "local", or model name
    temperature: float = 0.7
    max_tokens: int = 2000
    response_format: Optional[str] = None  # "json", "text", etc.


class OracleResponse(BaseModel):
    """
    Canonical Oracle response contract.
    Implements: Part VI §6.2 — OracleResponse
    """
    success: bool
    content: Union[str, dict, list] = ""
    llm_used: str = ""
    tokens_used: dict = Field(default_factory=lambda: {
        "prompt": 0, "completion": 0, "total": 0
    })
    cached: bool = False
    latency_ms: float = 0.0


class ModelDefinition(BaseModel):
    """Configuration for a registered LLM model."""
    llm_id: str
    provider: str  # "ollama", "openai_compat"
    display_name: Optional[str] = None
    context_window: int = 4096
    preference_tags: list[str] = Field(default_factory=list)
    supports_json_mode: bool = False
    supports_embeddings: bool = False
    default_temperature: float = 0.7
    max_output_tokens: int = 4096


class ProviderConfig(BaseModel):
    """Configuration for an LLM provider backend."""
    provider_type: str  # "ollama", "openai_compat"
    base_url: str = "http://localhost:11434"
    api_key_env: Optional[str] = None
    enabled: bool = True
    timeout_seconds: int = 120
    max_concurrent: int = 4
    max_retries: int = 3


class EmbeddingRequest(BaseModel):
    """Request specifically for embedding generation."""
    texts: list[str]
    model: Optional[str] = None


class EmbeddingResponse(BaseModel):
    """Response containing generated embeddings."""
    embeddings: list[list[float]]
    used: str
    dimensions: int
    latency_ms: float


class CacheEntry(BaseModel):
    """Schema for a cached Oracle response."""
    cache_key: str
    response_json: str
    used: str
    created_at: str
    expires_at: str
    hit_count: int = 0
