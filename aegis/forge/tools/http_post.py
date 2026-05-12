# aegis/forge/tools/http_post.py
# Implements: Part VIII, §8.1 — http_post tool
"""
Tool: http_post
Perform an HTTP POST request.
"""

import asyncio
import json

import aiohttp

from aegis.forge.tools.base import ToolManifest, ToolResult


manifest = ToolManifest(
    name="http_post",
    description="Perform an HTTP POST request.",
    version="1.0.0",
    parameters_schema={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "The URL to POST to."},
            "body": {"type": "object", "default": {}, "description": "JSON body payload."},
            "headers": {"type": "object", "default": {}, "description": "Optional HTTP headers."},
            "timeout": {"type": "integer", "default": 30, "description": "Request timeout in seconds."},
            "content_type": {"type": "string", "default": "application/json", "description": "Content-Type header."},
        },
        "required": ["url"],
    },
    permissions_required=["network.http"],
    timeout_seconds=60,
)


async def execute(params: dict) -> ToolResult:
    """
    Perform an HTTP POST request.

    Args:
        params: {"url": str, "body": dict, "headers": dict, "timeout": int, "content_type": str}

    Returns:
        ToolResult with response status and body.
    """
    url = params.get("url")
    body = params.get("body", {})
    headers = params.get("headers", {})
    timeout = params.get("timeout", 30)
    content_type = params.get("content_type", "application/json")

    if not url:
        return ToolResult(success=False, error="Parameter 'url' is required.")

    if not url.startswith(("http://", "https://")):
        return ToolResult(success=False, error="URL must start with http:// or https://")

    headers.setdefault("Content-Type", content_type)

    try:
        client_timeout = aiohttp.ClientTimeout(total=timeout)
        async with aiohttp.ClientSession(timeout=client_timeout) as session:
            if content_type == "application/json":
                async with session.post(url, json=body, headers=headers) as response:
                    response_body = await response.text(encoding="utf-8", errors="replace")
                    return ToolResult(
                        success=(200 <= response.status < 400),
                        data={
                            "status_code": response.status,
                            "headers": dict(response.headers),
                            "body": response_body,
                            "url": str(response.url),
                        },
                        error=f"HTTP {response.status}" if response.status >= 400 else None,
                    )
            else:
                async with session.post(url, data=json.dumps(body), headers=headers) as response:
                    response_body = await response.text(encoding="utf-8", errors="replace")
                    return ToolResult(
                        success=(200 <= response.status < 400),
                        data={
                            "status_code": response.status,
                            "headers": dict(response.headers),
                            "body": response_body,
                            "url": str(response.url),
                        },
                        error=f"HTTP {response.status}" if response.status >= 400 else None,
                    )
    except aiohttp.ClientError as e:
        return ToolResult(success=False, error=f"HTTP POST failed: {str(e)}")
    except asyncio.TimeoutError:
        return ToolResult(success=False, error=f"HTTP POST timed out after {timeout}s: {url}")
    except Exception as e:
        return ToolResult(success=False, error=f"HTTP POST failed: {str(e)}")
