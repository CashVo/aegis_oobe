# aegis/agents/oracle/prompt_engine.py
# Implements: Part II §2.1 — Prompt templating and context assembly
"""
Prompt Engine — Assembles complete prompts from templates, context packets,
and user input. Handles context packet formatting and token-aware truncation.
"""

from __future__ import annotations

from typing import Optional

import structlog

logger = structlog.get_logger(__name__)

# ── Default Templates ────────────────────────────────────────────────

DEFAULT_SYSTEM_PROMPT = (
    "You are Aegis, an intelligent AI assistant built on a multi-agent "
    "architecture. You are helpful, accurate, and concise. When you have "
    "relevant context about the user, incorporate it naturally into your "
    "responses."
)

CLASSIFICATION_SYSTEM_PROMPT = (
    "You are a classification engine. Analyze the input and return a JSON "
    "object with the following fields:\n"
    '- "label": the classification label\n'
    '- "confidence": a float between 0.0 and 1.0\n'
    '- "reasoning": a brief explanation of the classification\n'
    "Respond ONLY with valid JSON. No other text."
)

JSON_OUTPUT_INSTRUCTION = (
    "\n\nIMPORTANT: You MUST respond with valid JSON only. "
    "No markdown fences, no explanatory text outside the JSON structure."
)

CONTEXT_HEADER = "\n\n--- Relevant Context ---\n"
CONTEXT_FOOTER = "\n--- End Context ---\n\n"
CONTEXT_FRAGMENT_TEMPLATE = "[{tier}] (relevance: {relevance:.2f})\n{content}\n"


class PromptEngine:
    """
    Assembles prompts from components: system prompt, context packet,
    user prompt, and optional template instructions.

    Responsibilities:
    - Format context packets from Lexicon into prompt-ready text
    - Apply prompt templates for different action types
    - Insert JSON-mode instructions when required
    - Provide classification-specific prompt assembly
    """

    def __init__(self, config: dict | None = None) -> None:
        """
        Initialize the prompt engine.

        Args:
            config: Templates configuration dict.
        """
        config = config or {}
        self._default_system = config.get("default_system", DEFAULT_SYSTEM_PROMPT)
        self._custom_templates: dict[str, str] = config.get("custom", {})

    def assemble(
        self,
        prompt: str,
        system_prompt: str | None = None,
        context_packet: dict | None = None,
        force_json_instruction: bool = False,
    ) -> tuple[str, str]:
        """
        Assemble a complete (system_prompt, user_prompt) pair.

        Args:
            prompt: The user's raw prompt text.
            system_prompt: Optional override for the system prompt.
            context_packet: Serialized ContextPacket from Lexicon (CHUNK-006).
            force_json_instruction: If True, append JSON output instructions.

        Returns:
            Tuple of (assembled_system_prompt, assembled_user_prompt).
        """
        # System prompt
        sys_prompt = system_prompt or self._default_system

        if force_json_instruction:
            sys_prompt += JSON_OUTPUT_INSTRUCTION

        # User prompt with context
        user_prompt = prompt

        if context_packet:
            context_text = self._format_context_packet(context_packet)
            if context_text:
                user_prompt = context_text + user_prompt

        logger.debug(
            "prompt_engine.assembled",
            system_len=len(sys_prompt),
            user_len=len(user_prompt),
            has_context=context_packet is not None,
        )

        return sys_prompt, user_prompt

    def assemble_classification(
        self,
        prompt: str,
        system_prompt: str | None = None,
        context_packet: dict | None = None,
    ) -> tuple[str, str]:
        """
        Assemble prompts specifically for classification tasks.

        Uses the classification system prompt template and enforces
        JSON output format.

        Args:
            prompt: The text to classify.
            system_prompt: Optional override (defaults to classification template).
            context_packet: Optional context from Lexicon.

        Returns:
            Tuple of (system_prompt, user_prompt).
        """
        sys_prompt = system_prompt or CLASSIFICATION_SYSTEM_PROMPT

        user_prompt = prompt
        if context_packet:
            context_text = self._format_context_packet(context_packet)
            if context_text:
                user_prompt = context_text + user_prompt

        return sys_prompt, user_prompt

    def _format_context_packet(self, context_packet: dict) -> str:
        """
        Format a serialized ContextPacket into prompt-ready text.

        Expected context_packet structure (from Lexicon CHUNK-006):
        {
            "fragments": [
                {"tier": "L0", "content": "...", "relevance": 0.95},
                {"tier": "L1", "content": "...", "relevance": 0.82},
                ...
            ],
            "total_tokens": 1200,
            "tiers_queried": ["L0", "L1", "L2", "L3"]
        }

        Args:
            context_packet: Serialized ContextPacket dict.

        Returns:
            Formatted context string, or empty string if no fragments.
        """
        fragments = context_packet.get("fragments", [])
        if not fragments:
            return ""

        # Sort by relevance descending
        sorted_fragments = sorted(
            fragments, key=lambda f: f.get("relevance", 0), reverse=True
        )

        parts = [CONTEXT_HEADER]
        for frag in sorted_fragments:
            parts.append(
                CONTEXT_FRAGMENT_TEMPLATE.format(
                    tier=frag.get("tier", "??"),
                    relevance=frag.get("relevance", 0.0),
                    content=frag.get("content", ""),
                )
            )
        parts.append(CONTEXT_FOOTER)

        return "".join(parts)

    def get_template(self, name: str) -> str | None:
        """
        Retrieve a custom prompt template by name.

        Args:
            name: Template identifier.

        Returns:
            Template string if found, None otherwise.
        """
        return self._custom_templates.get(name)

    def register_template(self, name: str, template: str) -> None:
        """
        Register a custom prompt template.

        Args:
            name: Template identifier.
            template: The template string.
        """
        self._custom_templates[name] = template
        logger.info("prompt_engine.template_registered", name=name)
