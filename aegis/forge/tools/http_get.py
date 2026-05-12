# aegis/forge/tools/http_get.py
# Implements: Part VIII, §8.1 — http_get tool
"""
Tool: http_get
Perform an HTTP GET request and return the response.
"""

import aiohttp

from aegis.forge.tools.base import ToolManifest, ToolResult


manifest = ToolManifest(
    name="http_get",
    description="Perform an HTTP GET request and return the response.",
    version="1.0.0",
    parameters_schema={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "The URL to request."},
            "headers": {"type": "object", "default": {}, "description": "Optional HTTP headers."},
            "timeout": {"type": "integer", "default": 30, "description": "Request timeout in seconds."},
            "max_content_length": {"type": "integer", "default": 1048576, "description": "Max response size in bytes (default 1MB)."},
        },
        "required": ["url"],
    },
    permissions_required=["network.http"],
    timeout_seconds=60,
)


async def execute(params: dict) -> ToolResult:
    """
    Perform an HTTP GET request.

    Args:
        params: {"url": str, "headers": dict, "timeout": int, "max_content_length": int}

    Returns:
        ToolResult with response status, headers, and body.
    """
    url = params.get("url")
    headers = params.get("headers", {})
    timeout = params.get("timeout", 30)
    max_content_length = params.get("max_content_length", 1048576)

    if not url:
        return ToolResult(success=False, error="Parameter 'url' is required.")

    if not url.startswith(("http://", "https://")):
        return ToolResult(success=False, error="URL must start with http:// or https://")

    try:
        client_timeout = aiohttp.ClientTimeout(total=timeout)
        async with aiohttp.ClientSession(timeout=client_timeout) as session:
            async with session.get(url, headers=headers) as response:
                # Check content length before reading
                content_length = response.content_length
                if content_length and content_length > max_content_length:
                    return ToolResult(
                        success=False,
                        error=f"Response too large: {content_length} bytes (max: {max_content_length}).",
                    )

                body = await response.text(encoding="utf-8", errors="replace")
                if len(body) > max_content_length:
                    body = body[:max_content_length] + "\n... [TRUNCATED]"

                return ToolResult(
                    success=(200 <= response.status < 400),
                    data={
                        "status_code": response.status,
                        "headers": dict(response.headers),
                        "body": body,
                        "url": str(response.url),
                        "content_type": response.content_type,
                    },
                    error=f"HTTP {response.status}" if response.status >= 400 else None,
                )
    except aiohttp.ClientError as e:
        return ToolResult(success=False, error=f"HTTP request failed: {str(e)}")
    except asyncio.TimeoutError:
        return ToolResult(success=False, error=f"HTTP GET timed out after {timeout}s: {url}")
    except Exception as e:
        return ToolResult(success=False, error=f"HTTP GET failed: {str(e)}")
