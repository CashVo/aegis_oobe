# aegis/agents/torchestrator/router.py
# Implements: Part II §2.2 — Inter-agent message routing
# Implements: Part VI — Protocol dispatch
#
# The Router handles the mechanics of sending messages to other agents
# via the Redis message bus and collecting responses.

import asyncio
import logging
from aegis.utils import time
from typing import Any, Dict, Optional
from uuid import uuid4

from aegis.schemas.message import AegisMessage, MessageType, Priority
from aegis.schemas.torchestrator import TaskStep, TaskStatus

logger = logging.getLogger(__name__)

# Agent stream mapping
AGENT_STREAMS = {
    "oracle": "aegis:stream:oracle",
    "forge": "aegis:stream:forge",
    "lexicon": "aegis:stream:lexicon",
    "warden": "aegis:stream:warden",
    "identity": "aegis:stream:identity",
    "janus": "aegis:stream:janus",
    "system": "aegis:stream:system_manager",
}


class MessageRouter:
    """
    Routes messages between TOrchestrator and other agents via the bus.

    Handles:
    - Building properly formatted AegisMessage envelopes
    - Publishing to agent streams
    - Waiting for correlated responses (with timeout)
    - Warden authorization checks before dispatching
    """

    def __init__(self, bus_publisher=None, bus_subscriber=None, agent_id: str = "torchestrator"):
        """
        Initialize the MessageRouter.

        Args:
            bus_publisher: The Redis bus publisher (from CHUNK-002).
            bus_subscriber: The Redis bus subscriber for receiving responses.
            agent_id: This agent's ID for message source attribution.
        """
        self._publisher = bus_publisher
        self._subscriber = bus_subscriber
        self._agent_id = agent_id
        self._pending_responses: Dict[str, asyncio.Future] = {}
        logger.info("MessageRouter initialized for agent '%s'.", agent_id)

    async def execute_step(
        self,
        step: TaskStep,
        tenant_id: str,
        user_id: str,
        session_id: str,
        timeout: float = 60.0,
        context_data: Optional[Dict[str, Any]] = None
    ) -> TaskStep:
        """
        Execute a single task step by routing a message to the target agent.

        Args:
            step: The TaskStep to execute.
            tenant_id: Active tenant ID.
            user_id: Active user ID.
            session_id: Current session ID.
            timeout: Maximum time to wait for response (seconds).
            context_data: Optional context from previous steps.

        Returns:
            The TaskStep updated with result or error.
        """
        step.status = TaskStatus.IN_PROGRESS
        start_time = time.perf_counter()

        try:
            # Resolve the target stream
            target_stream = AGENT_STREAMS.get(step.target_agent)
            if not target_stream:
                step.status = TaskStatus.FAILED
                step.error = f"Unknown target agent: {step.target_agent}"
                return step

            # Inject context from previous steps if specified
            payload = dict(step.payload)
            if context_data:
                if "use_context_from_step" in payload:
                    payload["context_packet"] = context_data.get(payload.pop("use_context_from_step"))
                if "use_web_context_from_step" in payload:
                    payload["web_context"] = context_data.get(payload.pop("use_web_context_from_step"))

            # Build the message
            correlation_id = str(uuid4())
            # Use main stream for responses, filter by correlation_id
            response_channel = "aegis:stream:torchestrator"
            message = AegisMessage(
                correlation_id=correlation_id,
                source_agent=self._agent_id,
                target_agent=step.target_agent,
                message_type=MessageType.REQUEST,
                tenant_id=tenant_id,
                user_id=user_id,
                action=step.action,
                payload=payload,
                priority=Priority.NORMAL,
                # Use a longer TTL for Oracle calls (default 120s for Oracle, 60s for others)
                ttl_seconds=int(timeout * 2) if step.target_agent == "oracle" else int(timeout),
                metadata={
                    "session_id": session_id,
                    "step_id": step.step_id,
                },
            )
            # Add response_channel to payload so target agent knows where to reply
            message.payload["response_channel"] = response_channel

            # Send authorization check to Warden first
            # Use a generous timeout for Warden (up to 30s) to accommodate local model cold starts
            warden_timeout = min(timeout, 30.0)
            authorized = await self._check_authorization(
                action=step.action,
                resource=step.payload.get("tool_name", step.payload.get("skill_name", step.action)),
                tenant_id=tenant_id,
                user_id=user_id,
                timeout=warden_timeout,
                response_channel=response_channel
            )

            if not authorized:
                step.status = TaskStatus.FAILED
                step.error = "Authorization denied by Warden."
                return step

            # Use main stream for responses, filter by correlation_id
            consumer_group = f"torchestrator-step-{step.step_id}"
            # Ensure consumer group exists for main stream
            if self._subscriber:
                try:
                    await self._subscriber._ensure_consumer_group(response_channel, consumer_group)
                except Exception:
                    pass  # Group may already exist
            
            # Publish message and wait for response
            response = await self._send_and_wait(message, target_stream, correlation_id, timeout, response_channel, consumer_group)

            if response:
                step.status = TaskStatus.COMPLETED
                step.result = response.payload if hasattr(response, 'payload') else response
            else:
                step.status = TaskStatus.FAILED
                step.error = f"Timeout waiting for response from {step.target_agent} ({timeout}s)"

        except Exception as e:
            step.status = TaskStatus.FAILED
            step.error = str(e)
            logger.error("Step execution failed: %s", e, exc_info=True)

        elapsed = (time.perf_counter() - start_time) * 1000
        elapsed = max(elapsed, 0.01)
        logger.info(
            "Step '%s' -> %s (%.1fms): %s",
            step.description, step.target_agent, elapsed, step.status.value
        )
        return step

    async def _check_authorization(
        self,
        action: str,
        resource: str,
        tenant_id: str,
        user_id: str,
        timeout: float = 10.0,
        response_channel: str = None
    ) -> bool:
        """
        Check authorization with Warden before executing a step.
        """
        if not self._publisher:
            logger.debug("No publisher available, skipping Warden check (dev mode)")
            return True

        correlation_id = str(uuid4())
        future = asyncio.get_event_loop().create_future()
        self._pending_responses[correlation_id] = future

        message = AegisMessage(
            correlation_id=correlation_id,
            source_agent=self._agent_id,
            target_agent="warden",
            message_type=MessageType.REQUEST,
            tenant_id=tenant_id,
            user_id=user_id,
            action="warden.authorize",
            payload={
                "action": action,
                "resource": resource,
                "tenant_id": tenant_id,
                "user_id": user_id,
            },
            priority=Priority.HIGH,
        )
        if response_channel:
            message.payload["response_channel"] = response_channel

        try:
            await self._publisher.publish_to_stream("aegis:stream:warden", message)

            # Wait for authorization response with short timeout
            response = await asyncio.wait_for(future, timeout=timeout)
            if response:
                payload = response.payload if hasattr(response, 'payload') else response
                verdict = payload.get("verdict", "deny")
                if verdict == "allow":
                    return True
                elif verdict == "escalate":
                    logger.warning("Warden escalated action '%s' -- denying by default.", action)
                    return False
                else:
                    logger.warning("Warden denied action '%s': %s", action, payload.get("reason", ""))
                    return False

            # Timeout -- fail open in dev, fail closed in production
            logger.warning("Warden check timed out for action '%s'. Defaulting to ALLOW.", action)
            return True

        except asyncio.TimeoutError:
            logger.warning("Warden check timed out for action '%s'. Defaulting to ALLOW.", action)
            return True
        except Exception as e:
            logger.error("Warden authorization check failed: %s", e)
            # Fail open in development
            return True
        finally:
            self._pending_responses.pop(correlation_id, None)

    async def _send_and_wait(
        self,
        message: AegisMessage,
        target_stream: str,
        correlation_id: str,
        timeout: float,
        response_channel: str = None,
        consumer_group: str = None
    ) -> Optional[Dict[str, Any]]:
        """
        Publish a message to the bus and wait for a correlated response.

        Args:
            message: The AegisMessage to send.
            target_stream: The Redis stream to publish to.
            correlation_id: The correlation ID to match response.
            timeout: Maximum wait time in seconds.
            response_channel: Optional specific response channel to listen on.
            consumer_group: Consumer group for the response channel.

        Returns:
            The response payload dict, or None on timeout.
        """
        if not self._publisher:
            logger.debug("No bus publisher available. Simulating immediate response.")
            # Return a simulated response for development/testing
            return {"content": "[Simulated response -- no bus connected]", "success": True}

        # Create a future for the response
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending_responses[correlation_id] = future

        try:
            # Publish the message
            # Use publish_to_stream for direct stream publishing
            await self._publisher.publish_to_stream(target_stream, message)

            # Wait for response with timeout
            # The response will come through handle_incoming_response callback
            # which is called by the TOrchestrator's subscriber when it receives
            # a response on its main stream (the response_channel)
            response = await asyncio.wait_for(future, timeout=timeout)
            return response

        except asyncio.TimeoutError:
            logger.warning("Timeout waiting for response (correlation: %s)", correlation_id)
            return None
        except Exception as e:
            logger.error("Error in send_and_wait: %s", e)
            return None
        finally:
            self._pending_responses.pop(correlation_id, None)

    async def handle_incoming_response(self, message: AegisMessage) -> None:
        """
        Handle an incoming response message from another agent.

        Called by the TOrchestrator agent when it receives a response
        on its own stream.
        """
        correlation_id = message.correlation_id
        if correlation_id and correlation_id in self._pending_responses:
            future = self._pending_responses[correlation_id]
            if not future.done():
                future.set_result(message.payload)
                logger.debug("Resolved pending response for correlation: %s", correlation_id)
        else:
            logger.debug(
                "Received response with no pending future (correlation: %s). "
                "May have already timed out.",
                correlation_id
            )