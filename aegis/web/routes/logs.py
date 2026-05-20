# aegis/web/routes/logs.py
# Implements: Part X, §10.2 — Log Viewer (/logs)
"""
Streaming log viewer via WebSocket. Subscribes to Observer broadcast.
"""

import asyncio
import json
import logging

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from aegis.web.app import templates

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/logs", include_in_schema=False)
async def logs_page(request: Request):
    """Render the log viewer page."""
    return templates.TemplateResponse(request, "logs.html")


@router.websocket("/ws/logs")
async def logs_websocket(websocket: WebSocket):
    """
    Stream system logs to the client via WebSocket.
    Subscribes to the aegis:stream:broadcast channel for log events.
    """
    await websocket.accept()
    bus = websocket.app.state.bus

    if not bus:
        await websocket.send_json({"type": "error", "message": "Bus unavailable"})
        await websocket.close()
        return

    consumer_group = f"web-logs-{id(websocket)}"
    try:
        await bus.create_consumer_group("aegis:stream:observer", consumer_group)
    except Exception:
        pass

    try:
        while True:
            messages = await bus.consume(
                "aegis:stream:observer",
                consumer_group,
                f"web-{id(websocket)}",
                count=10,
                block_ms=2000,
            )
            if messages:
                for _, msg_data in messages:
                    try:
                        from aegis.schemas.message import AegisMessage
                        parsed = AegisMessage.model_validate(msg_data)
                        log_entry = {
                            "type": "log",
                            "timestamp": parsed.timestamp.isoformat(),
                            "source": parsed.source_agent,
                            "action": parsed.action,
                            "level": parsed.payload.get("level", "info"),
                            "message": parsed.payload.get("message", str(parsed.payload)),
                        }
                    except Exception:
                        log_entry = {"type": "log", "message": str(msg_data)}
                    await websocket.send_json(log_entry)
            else:
                # Send heartbeat to keep connection alive
                await websocket.send_json({"type": "heartbeat"})

    except WebSocketDisconnect:
        logger.debug("Logs WebSocket disconnected.")
    except Exception as exc:
        logger.error(f"Logs WebSocket error: {exc}")
    finally:
        try:
            await websocket.close()
        except Exception:
            pass
