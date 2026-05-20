# aegis/web/routes/memory.py
# Implements: Part X, §10.2 — Memory Explorer (/memory)
"""
Memory Explorer: browse and search Lexicon memory tiers.
"""

import asyncio
import logging
import uuid

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse
from aegis.web.app import templates
from aegis.schemas.message import AegisMessage, MessageType

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/memory", include_in_schema=False)
async def memory_page(request: Request):
    """Render the Memory Explorer page."""
    return templates.TemplateResponse(request, "memory.html", {
        "fragments": [],
        "query": "",
    })


@router.post("/memory/search", include_in_schema=False)
async def memory_search(
    request: Request,
    query: str = Form(""),
    tiers: str = Form("L1,L2,L3"),
    tenant_id: str = Form("default"),
    user_id: str = Form("root"),
):
    """Handle memory search form submission (HTMX partial)."""
    bus = request.app.state.bus
    fragments = []

    if bus and query.strip():
        correlation_id = str(uuid.uuid4())
        response_channel = f"aegis:stream:web:lexicon:{correlation_id}"
        consumer_group = f"web-lex-{correlation_id}"
        try:
            await bus.create_consumer_group(response_channel, consumer_group)
        except Exception:
            pass

        tier_list = [t.strip() for t in tiers.split(",")]
        msg = AegisMessage(
            correlation_id=correlation_id,
            source_agent="web",
            target_agent="lexicon",
            message_type=MessageType.REQUEST,
            tenant_id=tenant_id,
            user_id=user_id,
            action="lexicon.search_memory",
            payload={
                "query": query,
                "tiers": tier_list,
                "limit": 20,
                "tenant_id": tenant_id,
                "user_id": user_id,
            },
            metadata={"response_channel": response_channel},
        )
        await bus.publish("aegis:stream:lexicon", msg)

        deadline = asyncio.get_event_loop().time() + 10
        while asyncio.get_event_loop().time() < deadline:
            messages = await bus.consume(
                response_channel, consumer_group, "web",
                count=1, block_ms=500,
            )
            if messages:
                for _, data in messages:
                    parsed = AegisMessage.model_validate(data)
                    fragments = parsed.payload.get("data", {}).get("fragments", [])
                break

    return templates.TemplateResponse(request, "memory.html", {
        "fragments": fragments,
        "query": query,
    })
