# aegis/web/core/base_router.py
# Base router class for Mission Control modules

from typing import Any, Callable, Optional
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from aegis.web.core.dependencies import get_bus, get_config
from aegis.web.core.pagination import PaginationParams, PaginatedResponse
from aegis.web.core.filters import FilterParams
from aegis.web.core.charting import ChartData
from aegis.bus.redis_bus import RedisBus


class BaseMissionControlRouter(APIRouter):
    """
    Base router for Mission Control modules.

    Provides:
    - Standardized error handling
    - Common dependencies (bus, config)
    - HTMX-aware responses
    - OpenAPI documentation enhancements
    """

    def __init__(
        self,
        prefix: str = "",
        tags: Optional[list[str]] = None,
        module_name: str = "",
        **kwargs: Any,
    ):
        super().__init__(prefix=prefix, tags=tags or [], **kwargs)
        self.module_name = module_name or prefix.strip("/").replace("/", "_")

        # Add common exception handlers
        self._setup_exception_handlers()

    def _setup_exception_handlers(self) -> None:
        """Setup common exception handlers."""

        @self.exception_handler(HTTPException)
        async def http_exception_handler(request: Request, exc: HTTPException):
            # Return HTML for HTMX requests, JSON for API requests
            if request.headers.get("HX-Request"):
                from aegis.web.app import templates
                return templates.TemplateResponse(
                    request,
                    "partials/error.html",
                    {"error": exc.detail, "status_code": exc.status_code},
                    status_code=exc.status_code,
                )
            return {"error": exc.detail, "status_code": exc.status_code}

        @self.exception_handler(Exception)
        async def generic_exception_handler(request: Request, exc: Exception):
            import logging
            logger = logging.getLogger(__name__)
            logger.exception(f"Unhandled error in {self.module_name}: {exc}")

            if request.headers.get("HX-Request"):
                from aegis.web.app import templates
                return templates.TemplateResponse(
                    request,
                    "partials/error.html",
                    {"error": "Internal server error", "status_code": 500},
                    status_code=500,
                )
            return {"error": "Internal server error", "status_code": 500}

    # --- Common Dependencies ---

    async def bus(self, request: Request) -> RedisBus:
        """Get RedisBus - override in subclass if different dependency needed."""
        return await get_bus(request)

    async def config(self, request: Request) -> Any:
        """Get config - override in subclass if different dependency needed."""
        return await get_config(request)

    # --- HTMX Helpers ---

    def is_htmx(self, request: Request) -> bool:
        """Check if request is from HTMX."""
        return request.headers.get("HX-Request") == "true"

    def htmx_partial(self, request: Request, template: str, context: dict) -> HTMLResponse:
        """Render a partial template for HTMX requests."""
        from aegis.web.app import templates
        return templates.TemplateResponse(request, template, context)

    def htmx_full_or_partial(
        self,
        request: Request,
        full_template: str,
        partial_template: str,
        context: dict,
    ) -> HTMLResponse:
        """Render full page or partial based on HTMX header."""
        if self.is_htmx(request):
            return self.htmx_partial(request, partial_template, context)
        from aegis.web.app import templates
        return templates.TemplateResponse(request, full_template, context)


# --- Standard Response Models ---

class HealthResponse(BaseModel):
    """Standard health check response."""
    status: str = "healthy"
    module: str
    details: dict = {}


class ErrorResponse(BaseModel):
    """Standard error response (RFC 9457 Problem Details)."""
    type: str = "about:blank"
    title: str
    status: int
    detail: str
    instance: Optional[str] = None


class SuccessResponse(BaseModel):
    """Standard success response."""
    success: bool = True
    message: str
    data: Optional[dict] = None


# --- Decorators for Common Patterns ---

def mc_endpoint(
    path: str,
    methods: list[str] = ["GET"],
    response_model: Any = None,
    summary: str = "",
    description: str = "",
    **kwargs: Any,
):
    """
    Decorator for Mission Control endpoints with common enhancements.

    Adds:
    - Automatic OpenAPI documentation
    - HTMX partial/full rendering
    - Standard error responses
    """
    def decorator(func: Callable) -> Callable:
        # The actual route registration happens in the router subclass
        func._mc_endpoint = {
            "path": path,
            "methods": methods,
            "response_model": response_model,
            "summary": summary,
            "description": description,
            "kwargs": kwargs,
        }
        return func
    return decorator