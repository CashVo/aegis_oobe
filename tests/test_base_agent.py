# File: tests/test_base_agent.py
# Purpose: Tests BaseAgent ABC contract enforcement.

import pytest
from aegis.agents import BaseAgent
from aegis.schemas import AgentID, AegisMessage

# Define a minimal concrete implementation for testing
class ConcreteAgent(BaseAgent):
    async def handle_message(self, message: AegisMessage) -> AegisMessage | None:
        return None
    async def startup(self) -> None:
        pass
    async def shutdown(self) -> None:
        pass

def test_concrete_agent_instantiation():
    """Verify a correct concrete class can be instantiated."""
    agent = ConcreteAgent(agent_id=AgentID.FORGE, subscriptions=["test.action"])
    assert agent.agent_id == AgentID.FORGE
    assert agent.subscriptions == ["test.action"]

def test_missing_handle_message_raises_type_error():
    """Test that failing to implement handle_message raises TypeError."""
    with pytest.raises(TypeError, match="Can't instantiate abstract class"):
        class IncompleteAgent(BaseAgent):
            # Missing handle_message
            async def startup(self) -> None: pass
            async def shutdown(self) -> None: pass

        IncompleteAgent(agent_id=AgentID.FORGE)

def test_missing_startup_raises_type_error():
    """Test that failing to implement startup raises TypeError."""
    with pytest.raises(TypeError, match="Can't instantiate abstract class"):
        class IncompleteAgent(BaseAgent):
            async def handle_message(self, message: AegisMessage) -> None: pass
            # Missing startup
            async def shutdown(self) -> None: pass

        IncompleteAgent(agent_id=AgentID.FORGE)

def test_missing_shutdown_raises_type_error():
    """Test that failing to implement shutdown raises TypeError."""
    with pytest.raises(TypeError, match="Can't instantiate abstract class"):
        class IncompleteAgent(BaseAgent):
            async def handle_message(self, message: AegisMessage) -> None: pass
            async def startup(self) -> None: pass
            # Missing shutdown

        IncompleteAgent(agent_id=AgentID.FORGE)
