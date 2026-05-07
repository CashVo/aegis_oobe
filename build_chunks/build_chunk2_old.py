
# build_chunk_2.py
#
# This script assembles the Aegis Forge chunk (Chunk 2).
# Run it from the root of your project directory.
# It will create the necessary directories and write the frozen files.

import os
import textwrap

# --- File Manifest ---
# A dictionary mapping file paths to their content.
CHUNK_2_FILES = {
    "src/aegis/events/contracts.py": '''
    # src/aegis/events/contracts.py

    import uuid
    from datetime import datetime, timezone
    from typing import Any, Dict, Optional

    from pydantic import BaseModel, Field

    # Critical integration with Chunk 1's message bus serializer.
    from aegis.bus import register_model

    def get_utc_now() -> datetime:
        """Returns the current UTC datetime."""
        return datetime.now(timezone.utc)

    @register_model
    class SkillRequest(BaseModel):
        """
        An event published to request that a skill be executed.
        """
        skill_name: str = Field(
            ...,
            description="The name of the skill to be executed (e.g., 'rlm_code_generator')."
        )
        payload: Dict[str, Any] = Field(
            default_factory=dict,
            description="The input data or arguments for the skill."
        )
        correlation_id: uuid.UUID = Field(
            default_factory=uuid.uuid4,
            description="A unique ID to track the request and its corresponding response.",
            index=True
        )
        request_id: uuid.UUID = Field(
            default_factory=uuid.uuid4,
            description="The unique ID of this specific request event.",
            primary_key=True
        )
        requested_at: datetime = Field(
            default_factory=get_utc_now,
            description="The UTC timestamp when the request was created."
        )

    @register_model
    class SkillResponse(BaseModel):
        """
        An event published to deliver the result of a skill's execution.
        """
        correlation_id: uuid.UUID = Field(
            ...,
            description="The ID from the original SkillRequest to correlate them.",
            index=True
        )
        status: str = Field(
            "success",
            description="The final status of the execution ('success', 'failure')."
        )
        result: Dict[str, Any] = Field(
            default_factory=dict,
            description="The output data from the skill."
        )
        error_message: Optional[str] = Field(
            None,
            description="An error message if the status is 'failure'."
        )
        response_id: uuid.UUID = Field(
            default_factory=uuid.uuid4,
            description="The unique ID of this specific response event.",
            primary_key=True
        )
        responded_at: datetime = Field(
            default_factory=get_utc_now,
            description="The UTC timestamp when the response was created."
        )
    ''',
    "src/aegis/skills/base.py": '''
    # src/aegis/skills/base.py

    import asyncio
    import logging
    from typing import Awaitable, Callable, Dict, Any

    logger = logging.getLogger(__name__)

    # The registry will store skill functions keyed by their name.
    _skill_registry: Dict[str, Callable[..., Awaitable[Dict[str, Any]]]] = {}

    class SkillNotFoundError(Exception):
        """Raised when a requested skill is not found in the registry."""
        pass

    def register_skill(func: Callable[..., Awaitable[Dict[str, Any]]]) -> Callable[..., Awaitable[Dict[str, Any]]]:
        """
        A decorator to register a function as an executable skill.
        """
        skill_name = func.__name__
        if skill_name in _skill_registry:
            logger.warning(f"Skill '{skill_name}' is being re-registered. This may be unintentional.")
        _skill_registry[skill_name] = func
        logger.debug(f"Registered skill: '{skill_name}'")
        return func

    def get_skill(skill_name: str) -> Callable[..., Awaitable[Dict[str, Any]]]:
        """
        Retrieves a skill function from the registry.

        Args:
            skill_name: The name of the skill to retrieve.

        Returns:
            The awaitable skill function.

        Raises:
            SkillNotFoundError: If the skill is not found in the registry.
        """
        if skill_name not in _skill_registry:
            raise SkillNotFoundError(f"Skill '{skill_name}' is not registered.")
        return _skill_registry[skill_name]

    # --- Placeholder Skill for Testing ---

    @register_skill
    async def placeholder_skill(payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        A simple skill that simulates doing work and returns a result.
        """
        logger.info(f"Executing placeholder_skill with payload: {payload}")
        
        duration = payload.get("duration_seconds", 2)
        await asyncio.sleep(duration)
        
        output = {
            "message": "Placeholder skill executed successfully.",
            "input_payload": payload,
            "duration_slept": duration
        }
        
        logger.info("Placeholder_skill finished.")
        return output
    ''',
    "src/aegis/forge/runner.py": '''
    # src/aegis/forge/runner.py

    import asyncio
    import logging

    from aegis.bus import MessageBus
    from aegis.events.contracts import SkillRequest, SkillResponse
    from aegis.skills.base import SkillNotFoundError, get_skill

    logger = logging.getLogger(__name__)

    class ForgeRunner:
        """
        The core engine that listens for skill requests and runs them.
        """

        def __init__(self):
            self.bus = MessageBus()
            # A set to keep track of running skill tasks.
            self.active_tasks = set()

        async def run(self):
            """
            Starts the ForgeRunner's main loop, listening for and processing
            SkillRequest events indefinitely.
            """
            logger.info("ForgeRunner is starting up...")
            logger.info("Subscribing to SkillRequest events on the message bus.")
            
            async for request in self.bus.subscribe(SkillRequest):
                logger.info(f"Received SkillRequest for '{request.skill_name}' (Corr ID: {request.correlation_id})")
                
                # Spawn a new, non-blocking task to handle the request.
                task = asyncio.create_task(self._handle_skill_request(request))
                
                # Add the task to the active set to maintain a reference.
                self.active_tasks.add(task)
                
                # Add a callback to remove the task from the set when it's done.
                task.add_done_callback(self.active_tasks.discard)

        async def _handle_skill_request(self, request: SkillRequest):
            """
            Executes a single skill request, handling success or failure,
            and publishes the response.
            """
            response_data = {
                "correlation_id": request.correlation_id
            }
            
            try:
                # 1. Find the skill in the registry.
                skill_func = get_skill(request.skill_name)
                
                # 2. Execute the skill with its payload.
                logger.debug(f"Executing skill '{request.skill_name}'...")
                result = await skill_func(request.payload)
                logger.debug(f"Skill '{request.skill_name}' finished successfully.")
                
                # 3. Populate success response.
                response_data["status"] = "success"
                response_data["result"] = result

            except (SkillNotFoundError, Exception) as e:
                logger.error(
                    f"Skill '{request.skill_name}' failed for Corr ID "
                    f"{request.correlation_id}. Error: {e}",
                    exc_info=True
                )
                # 4. Populate failure response.
                response_data["status"] = "failure"
                response_data["error_message"] = str(e)
            
            # 5. Create and publish the final response.
            response = SkillResponse(**response_data)
            await self.bus.publish(response)
            logger.info(f"Published SkillResponse for '{request.skill_name}' (Corr ID: {request.correlation_id})")
    ''',
    "src/aegis/forge/main.py": '''
    # src/aegis/forge/main.py

    import asyncio
    import logging
    import signal
    import sys

    # Integration with Chunk 1 for Redis readiness
    from aegis.bus import wait_for_redis

    # Integration with the frozen runner.py
    from aegis.forge.runner import ForgeRunner

    # --- Basic Logging Setup ---
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    logger = logging.getLogger(__name__)

    async def shutdown(sig: signal.Signals, main_task: asyncio.Task):
        """
        Handles graceful shutdown of the service.
        """
        logger.warning(f"Received exit signal {sig.name}... Initiating graceful shutdown.")

        # 1. Cancel the main runner task. This will stop the bus.subscribe() loop.
        main_task.cancel()
        
        # Allow a moment for the cancellation to propagate
        await asyncio.sleep(1)
        logger.info("Shutdown complete.")

    async def main():
        """
        The main entry point for the Forge service.
        """
        logger.info("--- Initializing The Forge ---")

        # 1. Wait for Redis to be available (from Chunk 1)
        if not await wait_for_redis(timeout=10):
            logger.critical("Could not connect to Redis. The Forge cannot start.")
            sys.exit(1)

        # 2. Create the runner instance and its main task
        runner = ForgeRunner()
        runner_task = asyncio.create_task(runner.run())

        # 3. Set up signal handlers for graceful shutdown (Ctrl+C)
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(
                sig,
                lambda s=sig: asyncio.create_task(shutdown(s, runner_task))
            )
        
        logger.info("--- The Forge is operational ---")
        
        try:
            # This will run until the runner_task is cancelled by the shutdown handler
            await runner_task
        except asyncio.CancelledError:
            # This is expected during a graceful shutdown
            pass

    if __name__ == "__main__":
        try:
            asyncio.run(main())
        except (KeyboardInterrupt, SystemExit):
            logger.info("Forge process terminated.")
    ''',
    "tests/test_events/test_contracts.py": '''
    # tests/test_events/test_contracts.py

    import uuid
    from datetime import datetime

    # Import the serialization functions from Chunk 1
    from aegis.bus import deserialize, serialize

    # Import the contracts to be tested (from this chunk)
    from aegis.events.contracts import SkillRequest, SkillResponse

    def test_skill_request_serialization_round_trip():
        """
        Tests that a SkillRequest can be serialized and deserialized
        back into an identical object using the bus's serializer.
        """
        # 1. Create an instance of the model
        original_request = SkillRequest(
            skill_name="test_skill",
            payload={"arg1": "value1", "arg2": 123},
            correlation_id=uuid.uuid4()
        )

        # 2. Serialize it using the function from aegis.bus
        serialized_payload = serialize(original_request)
        assert isinstance(serialized_payload, str)

        # 3. Deserialize it
        deserialized_request = deserialize(serialized_payload)

        # 4. Verify the objects are identical
        assert isinstance(deserialized_request, SkillRequest)
        assert deserialized_request == original_request

    def test_skill_response_serialization_round_trip():
        """
        Tests that a SkillResponse can be serialized and deserialized
        back into an identical object using the bus's serializer.
        """
        # 1. Create an instance of the model
        original_response = SkillResponse(
            correlation_id=uuid.uuid4(),
            status="success",
            result={"output": "done", "value": 456},
        )

        # 2. Serialize it
        serialized_payload = serialize(original_response)
        assert isinstance(serialized_payload, str)

        # 3. Deserialize it
        deserialized_response = deserialize(serialized_payload)

        # 4. Verify the objects are identical
        assert isinstance(deserialized_response, SkillResponse)
        assert deserialized_response == original_response
    ''',
    "tests/test_forge/test_runner.py": '''
    # tests/test_forge/test_runner.py

    import asyncio
    import uuid
    from unittest.mock import AsyncMock, patch

    import pytest

    from aegis.events.contracts import SkillRequest, SkillResponse
    from aegis.forge.runner import ForgeRunner
    from aegis.skills.base import register_skill

    # Mark all tests in this file as async
    pytestmark = pytest.mark.asyncio

    # --- Test Skill Setup ---

    @register_skill
    async def failing_skill(payload: dict):
        """A skill specifically for testing the failure path."""
        raise ValueError("This skill was designed to fail.")

    # --- Pytest Fixture for Test Setup ---

    @pytest.fixture
    def runner_setup():
        """
        Sets up a ForgeRunner instance with a mocked MessageBus.
        
        This fixture provides:
        - A ForgeRunner instance.
        - An asyncio.Queue to simulate messages coming from bus.subscribe().
        - An AsyncMock to capture calls to bus.publish().
        """
        # This queue will act as the source for the mocked subscribe method
        subscribe_queue = asyncio.Queue()

        # The mock for the publish method
        publish_mock = AsyncMock()

        # Create an async generator from the queue to mock bus.subscribe()
        async def mock_subscribe(*args, **kwargs):
            while True:
                request = await subscribe_queue.get()
                yield request

        # Patch the MessageBus within the runner's module
        with patch("aegis.forge.runner.MessageBus") as MockMessageBus:
            # Configure the mock instance that the runner will create
            mock_bus_instance = MockMessageBus.return_value
            mock_bus_instance.subscribe.side_effect = mock_subscribe
            mock_bus_instance.publish = publish_mock

            # Instantiate the runner, which will now use our mocked bus
            runner = ForgeRunner()
            
            yield runner, subscribe_queue, publish_mock

    # --- Test Cases ---

    async def test_runner_happy_path(runner_setup):
        """
        Tests that the runner successfully processes a valid skill request.
        """
        runner, queue, publish_mock = runner_setup
        
        # Start the runner in the background
        runner_task = asyncio.create_task(runner.run())

        # 1. Create a valid request for a known skill
        request = SkillRequest(skill_name="placeholder_skill", payload={"duration_seconds": 0.1})
        
        # 2. "Publish" the request to our mock bus
        await queue.put(request)

        # 3. Wait for the publish mock to be called (with a timeout)
        await asyncio.wait_for(publish_mock.call_args_async, timeout=1.0)
        
        # 4. Assert the response
        publish_mock.assert_called_once()
        response = publish_mock.call_args[0][0]
        
        assert isinstance(response, SkillResponse)
        assert response.correlation_id == request.correlation_id
        assert response.status == "success"
        assert response.result["message"] == "Placeholder skill executed successfully."
        
        # Cleanup
        runner_task.cancel()

    async def test_runner_skill_not_found(runner_setup):
        """
        Tests that the runner correctly handles a request for a nonexistent skill.
        """
        runner, queue, publish_mock = runner_setup
        runner_task = asyncio.create_task(runner.run())

        # 1. Create a request for a skill that isn't registered
        request = SkillRequest(skill_name="non_existent_skill")
        
        # 2. Publish it
        await queue.put(request)

        # 3. Wait for the response
        await asyncio.wait_for(publish_mock.call_args_async, timeout=1.0)
        
        # 4. Assert the failure response
        publish_mock.assert_called_once()
        response = publish_mock.call_args[0][0]
        
        assert isinstance(response, SkillResponse)
        assert response.correlation_id == request.correlation_id
        assert response.status == "failure"
        assert "not registered" in response.error_message
        
        runner_task.cancel()

    async def test_runner_skill_execution_fails(runner_setup):
        """
        Tests that the runner correctly handles a skill that raises an exception.
        """
        runner, queue, publish_mock = runner_setup
        runner_task = asyncio.create_task(runner.run())

        # 1. Create a request for our skill that is designed to fail
        request = SkillRequest(skill_name="failing_skill")
        
        # 2. Publish it
        await queue.put(request)

        # 3. Wait for the response
        await asyncio.wait_for(publish_mock.call_args_async, timeout=1.0)
        
        # 4. Assert the failure response
        publish_mock.assert_called_once()
        response = publish_mock.call_args[0][0]
        
        assert isinstance(response, SkillResponse)
        assert response.correlation_id == request.correlation_id
        assert response.status == "failure"
        assert "This skill was designed to fail" in response.error_message

        runner_task.cancel()
    '''
}

def create_package_init_files(path):
    """Create __init__.py files in parent directories if they don't exist."""
    dir_name = os.path.dirname(path)
    if dir_name and (dir_name.startswith("src/") or dir_name.startswith("tests/")):
        parts = dir_name.split('/')
        for i in range(2, len(parts) + 1):
            pkg_path = "/".join(parts[:i])
            init_file = os.path.join(pkg_path, "__init__.py")
            if not os.path.exists(init_file):
                print(f"  [Created]  {init_file} (empty package marker)")
                with open(init_file, "w") as f:
                    pass

def main():
    """Main function to write all files."""
    print("--- Assembling Aegis Chunk 2: The Forge ---")
    
    for path, content in CHUNK_2_FILES.items():
        # Ensure the directory exists
        dir_name = os.path.dirname(path)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)
            create_package_init_files(path)

        print(f"  [Writing]  {path}")
        with open(path, "w") as f:
            f.write(textwrap.dedent(content.strip()))
            
    print("\\n--- Assembly Complete ---")
    print("All files for Chunk 2 have been written to your local project.")

if __name__ == "__main__":
    main()
