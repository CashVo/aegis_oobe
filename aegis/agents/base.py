# File: aegis/agents/base.py
# Purpose: Defines the Abstract Base Class for all Aegis agents.

from abc import ABC, abstractmethod

from aegis.schemas import AgentID, AegisMessage

class BaseAgent(ABC):
    """
    Abstract base class for all Aegis agents, enforcing a common contract.
    Conforms to Genesis Spec Part II, Section 2.3, with a concrete __init__.
    """

    def __init__(self, agent_id: AgentID, subscriptions: list[str] | None = None):
        """
        Initializes the agent.

        Args:
            agent_id: The canonical ID of the agent.
            subscriptions: A list of message actions or channels this agent listens to.
        """
        self.agent_id: AgentID = agent_id
        self.subscriptions: list[str] = subscriptions or []

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
