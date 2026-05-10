# aegis/observer/logging.py
# Implements: Part III, §3.2 — Structured Logging (structlog, JSON-formatted)
"""
Configures structured logging for the entire Aegis system.
Uses structlog for JSON-formatted, contextual logging.
All log entries include tenant_id, user_id, correlation_id, and agent_id.

Provides a FallbackLogger for stderr output when Observer is unavailable (RT-3).
"""

import sys
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import structlog
from structlog.types import EventDict


# ─── Processors ──────────────────────────────────────────────────────

def add_timestamp(logger: Any, method_name: str, event_dict: EventDict) -> EventDict:
    """Add ISO-format UTC timestamp to every log entry."""
    event_dict["timestamp"] = datetime.now(timezone.utc).isoformat()
    return event_dict


def add_log_level(logger: Any, method_name: str, event_dict: EventDict) -> EventDict:
    """Ensure log level is present."""
    event_dict["level"] = method_name
    return event_dict


def sanitize_event_dict(logger: Any, method_name: str, event_dict: EventDict) -> EventDict:
    """Remove None values and ensure serializable output."""
    return {k: v for k, v in event_dict.items() if v is not None}


# ─── Configuration ───────────────────────────────────────────────────

def configure_logging(
    log_level: str = "INFO",
    json_output: bool = True,
    log_file: Optional[str] = None,
) -> None:
    """
    Configure structlog for the Aegis system.

    Args:
        log_level: Minimum log level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        json_output: If True, output JSON-formatted logs. Otherwise, console-friendly.
        log_file: Optional file path to write logs to (in addition to stdout).
    """
    # Set up standard library logging as structlog's output
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, log_level.upper(), logging.INFO),
    )

    # Add file handler if specified
    if log_file:
        file_handler = logging.FileHandler(log_file, mode="a", encoding="utf-8")
        file_handler.setLevel(getattr(logging, log_level.upper(), logging.INFO))
        logging.getLogger().addHandler(file_handler)

    # Choose renderer based on output format
    if json_output:
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    # Configure structlog
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.filter_by_level,
            add_timestamp,
            add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            sanitize_event_dict,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Set the formatter for the root handler
    formatter = structlog.stdlib.ProcessorFormatter(
        processor=renderer,
        foreign_pre_chain=[
            structlog.contextvars.merge_contextvars,
            add_timestamp,
            add_log_level,
            structlog.processors.format_exc_info,
        ],
    )
    for handler in logging.getLogger().handlers:
        handler.setFormatter(formatter)


def get_logger(
    agent_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
    user_id: Optional[str] = None,
    **initial_context: Any,
) -> structlog.stdlib.BoundLogger:
    """
    Get a bound structured logger with Aegis context fields.

    Args:
        agent_id: The agent requesting the logger.
        tenant_id: Current tenant context.
        user_id: Current user context.
        **initial_context: Additional context to bind.

    Returns:
        A bound structlog logger instance.
    """
    logger = structlog.get_logger()
    bindings: Dict[str, Any] = {}

    if agent_id:
        bindings["agent_id"] = agent_id
    if tenant_id:
        bindings["tenant_id"] = tenant_id
    if user_id:
        bindings["user_id"] = user_id
    bindings.update(initial_context)

    if bindings:
        logger = logger.bind(**bindings)

    return logger


# ─── Fallback Logger (RT-3 Mitigation) ──────────────────────────────

class FallbackLogger:
    """
    Minimal stderr logger used when the Observer service is unavailable.
    Implements RT-3 mitigation: agents fall back to local stderr logging
    if Observer crashes.

    Outputs JSON-formatted log lines to stderr for later collection.
    """

    def __init__(self, agent_id: str):
        self.agent_id = agent_id

    def _emit(self, level: str, message: str, **context: Any) -> None:
        """Write a JSON log line to stderr."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": level,
            "agent_id": self.agent_id,
            "event": message,
            **context,
        }
        sys.stderr.write(json.dumps(entry) + "\n")
        sys.stderr.flush()

    def debug(self, message: str, **ctx: Any) -> None:
        self._emit("debug", message, **ctx)

    def info(self, message: str, **ctx: Any) -> None:
        self._emit("info", message, **ctx)

    def warning(self, message: str, **ctx: Any) -> None:
        self._emit("warning", message, **ctx)

    def error(self, message: str, **ctx: Any) -> None:
        self._emit("error", message, **ctx)

    def critical(self, message: str, **ctx: Any) -> None:
        self._emit("critical", message, **ctx)
