# aegis/web/routes/users.py
# Implements: Part X, §10.2 — User Management (/users)
"""
User Management CRUD interface.
"""

import asyncio
import logging
import uuid

from fastapi import APIRouter, Request, Form
from aegis.web.app import templates
from aegis.schemas.message import AegisMessage, MessageType

logger = logging.getLogger(__name__)
router = APIRouter()


async def _identity_bus_call(bus, action: str, payload: dict) -> dict:
    """Send identity request via bus and return response payload."""
    if not bus:
        return {"success": False, "error": "Bus unavailable"}

    correlation_id = str(uuid.uuid4())
    response_channel = f"aegis:stream:web:identity:{correlation_id}"
    consumer_group = f"web-id-{correlation_id}"
    try:
        await bus.create_consumer_group(response_channel, consumer_group)
    except Exception:
        pass

    msg = AegisMessage(
        correlation_id=correlation_id,
        source_agent="web",
        target_agent="identity",
        message_type=MessageType.REQUEST,
        tenant_id=payload.get("tenant_id", "default"),
        user_id="root",
        action=f"identity.{action}",
        payload=payload,
        metadata={"response_channel": response_channel},
    )
    await bus.publish("aegis:stream:identity", msg)

    deadline = asyncio.get_event_loop().time() + 10
    result = {"success": False, "error": "timeout"}
    while asyncio.get_event_loop().time() < deadline:
        messages = await bus.consume(
            response_channel, consumer_group, "web",
            count=1, block_ms=500,
        )
        if messages:
            for _, data in messages:
                parsed = AegisMessage.model_validate(data)
                result = parsed.payload
            break
    return result


@router.get("/users", include_in_schema=False)
async def users_page(request: Request, tenant_id: str = "default"):
    """Render the user management page."""
    bus = request.app.state.bus
    result = await _identity_bus_call(bus, "list_users", {"tenant_id": tenant_id})
    users = result.get("data", {}).get("users", [])
    return templates.TemplateResponse(request, "users.html", {
        "users": users,
        "tenant_id": tenant_id,
        "message": None,
    })


@router.post("/users/create", include_in_schema=False)
async def create_user(
    request: Request,
    username: str = Form(...),
    display_name: str = Form(""),
    email: str = Form(""),
    role_name: str = Form("member"),
    tenant_id: str = Form("default"),
):
    """Handle user creation form."""
    bus = request.app.state.bus
    result = await _identity_bus_call(bus, "create_user", {
        "tenant_id": tenant_id,
        "username": username,
        "display_name": display_name,
        "email": email or None,
        "role_name": role_name,
    })
    message = f"User '{username}' created." if result.get("success") else result.get("error", "Failed")

    # Re-fetch user list
    list_result = await _identity_bus_call(bus, "list_users", {"tenant_id": tenant_id})
    users = list_result.get("data", {}).get("users", [])

    return templates.TemplateResponse(request, "users.html", {
        "users": users,
        "tenant_id": tenant_id,
        "message": message,
    })


@router.post("/users/delete/{user_id}", include_in_schema=False)
async def delete_user(request: Request, user_id: str, tenant_id: str = "default"):
    """Handle user deletion."""
    bus = request.app.state.bus
    result = await _identity_bus_call(bus, "delete_user", {
        "tenant_id": tenant_id,
        "user_id": user_id,
    })
    message = f"User {user_id} deleted." if result.get("success") else result.get("error", "Failed")

    list_result = await _identity_bus_call(bus, "list_users", {"tenant_id": tenant_id})
    users = list_result.get("data", {}).get("users", [])

    return templates.TemplateResponse(request, "users.html", {
        "users": users,
        "tenant_id": tenant_id,
        "message": message,
    })
