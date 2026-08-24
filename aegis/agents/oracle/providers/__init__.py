# aegis/agents/oracle/providers/__init__.py
"""
LLM Provider implementations for the Oracle agent.
Local-first per Part I, Principle 1.
"""

from aegis.agents.oracle.providers.base import LLMProvider, ProviderError
from aegis.agents.oracle.providers.ollama import OllamaProvider
from aegis.agents.oracle.providers.openai_compat import OpenAICompatProvider
from aegis.agents.oracle.providers.openrouter import OpenRouterProvider

__all__ = ["LLMProvider", "ProviderError", "OllamaProvider", "OpenAICompatProvider", "OpenRouterProvider"]
