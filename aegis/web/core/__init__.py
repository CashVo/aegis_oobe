# aegis/web/core/__init__.py
# Shared Mission Control core infrastructure

from aegis.web.core.base_router import BaseMissionControlRouter
from aegis.web.core.dependencies import get_bus, get_config, get_redis_client
from aegis.web.core.pagination import PaginationParams, PaginatedResponse
from aegis.web.core.filters import FilterParams, parse_filters
from aegis.web.core.charting import ChartData, serialize_plotly_figure

__all__ = [
    "BaseMissionControlRouter",
    "get_bus",
    "get_config",
    "get_redis_client",
    "PaginationParams",
    "PaginatedResponse",
    "FilterParams",
    "parse_filters",
    "ChartData",
    "serialize_plotly_figure",
]