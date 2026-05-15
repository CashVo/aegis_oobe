# aegis/main.py
# Implements: Part III §3.3 — Entry Point
"""
Aegis System Entry Point.

Launches the System Manager, which bootstraps Redis, the Scheduler,
and all council agents in the correct dependency order.

Usage::

    python -m aegis.main
    # or
    python -m aegis

Configuration is loaded from ``aegis_config.yaml`` in the current
working directory. Override with env vars (see SystemManager docs).
"""

from __future__ import annotations

import asyncio
import logging
import sys

import structlog


def configure_logging(level: str = "INFO") -> None:
    """
    Configure structured logging for the Aegis system.

    Uses structlog for JSON-formatted, contextual logging as specified
    in Part III §3.2 (Observer Service logging requirements).
    """
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(colors=True),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Also configure stdlib logging for third-party libraries
    logging.basicConfig(
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        level=getattr(logging, level.upper(), logging.INFO),
        stream=sys.stderr,
    )


def main() -> None:
    """
    Main entry point for the Aegis system.

    Configures logging, creates the SystemManager, and runs it
    until a shutdown signal is received.
    """
    configure_logging()
    log = structlog.get_logger("aegis.main")

    log.info("=" * 60)
    log.info("  PROJECT AEGIS — Initializing")
    log.info("=" * 60)

    from aegis.manager.system_manager import SystemManager

    manager = SystemManager()

    try:
        asyncio.run(manager.run())
    except KeyboardInterrupt:
        log.info("Aegis shutdown via KeyboardInterrupt")
    except Exception as exc:
        log.critical("Aegis fatal error: %s", exc, exc_info=True)
        sys.exit(1)

    log.info("Aegis has exited cleanly.")


if __name__ == "__main__":
    main()
