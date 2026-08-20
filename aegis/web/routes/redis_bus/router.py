# aegis/web/routes/redis_bus/router.py
# API routes for Redis Bus Observability

import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from aegis.web.core.dependencies import get_bus, get_redis_client
from aegis.web.core.pagination import PaginationParams, PaginatedResponse, get_pagination_params
from aegis.web.core.filters import FilterParams, get_filter_params
from aegis.web.core.charting import ChartData, create_chart_response, create_time_series_chart, create_bar_chart, create_funnel_chart
from aegis.bus.redis_bus import RedisBus
from redis.asyncio import Redis

from aegis.web.routes.redis_bus.models import (
    StreamSummary,
    StreamDetail,
    MessageListItem,
    MessageDetail,
    PipelineState,
    TokenChartDataPoint,
    CumulativeChartDataPoint,
    CumulativeChartResponse,
    TokenChartResponse,
    OverviewStats,
    MessageActionRequest,
    MessageActionResponse,
    StreamFilters,
    MessageFilters,
)
from aegis.web.routes.redis_bus.service import RedisBusService
from aegis.web.routes.redis_bus.storage import (
    ObservabilityStorage,
    ObservabilityArchiver,
    get_observability_storage,
    start_archiver,
    stop_archiver,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/redis-bus", tags=["Redis Bus Observability"])


# ============================================
# Lifespan Events
# ============================================

@router.on_event("startup")
async def startup_observability():
    """Initialize observability storage and archiver on startup."""
    try:
        storage = await get_observability_storage()
        # Note: archiver needs redis_service, which we get from the app state
        # This will be started when the first request comes in
        logger.info("Observability storage initialized")
    except Exception as e:
        logger.error(f"Failed to initialize observability storage: {e}")


@router.on_event("shutdown")
async def shutdown_observability():
    """Stop archiver on shutdown."""
    await stop_archiver()
    logger.info("Observability archiver stopped")


# ============================================
# Dependency Injection
# ============================================

async def get_redis_bus_service(request: Request) -> RedisBusService:
    """Get RedisBusService instance."""
    redis_client = await get_redis_client(request)
    return RedisBusService(redis_client)


async def get_observability_storage_dep(request: Request) -> ObservabilityStorage:
    """Get ObservabilityStorage instance."""
    return await get_observability_storage()


# ============================================
# Stream Endpoints
# ============================================

@router.get("/streams", response_model=List[StreamSummary])
async def list_streams(
    request: Request,
    service: RedisBusService = Depends(get_redis_bus_service),
    filters: StreamFilters = Depends(),  # Will need custom dependency
):
    """List all Redis streams with summary statistics."""
    summaries = await service.get_all_stream_summaries()

    # Apply filters
    if filters.agent_id:
        summaries = [s for s in summaries if filters.agent_id in s["agent_id"]]
    if not filters.include_broadcast:
        summaries = [s for s in summaries if not s["is_broadcast"]]
    if filters.min_messages > 0:
        summaries = [s for s in summaries if s["length"] >= filters.min_messages]
    if filters.has_pending is not None:
        if filters.has_pending:
            summaries = [s for s in summaries if s["pending_count"] > 0]
        else:
            summaries = [s for s in summaries if s["pending_count"] == 0]

    return [StreamSummary(**s) for s in summaries]


@router.get("/streams/{stream_name}", response_model=StreamDetail)
async def get_stream_detail(
    stream_name: str,
    request: Request,
    service: RedisBusService = Depends(get_redis_bus_service),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    """Get detailed stream information with recent messages."""
    summary = await service.get_stream_summary(stream_name)

    # Get recent messages
    start_id = "-"
    end_id = "+"
    # For pagination, we'd need cursor-based; for now just get recent
    messages = await service.get_messages(stream_name, count=page_size)

    summary["recent_messages"] = [MessageListItem(**m) for m in messages]
    return StreamDetail(**summary)


@router.get("/streams/{stream_name}/messages", response_model=PaginatedResponse[MessageListItem])
async def list_stream_messages(
    stream_name: str,
    request: Request,
    service: RedisBusService = Depends(get_redis_bus_service),
    pagination: PaginationParams = Depends(get_pagination_params),
    # Filters
    message_type: Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    source_agent: Optional[str] = Query(None),
    target_agent: Optional[str] = Query(None),
    correlation_id: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
):
    """List messages in a stream with pagination and filtering."""
    filters = {}
    if message_type: filters["message_type"] = message_type
    if priority: filters["priority"] = priority
    if status: filters["status"] = status
    if source_agent: filters["source_agent"] = source_agent
    if target_agent: filters["target_agent"] = target_agent
    if correlation_id: filters["correlation_id"] = correlation_id
    if action: filters["action"] = action
    if start: filters["start"] = datetime.fromisoformat(start.replace("Z", "+00:00"))
    if end: filters["end"] = datetime.fromisoformat(end.replace("Z", "+00:00"))
    if search: filters["search"] = search

    # For cursor pagination, use entry_id range
    # Simple approach: get more messages and filter
    messages = await service.get_messages(
        stream_name,
        count=pagination.page_size * 3,
        filters=filters,
    )

    # Apply pagination
    total = len(messages)
    start_idx = pagination.offset
    end_idx = min(start_idx + pagination.page_size, total)
    page_items = messages[start_idx:end_idx]

    return PaginatedResponse.create(
        items=[MessageListItem(**m) for m in page_items],
        page=pagination.page,
        page_size=pagination.page_size,
        total_items=total,
    )


@router.get("/streams/{stream_name}/messages/{entry_id}", response_model=MessageDetail)
async def get_message_detail(
    stream_name: str,
    entry_id: str,
    request: Request,
    service: RedisBusService = Depends(get_redis_bus_service),
):
    """Get full detail for a single message."""
    detail = await service.get_message_detail(stream_name, entry_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Message not found")
    return MessageDetail(**detail)


@router.get("/streams/{stream_name}/pending")
async def get_pending_messages(
    stream_name: str,
    request: Request,
    group: Optional[str] = Query(None),
    service: RedisBusService = Depends(get_redis_bus_service),
    count: int = Query(100, ge=1, le=500),
):
    """Get pending messages for a consumer group."""
    # Get consumer groups
    groups = await service.redis.xinfo_groups(stream_name)
    if not groups:
        return {"stream": stream_name, "groups": [], "pending": []}

    # If group not specified, use first group
    if not group:
        group = groups[0]["name"].decode() if isinstance(groups[0]["name"], bytes) else groups[0]["name"]

    pending = await service.get_pending_messages(stream_name, group, count)

    return {
        "stream": stream_name,
        "group": group,
        "available_groups": [g["name"].decode() if isinstance(g["name"], bytes) else g["name"] for g in groups],
        "pending": [MessageListItem(**p) for p in pending],
    }


@router.get("/streams/{stream_name}/groups")
async def get_consumer_groups(
    stream_name: str,
    request: Request,
    service: RedisBusService = Depends(get_redis_bus_service),
):
    """Get consumer groups for a stream."""
    summary = await service.get_stream_summary(stream_name)
    return {
        "stream": stream_name,
        "groups": summary.get("consumer_groups_detail", []),
    }


# ============================================
# Analytics Endpoints
# ============================================

@router.get("/stats/overview", response_model=OverviewStats)
async def get_overview_stats(
    request: Request,
    service: RedisBusService = Depends(get_redis_bus_service),
):
    """Get global overview statistics."""
    streams = await service.list_streams()

    total_messages = 0
    total_pending = 0
    total_groups = 0
    total_rate = 0.0
    active_agents = set()

    for stream in streams:
        summary = await service.get_stream_summary(stream)
        total_messages += summary["length"]
        total_pending += summary["pending_count"]
        total_groups += summary["consumer_groups"]
        total_rate += summary["msgs_per_sec"]
        active_agents.add(summary["agent_id"])

    return OverviewStats(
        total_streams=len(streams),
        total_messages=total_messages,
        total_pending=total_pending,
        total_consumer_groups=total_groups,
        active_agents=len(active_agents),
        msgs_per_sec=total_rate,
        avg_latency_ms=0.0,  # Would need more computation
        error_rate=0.0,
        total_tokens_24h=0,
        total_requests_24h=0,
    )


@router.get("/stats/pipeline", response_model=PipelineState)
async def get_pipeline_state(
    request: Request,
    service: RedisBusService = Depends(get_redis_bus_service),
    stuck_threshold: int = Query(5, description="Minutes before considering message stuck"),
):
    """Get pipeline health state."""
    state = await service.get_pipeline_state(stuck_threshold_minutes=stuck_threshold)
    return PipelineState(**state)


# ============================================
# Chart Endpoints
# ============================================

@router.get("/charts/tokens/{stream_name}", response_model=TokenChartResponse)
async def get_token_chart(
    stream_name: str,
    request: Request,
    service: RedisBusService = Depends(get_redis_bus_service),
    limit: int = Query(100, ge=1, le=500),
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
):
    """Get token usage chart data for a stream."""
    start_dt = datetime.fromisoformat(start.replace("Z", "+00:00")) if start else None
    end_dt = datetime.fromisoformat(end.replace("Z", "+00:00")) if end else None

    data = await service.get_token_chart_data(stream_name, limit, start_dt, end_dt)
    return TokenChartResponse(**data)


@router.get("/charts/cumulative", response_model=CumulativeChartResponse)
async def get_cumulative_chart(
    request: Request,
    service: RedisBusService = Depends(get_redis_bus_service),
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    granularity: str = Query("hour", pattern="^(minute|hour|day)$"),
    agents: Optional[str] = Query(None, description="Comma-separated agent IDs"),
    types: Optional[str] = Query(None, description="Comma-separated message types"),
    streams: Optional[str] = Query(None, description="Comma-separated stream names"),
):
    """Get cumulative token/request chart data with date range filters."""
    # Default to last 24 hours
    end_dt = datetime.fromisoformat(end.replace("Z", "+00:00")) if end else datetime.now(timezone.utc)
    start_dt = datetime.fromisoformat(start.replace("Z", "+00:00")) if start else end_dt - timedelta(hours=24)

    agent_list = agents.split(",") if agents else None
    type_list = types.split(",") if types else None
    stream_list = streams.split(",") if streams else None

    data = await service.get_cumulative_chart_data(
        start_dt, end_dt, granularity, agent_list, type_list, stream_list
    )
    return CumulativeChartResponse(**data)


@router.get("/charts/rate")
async def get_rate_chart(
    request: Request,
    service: RedisBusService = Depends(get_redis_bus_service),
    window: int = Query(3600, description="Window in seconds"),
    granularity: int = Query(60, description="Bucket size in seconds"),
):
    """Get messages/second rate over time."""
    streams = await service.list_streams()

    end_ms = int(time.time() * 1000)
    start_ms = end_ms - window * 1000
    bucket_ms = granularity * 1000
    num_buckets = max(1, window // granularity)

    buckets = {}
    for i in range(num_buckets):
        bucket_start = start_ms + i * bucket_ms
        bucket_dt = datetime.fromtimestamp(bucket_start / 1000, tz=timezone.utc)
        buckets[bucket_start] = {"timestamp": bucket_dt, "count": 0, "by_stream": {}}

    for stream in streams:
        try:
            entries = await service.redis.xrange(stream, min=f"{start_ms}-0", max=f"{end_ms}-0", count=10000)
            for entry_id, _ in entries:
                entry_id_str = entry_id.decode() if isinstance(entry_id, bytes) else entry_id
                entry_ts = int(entry_id_str.split("-")[0])
                bucket_start = (entry_ts // bucket_ms) * bucket_ms
                if bucket_start in buckets:
                    buckets[bucket_start]["count"] += 1
                    buckets[bucket_start]["by_stream"][stream] = buckets[bucket_start]["by_stream"].get(stream, 0) + 1
        except Exception:
            continue

    # Build time series
    sorted_buckets = sorted(buckets.items())
    timestamps = [b[1]["timestamp"] for b in sorted_buckets]
    total_counts = [b[1]["count"] for b in sorted_buckets]

    # By stream
    all_streams = set()
    for b in buckets.values():
        all_streams.update(b["by_stream"].keys())

    by_stream = {}
    for s in all_streams:
        by_stream[s] = [b[1]["by_stream"].get(s, 0) for _, b in sorted_buckets]

    # Create Plotly chart
    fig = create_time_series_chart(
        x=timestamps,
        y_series={"Total": total_counts, **by_stream},
        title="Messages per Second",
        x_title="Time",
        y_title="Messages/sec",
        chart_type="line",
    )

    return create_chart_response(fig, title="Message Rate", description=f"Rate over last {window}s, {granularity}s buckets")


# ============================================
# Message Actions
# ============================================

@router.post("/messages/action", response_model=MessageActionResponse)
async def message_action(
    request: Request,
    action_req: MessageActionRequest,
    stream: str = Query(...),
    entry_id: str = Query(...),
    service: RedisBusService = Depends(get_redis_bus_service),
):
    """Perform an action on a message (delete, reassign, move, retry, acknowledge)."""
    action = action_req.action

    try:
        if action == "delete":
            success = await service.delete_message(stream, entry_id)
            return MessageActionResponse(
                success=success,
                message="Message deleted" if success else "Failed to delete message",
                entry_id=entry_id,
            )

        elif action == "reassign":
            if not action_req.target_agent:
                raise HTTPException(status_code=400, detail="target_agent required for reassign")
            new_entry_id = await service.reassign_message(stream, entry_id, action_req.target_agent)
            return MessageActionResponse(
                success=new_entry_id is not None,
                message=f"Message reassigned to {action_req.target_agent}" if new_entry_id else "Failed to reassign",
                entry_id=entry_id,
                new_entry_id=new_entry_id,
            )

        elif action == "move":
            if not action_req.target_stream:
                raise HTTPException(status_code=400, detail="target_stream required for move")
            new_entry_id = await service.move_message(stream, entry_id, action_req.target_stream)
            return MessageActionResponse(
                success=new_entry_id is not None,
                message=f"Message moved to {action_req.target_stream}" if new_entry_id else "Failed to move",
                entry_id=entry_id,
                new_entry_id=new_entry_id,
            )

        elif action == "retry":
            new_entry_id = await service.retry_message(stream, entry_id)
            return MessageActionResponse(
                success=new_entry_id is not None,
                message="Message queued for retry" if new_entry_id else "Failed to retry",
                entry_id=entry_id,
                new_entry_id=new_entry_id,
            )

        elif action == "acknowledge":
            # Need consumer group
            groups = await service.redis.xinfo_groups(stream)
            if not groups:
                raise HTTPException(status_code=400, detail="No consumer groups on stream")
            group_name = groups[0]["name"].decode() if isinstance(groups[0]["name"], bytes) else groups[0]["name"]
            success = await service.acknowledge_message(stream, group_name, entry_id)
            return MessageActionResponse(
                success=success,
                message="Message acknowledged" if success else "Failed to acknowledge",
                entry_id=entry_id,
            )

        else:
            raise HTTPException(status_code=400, detail=f"Unknown action: {action}")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Message action failed: {e}")
        return MessageActionResponse(
            success=False,
            message=str(e),
            entry_id=entry_id,
        )


# ============================================
# Web UI Routes
# ============================================

@router.get("/", response_class=HTMLResponse)
async def redis_bus_dashboard(request: Request):
    """Main Redis Bus observability dashboard."""
    from aegis.web.app import templates

    bus = getattr(request.app.state, "bus", None)
    redis_connected = False
    if bus:
        try:
            redis_connected = await bus.ping()
        except Exception:
            pass

    return templates.TemplateResponse(
        request,
        "redis_bus.html",
        {
            "redis_connected": redis_connected,
            "page_title": "Redis Bus Observability",
        },
    )


@router.get("/partials/stream-list", response_class=HTMLResponse)
async def stream_list_partial(
    request: Request,
    service: RedisBusService = Depends(get_redis_bus_service),
):
    """HTMX partial for stream list."""
    from aegis.web.app import templates

    summaries = await service.get_all_stream_summaries()
    return templates.TemplateResponse(
        request,
        "partials/stream_list.html",
        {"streams": summaries},
    )


@router.get("/partials/overview-stats", response_class=HTMLResponse)
async def overview_stats_partial(
    request: Request,
    service: RedisBusService = Depends(get_redis_bus_service),
):
    """HTMX partial for overview stats."""
    from aegis.web.app import templates

    stats = await service.get_overview_stats()
    return templates.TemplateResponse(
        request,
        "partials/overview_stats.html",
        {"stats": stats},
    )


@router.get("/partials/stream-detail/{stream_name}", response_class=HTMLResponse)
async def stream_detail_partial(
    stream_name: str,
    request: Request,
    service: RedisBusService = Depends(get_redis_bus_service),
    page: int = Query(1, ge=1),
):
    """HTMX partial for stream detail with messages."""
    from aegis.web.app import templates

    summary = await service.get_stream_summary(stream_name)
    messages = await service.get_messages(stream_name, count=50)

    return templates.TemplateResponse(
        request,
        "partials/stream_detail.html",
        {"stream": summary, "messages": messages, "page": page},
    )


@router.get("/partials/message-detail/{stream_name}/{entry_id}", response_class=HTMLResponse)
async def message_detail_partial(
    stream_name: str,
    entry_id: str,
    request: Request,
    service: RedisBusService = Depends(get_redis_bus_service),
):
    """HTMX partial for message detail modal."""
    from aegis.web.app import templates

    detail = await service.get_message_detail(stream_name, entry_id)
    if not detail:
        return templates.TemplateResponse(
            request,
            "partials/error.html",
            {"error": "Message not found", "status_code": 404},
            status_code=404,
        )

    return templates.TemplateResponse(
        request,
        "partials/message_detail.html",
        {"message": detail},
    )


@router.get("/partials/pipeline", response_class=HTMLResponse)
async def pipeline_partial(
    request: Request,
    service: RedisBusService = Depends(get_redis_bus_service),
):
    """HTMX partial for pipeline view."""
    from aegis.web.app import templates

    state = await service.get_pipeline_state()
    return templates.TemplateResponse(
        request,
        "partials/pipeline_view.html",
        {"pipeline": state},
    )


@router.get("/partials/token-chart/{stream_name}", response_class=HTMLResponse)
async def token_chart_partial(
    stream_name: str,
    request: Request,
    service: RedisBusService = Depends(get_redis_bus_service),
    limit: int = Query(50),
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
):
    """HTMX partial for token chart."""
    from aegis.web.app import templates
    from aegis.web.core.charting import create_bar_chart, create_chart_response

    data = await service.get_token_chart_data(stream_name, limit, 
        datetime.fromisoformat(start.replace("Z", "+00:00")) if start else None,
        datetime.fromisoformat(end.replace("Z", "+00:00")) if end else None,
    )

    # Create chart
    timestamps = [d["timestamp"] for d in data["data_points"]]
    total_tokens = [d["total_tokens"] for d in data["data_points"]]
    prompt_tokens = [d["prompt_tokens"] for d in data["data_points"]]
    completion_tokens = [d["completion_tokens"] for d in data["data_points"]]

    fig = create_time_series_chart(
        x=timestamps,
        y_series={
            "Total Tokens": total_tokens,
            "Prompt Tokens": prompt_tokens,
            "Completion Tokens": completion_tokens,
        },
        title=f"Token Usage - {stream_name}",
        x_title="Time",
        y_title="Tokens",
        chart_type="bar",
        stack=True,
    )

    chart_response = create_chart_response(fig, title=f"Token Usage - {stream_name}")

    return templates.TemplateResponse(
        request,
        "partials/token_chart.html",
        {"chart": chart_response, "stream": stream_name, "data": data},
    )


@router.get("/partials/cumulative-chart", response_class=HTMLResponse)
async def cumulative_chart_partial(
    request: Request,
    service: RedisBusService = Depends(get_redis_bus_service),
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    granularity: str = Query("hour"),
    agents: Optional[str] = Query(None),
    types: Optional[str] = Query(None),
    streams: Optional[str] = Query(None),
):
    """HTMX partial for cumulative chart with filters."""
    from aegis.web.app import templates
    from aegis.web.core.charting import create_time_series_chart, create_chart_response, create_dual_axis_chart

    end_dt = datetime.fromisoformat(end.replace("Z", "+00:00")) if end else datetime.now(timezone.utc)
    start_dt = datetime.fromisoformat(start.replace("Z", "+00:00")) if start else end_dt - timedelta(hours=24)

    agent_list = agents.split(",") if agents else None
    type_list = types.split(",") if types else None
    stream_list = streams.split(",") if streams else None

    data = await service.get_cumulative_chart_data(start_dt, end_dt, granularity, agent_list, type_list, stream_list)

    if not data["data_points"]:
        fig = create_time_series_chart(
            x=[start_dt, end_dt],
            y_series={"Tokens": [0, 0], "Requests": [0, 0]},
            title="No data in selected range",
        )
    else:
        timestamps = [d["timestamp"] for d in data["data_points"]]
        cum_tokens = [d["cumulative_tokens"] for d in data["data_points"]]
        cum_requests = [d["cumulative_requests"] for d in data["data_points"]]

        fig = create_dual_axis_chart(
            x=timestamps,
            left_y={"Cumulative Tokens": cum_tokens},
            right_y={"Cumulative Requests": cum_requests},
            title=f"Cumulative Tokens & Requests ({granularity} buckets)",
            left_title="Tokens",
            right_title="Requests",
        )

    chart_response = create_chart_response(fig, title="Cumulative Usage")

    return templates.TemplateResponse(
        request,
        "partials/cumulative_chart.html",
        {
            "chart": chart_response,
            "data": data,
            "filters": {
                "start": start_dt.isoformat(),
                "end": end_dt.isoformat(),
                "granularity": granularity,
                "agents": agents,
                "types": types,
                "streams": streams,
            },
        },
    )


# Need to import time for rate chart
import time


# ============================================
# Historical Data Endpoints
# ============================================

@router.get("/history/streams/{stream_name}")
async def get_stream_history(
    stream_name: str,
    request: Request,
    storage: ObservabilityStorage = Depends(get_observability_storage_dep),
    hours: int = Query(24, ge=1, le=168),
    limit: int = Query(1000, ge=1, le=5000),
):
    """Get historical stream metrics."""
    history = await storage.get_stream_history(stream_name, hours, limit)
    return {"stream": stream_name, "history": history}


@router.get("/history/messages")
async def get_archived_messages(
    request: Request,
    storage: ObservabilityStorage = Depends(get_observability_storage_dep),
    stream_name: Optional[str] = Query(None),
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    message_type: Optional[str] = Query(None),
    source_agent: Optional[str] = Query(None),
    target_agent: Optional[str] = Query(None),
    correlation_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """Query archived messages with filters."""
    start_dt = datetime.fromisoformat(start.replace("Z", "+00:00")) if start else None
    end_dt = datetime.fromisoformat(end.replace("Z", "+00:00")) if end else None

    messages = await storage.get_archived_messages(
        stream_name=stream_name,
        start=start_dt,
        end=end_dt,
        message_type=message_type,
        source_agent=source_agent,
        target_agent=target_agent,
        correlation_id=correlation_id,
        status=status,
        limit=limit,
        offset=offset,
    )
    return {"messages": messages, "limit": limit, "offset": offset}


@router.get("/history/messages/correlation/{correlation_id}")
async def get_correlation_chain(
    correlation_id: str,
    request: Request,
    storage: ObservabilityStorage = Depends(get_observability_storage_dep),
):
    """Get all messages in a correlation chain."""
    messages = await storage.get_message_by_correlation(correlation_id)
    return {"correlation_id": correlation_id, "messages": messages}


@router.get("/history/pipeline")
async def get_pipeline_history(
    request: Request,
    storage: ObservabilityStorage = Depends(get_observability_storage_dep),
    hours: int = Query(24, ge=1, le=168),
):
    """Get historical pipeline state."""
    history = await storage.get_pipeline_history(hours)
    return {"history": history}


@router.get("/history/tokens")
async def get_token_aggregates(
    request: Request,
    storage: ObservabilityStorage = Depends(get_observability_storage_dep),
    stream_name: Optional[str] = Query(None),
    granularity: str = Query("hour", pattern="^(minute|hour|day)$"),
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    limit: int = Query(1000, ge=1, le=5000),
):
    """Get historical token aggregates."""
    start_dt = datetime.fromisoformat(start.replace("Z", "+00:00")) if start else None
    end_dt = datetime.fromisoformat(end.replace("Z", "+00:00")) if end else None

    aggregates = await storage.get_token_aggregates(
        stream_name=stream_name,
        granularity=granularity,
        start=start_dt,
        end=end_dt,
        limit=limit,
    )
    return {"aggregates": aggregates}


@router.get("/history/actions")
async def get_message_actions(
    request: Request,
    storage: ObservabilityStorage = Depends(get_observability_storage_dep),
    stream_name: Optional[str] = Query(None),
    message_id: Optional[str] = Query(None),
    hours: int = Query(24, ge=1, le=168),
    limit: int = Query(100, ge=1, le=1000),
):
    """Get message action audit log."""
    actions = await storage.get_message_actions(
        stream_name=stream_name,
        message_id=message_id,
        hours=hours,
        limit=limit,
    )
    return {"actions": actions}


# ============================================
# Archiver Control Endpoints
# ============================================

@router.post("/archiver/start")
async def start_archiver_endpoint(
    request: Request,
    service: RedisBusService = Depends(get_redis_bus_service),
    interval: int = Query(60, ge=10, le=3600),
):
    """Start the background archiver."""
    await start_archiver(service, interval)
    return {"status": "started", "interval_seconds": interval}


@router.post("/archiver/stop")
async def stop_archiver_endpoint():
    """Stop the background archiver."""
    await stop_archiver()
    return {"status": "stopped"}


@router.get("/archiver/status")
async def archiver_status():
    """Get archiver status."""
    from aegis.web.routes.redis_bus.storage import _archiver
    if _archiver:
        return {"running": _archiver._running, "interval_seconds": _archiver.interval_seconds}
    return {"running": False}


@router.post("/maintenance/cleanup")
async def cleanup_old_data(
    request: Request,
    storage: ObservabilityStorage = Depends(get_observability_storage_dep),
    retention_days: int = Query(30, ge=1, le=365),
):
    """Clean up old archived data."""
    await storage.cleanup_old_data(retention_days)
    return {"status": "cleaned", "retention_days": retention_days}