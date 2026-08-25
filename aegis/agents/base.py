# File: aegis/agents/base.py
# Purpose: Defines the Abstract Base Class for all Aegis agents.

from abc import ABC, abstractmethod
import asyncio
import time
from datetime import datetime, timezone
from typing import Optional

from aegis.schemas import AgentID, AegisMessage
from aegis.schemas.observer import HeartbeatEvent, AgentHealth
from aegis.schemas.message import MessageType


class BaseAgent(ABC):
    """
    Abstract base class for all Aegis agents, enforcing a common contract.
    Conforms to Genesis Spec Part II, Section 2.3, with a concrete __init__.
    """

    def __init__(
        self, 
        agent_id: AgentID, 
        subscriptions: list[str] | None = None,
        heartbeat_interval: float = 10.0,
    ):
        """
        Initializes the agent.

        Args:
            agent_id: The canonical ID of the agent.
            subscriptions: A list of message actions or channels this agent listens to.
            heartbeat_interval: Seconds between heartbeat messages (default: 10s).
        """
        self.agent_id: AgentID = agent_id
        self.subscriptions: list[str] = subscriptions or []
        self._heartbeat_interval = heartbeat_interval
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._start_time = time.time()
        self._bus_publisher = None
        self._bus_subscriber = None
        self._redis_conn = None

    def set_bus(self, bus_publisher, bus_subscriber=None, redis_conn=None):
        """Set the message bus publisher/subscriber for this agent."""
        self._bus_publisher = bus_publisher
        self._bus_subscriber = bus_subscriber
        self._redis_conn = redis_conn

    async def _heartbeat_loop(self) -> None:
        """Background task that publishes heartbeat events at regular intervals."""
        while True:
            try:
                await asyncio.sleep(self._heartbeat_interval)
                await self._send_heartbeat()
            except asyncio.CancelledError:
                break
            except Exception as e:
                # Log but don't crash the heartbeat loop
                import logging
                logging.getLogger(__name__).warning(f"Heartbeat error for {self.agent_id}: {e}")

    async def _send_heartbeat(self) -> None:
        """Publish a heartbeat event to the observer stream."""
        if self._bus_publisher is None:
            return
        
        uptime = time.time() - self._start_time
        event = HeartbeatEvent(
            agent_id=self.agent_id,
            status=AgentHealth.HEALTHY,
            uptime_seconds=uptime,
            timestamp=datetime.now(timezone.utc),
        )
        
        message = AegisMessage(
            message_id=f"heartbeat-{int(time.time()*1000)}",
            source_agent=self.agent_id,
            target_agent="observer",
            message_type=MessageType.EVENT,
            action="observer.heartbeat",
            tenant_id=getattr(self, 'tenant_id', 'default'),
            user_id=getattr(self, 'user_id', 'root'),
            payload=event.model_dump(mode="json"),
        )
        
        await self._bus_publisher.publish(message)

    async def start_heartbeat(self) -> None:
        """Start the heartbeat background task."""
        if self._heartbeat_task is None or self._heartbeat_task.done():
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop(), name=f"heartbeat-{self.agent_id}")

    async def stop_heartbeat(self) -> None:
        """Stop the heartbeat background task."""
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass

    @abstractmethod
    async def handle_message(self, message: AegisMessage) -> AegisMessage | None:
        """
        Process an incoming message and optionally return a response message.

        This is the primary message handling logic for any agent.

        Args:
            message: The incoming AegisMessage to process.

        Returns:
            An optional AegisMessage to be sent as a response, or None.
        """
        ...

    @abstractmethod
    async def startup(self) -> None:
        """
        Agent initialization logic.

        Called once when the system starts. Use for loading configuration,
        connecting to resources, or subscribing to message bus channels.
        """
        ...

    @abstractmethod
    async def shutdown(self) -> None:
        """
        Graceful teardown logic.

        Called once when the system is shutting down. Use for releasing
        resources or performing cleanup tasks.
        """
        ...
