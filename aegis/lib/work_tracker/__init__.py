"""Work Tracker Client Wrapper for Aegis.

Thin wrapper that re-exports the work-tracker client for use within Aegis.
This ensures both Hermes (via plugin) and Aegis use the same underlying library.
"""

from __future__ import annotations

# Re-export everything from work-tracker
try:
    import work_tracker as wt_module
    from work_tracker import (
        WorkTrackerClient,
        get_client,
        set_client,
        Session,
        Request,
        GitActivity,
        Task,
        DailyAggregate,
        DailyModelUsage,
        AgentType,
        SessionStatus,
        RequestStatus,
        TaskStatus,
        TaskCategory,
        ModelRouter,
        ModelConfig,
        TIER_CHAIN,
        CompletionRequest,
        CompletionResponse,
        CircuitBreaker,
        RateLimiter,
        TokenAccountant,
        get_router,
        set_router,
        GitCollector,
        collect_git_activity,
    )

    __all__ = [
        "WorkTrackerClient",
        "get_client",
        "set_client",
        "Session",
        "Request",
        "GitActivity",
        "Task",
        "DailyAggregate",
        "DailyModelUsage",
        "AgentType",
        "SessionStatus",
        "RequestStatus",
        "TaskStatus",
        "TaskCategory",
        "ModelRouter",
        "ModelConfig",
        "TIER_CHAIN",
        "CompletionRequest",
        "CompletionResponse",
        "CircuitBreaker",
        "RateLimiter",
        "TokenAccountant",
        "get_router",
        "set_router",
        "GitCollector",
        "collect_git_activity",
    ]

except ImportError:
    # work-tracker not installed - provide stubs for type hints
    __all__ = [
        "WorkTrackerClient",
        "get_client",
        "set_client",
        "ModelRouter",
        "get_router",
        "set_router",
    ]

    class WorkTrackerClient:
        """Stub when work-tracker not installed."""
        pass

    def get_client(*args, **kwargs):
        raise ImportError("work-tracker package not installed. Install with: pip install -e /path/to/work-tracker")

    def set_client(*args, **kwargs):
        pass

    class ModelRouter:
        """Stub when work-tracker not installed."""
        pass

    def get_router(*args, **kwargs):
        raise ImportError("work-tracker package not installed. Install with: pip install -e /path/to/work-tracker")

    def set_router(*args, **kwargs):
        pass