# aegis/web/routes/chat.py
# Implements: Part X, §10.2 — Chat Page (/chat) + WebSocket
"""
Real-time chat with TOrchestrator via WebSocket.
Supports multi-turn sessions, session management.
"""

import asyncio
import json
import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect, Query
from aegis.web.app import templates
from aegis.schemas.message import AegisMessage, MessageType, Priority

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/chat", include_in_schema=False)
async def chat_page(request: Request, session_id: Optional[str] = None):
    """Render the chat page."""
    sid = session_id or str(uuid.uuid4())
    return templates.TemplateResponse(request, "chat.html", {
        "session_id": sid,
    })


@router.websocket("/ws/chat")
async def chat_websocket(
    websocket: WebSocket,
    session_id: str = Query(default=None),
    tenant_id: str = Query(default="default"),
    user_id: str = Query(default="root"),
):
    """
    WebSocket endpoint for real-time chat with TOrchestrator.

    Protocol:
        Client → Server: JSON with {"message": "...", "session_id": "..."}
        Server → Client: JSON with ChatOutput schema
    """
    await websocket.accept()
    sid = session_id or str(uuid.uuid4())
    bus = websocket.app.state.bus

    # Send session init confirmation
    await websocket.send_json({
        "type": "session_init",
        "session_id": sid,
        "status": "connected",
    })

    if not bus:
        await websocket.send_json({
            "type": "error",
            "message": "System bus unavailable. Start Aegis first.",
        })
        await websocket.close()
        return

    response_channel = f"aegis:stream:web:chat:{sid}"
    consumer_group = f"web-chat-{sid}"
    try:
        await bus.create_consumer_group(response_channel, consumer_group)
    except Exception:
        pass

    try:
        while True:
            # Receive user message
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                data = {"message": raw}

            user_message = data.get("message", "").strip()
            if not user_message:
                continue

            # Dispatch to TOrchestrator via bus
            msg = AegisMessage(
                source_agent="web",
                target_agent="torchestrator",
                message_type=MessageType.REQUEST,
                tenant_id=tenant_id,
                user_id=user_id,
                action="torchestrator.chat",
                payload={
                    "message": user_message,
                    "session_id": sid,
                    "response_channel": response_channel,
                },
                priority=Priority.NORMAL,
                metadata={"session_id": sid, "source": "web"},
            )
            await bus.publish("aegis:stream:torchestrator", msg)

            # Await response (with timeout)
            response_received = False
            deadline = asyncio.get_event_loop().time() + 60

            while asyncio.get_event_loop().time() < deadline:
                messages = await bus.consume(
                    response_channel, consumer_group, "web",
                    count=1, block_ms=1000,
                )
                if messages:
                    for _, msg_data in messages:
                        parsed = AegisMessage.model_validate(msg_data)
                        response_text = parsed.payload.get("response", "")
                        metadata = parsed.payload.get("metadata", {})
                        await websocket.send_json({
                            "type": "chat_response",
                            "response": response_text,
                            "session_id": sid,
                            "agent": "TOrchestrator",
                            "metadata": metadata,
                        })
                    response_received = True
                    break

            if not response_received:
                await websocket.send_json({
                    "type": "error",
                    "message": "Response timeout from TOrchestrator.",
                })

    except WebSocketDisconnect:
        logger.info(f"Chat WebSocket disconnected: session={sid}")
    except Exception as exc:
        logger.error(f"Chat WebSocket error: {exc}", exc_info=True)
        try:
            await websocket.send_json({"type": "error", "message": str(exc)})
        except Exception:
            pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass
