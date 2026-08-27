# aegis/agents/torchestrator/agent.py
# Implements: Part II §2.1 — TOrchestrator (Council Lead)
# Implements: Part II §2.3 — BaseAgent inheritance
# Implements: Part X §10.2 — Chat Protocol (ChatInput/ChatOutput)
# Implements: Part XII — UC-1, UC-2, UC-5, UC-6
#
# The TOrchestrator is the primary conversational interface agent.
# It receives user input, decomposes intent, dispatches tasks to other
# agents, and synthesizes final responses.

import asyncio
import logging
from aegis.utils import time
from typing import Any, Dict, List, Optional

from aegis.agents.base import BaseAgent
from aegis.agents.torchestrator.decomposer import TaskDecomposer
from aegis.agents.torchestrator.intent import IntentParser
from aegis.agents.torchestrator.router import MessageRouter
from aegis.agents.torchestrator.session import SessionManager
from aegis.agents.torchestrator.synthesizer import ResponseSynthesizer
from aegis.schemas.message import AegisMessage, MessageType
from aegis.schemas.torchestrator import (
    ChatInput,
    ChatOutput,
    Intent,
    IntentCategory,
    Session,
    TaskPlan,
    TaskStatus,
    TaskStep,
    TOrchestratorAction,
    TOrchestratorRequest,
    TOrchestratorResponse,
)

logger = logging.getLogger(__name__)


class TOrchestrator(BaseAgent):
    """
    The Council Lead — primary conversational interface agent for Project Aegis.

    Responsibilities:
    - Receive and interpret user input
    - Classify intent (rule-based + Oracle fallback)
    - Decompose complex requests into task plans
    - Dispatch tasks to appropriate agents via the message bus
    - Manage multi-turn conversation sessions
    - Synthesize coherent responses from multiple agent results

    This is the ONLY agent the user directly interacts with.
    """

    agent_id: str = "torchestrator"
    subscriptions: List[str] = ["aegis:stream:torchestrator"]

    def __init__(
        self,
        bus_publisher=None,
        bus_subscriber=None,
        redis_client=None,
        config: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize the TOrchestrator.

        Args:
            bus_publisher: Redis bus publisher (from CHUNK-002).
            bus_subscriber: Redis bus subscriber for incoming messages.
            redis_client: Redis client for session persistence.
            config: Optional configuration overrides.
        """
        # Call parent init for heartbeat and bus support
        super().__init__(agent_id=self.agent_id, subscriptions=self.subscriptions)
        
        self._config = config or {}
        self._intent_parser = IntentParser()
        self._decomposer = TaskDecomposer()
        self._session_manager = SessionManager(redis_client=redis_client)
        self._synthesizer = ResponseSynthesizer()
        self._router = MessageRouter(
            bus_publisher=bus_publisher,
            bus_subscriber=bus_subscriber,
            agent_id=self.agent_id
        )
        self._bus_publisher = bus_publisher
        self._bus_subscriber = bus_subscriber
        logger.info("TOrchestrator initialized.")

    async def startup(self) -> None:
        """Agent initialization — subscribe to channels, load config."""
        logger.info("TOrchestrator starting up...")
        
        # Create our own MessageSubscriber if we have a Redis connection
        if self._redis_conn is not None:
            from aegis.bus.subscriber import MessageSubscriber
            self._bus_subscriber = MessageSubscriber(
                redis_client=self._redis_conn,
                agent_id=self.agent_id,
                handler=self._on_bus_message,
                subscribe_to_broadcast=False,
            )
            # Start the subscriber FIRST (it subscribes to our main stream)
            await self._bus_subscriber.start()
            logger.info(f"TOrchestrator created its own MessageSubscriber with agent_id={self.agent_id}")
            logger.info(f"  Subscribed to stream: {self._bus_subscriber._stream}")
            logger.info(f"  Consumer group: {self._bus_subscriber._group}")
            logger.info(f"  Consumer: {self._bus_subscriber._consumer}")

            # Now subscribe to additional channels (after start so _running is True)
            # Skip the main stream since we're already subscribed via the subscriber
            main_stream = self._bus_subscriber._stream
            if self._bus_subscriber:
                for channel in self.subscriptions:
                    if channel == main_stream:
                        logger.debug(f"Skipping subscription to main stream '{channel}' (already subscribed)")
                        continue
                    await self._bus_subscriber.subscribe(channel, self._on_bus_message)
                logger.info(f"TOrchestrator subscribed to additional channels: {[c for c in self.subscriptions if c != main_stream]}")
        
        # Subscribe to our stream if bus is available (fallback for backward compat)
        elif self._bus_subscriber:
            for channel in self.subscriptions:
                await self._bus_subscriber.subscribe(channel, self._on_bus_message)
        logger.info("TOrchestrator ready. Subscribed to: %s", self.subscriptions)

        # Start heartbeat for this agent
        await self.start_heartbeat()
    async def shutdown(self) -> None:
        """Graceful teardown — persist sessions, unsubscribe."""
        logger.info("TOrchestrator shutting down...")
        # Clean up sessions
        await self._session_manager.cleanup_expired()
        logger.info("TOrchestrator shutdown complete.")

    async def handle_message(self, message: AegisMessage) -> Optional[AegisMessage]:
        """
        Process an incoming message from the bus.

        This handles both direct chat inputs and responses from other agents.
        """
        if message.message_type == MessageType.RESPONSE:
            # This is a response to a message we sent — route to pending futures
            await self._router.handle_incoming_response(message)
            return None

        if message.message_type == MessageType.REQUEST:
            # This is a new request — process it
            try:
                request = TOrchestratorRequest(
                    action=TOrchestratorAction(message.action.split(".")[-1]),
                    session_id=message.metadata.get("session_id"),
                    message=message.payload.get("message"),
                    tenant_id=message.tenant_id,
                    user_id=message.user_id,
                    metadata=message.metadata,
                )
                response = await self.process_request(request)
                return AegisMessage(
                    correlation_id=message.correlation_id,
                    source_agent=self.agent_id,
                    target_agent=message.source_agent,
                    message_type=MessageType.RESPONSE,
                    tenant_id=message.tenant_id,
                    user_id=message.user_id,
                    action=f"{self.agent_id}.response",
                    payload=response.model_dump(),
                )
            except Exception as e:
                logger.error("Error handling request: %s", e, exc_info=True)
                return AegisMessage(
                    correlation_id=message.correlation_id,
                    source_agent=self.agent_id,
                    target_agent=message.source_agent,
                    message_type=MessageType.ERROR,
                    tenant_id=message.tenant_id,
                    user_id=message.user_id,
                    action=f"{self.agent_id}.error",
                    payload={"error": str(e)},
                )
        return None

    async def _on_bus_message(self, message: AegisMessage) -> None:
        """Callback for messages received on our bus stream."""
        try:
            response = await self.handle_message(message)
            if response and self._bus_publisher:
                # Use response_channel from original message payload if present
                target_stream = message.payload.get("response_channel", f"aegis:stream:{response.target_agent}")
                await self._bus_publisher.publish_to_stream(target_stream, response)
        except Exception as e:
            logger.error("Error processing bus message: %s", e, exc_info=True)

    # ─── Primary Chat Interface ──────────────────────────────────────

    async def chat(self, chat_input: ChatInput) -> ChatOutput:
        """
        Primary chat interface — called by CLI and Web UI.

        This is the main entry point for user interaction.
        Implements the full pipeline: intent → decompose → execute → synthesize.

        Args:
            chat_input: The user's chat message with session context.

        Returns:
            ChatOutput with the assistant's response.
        """
        start_time = time.perf_counter()

        # 1. Session management — get or create session
        session = await self._resolve_session(chat_input)

        # 2. Record user turn
        await self._session_manager.add_turn(
            session.session_id, "user", chat_input.message
        )

        # 3. Process the message through the full pipeline
        try:
            response_text, metadata = await self._process_user_message(
                message=chat_input.message,
                session=session,
                tenant_id=chat_input.tenant_id,
                user_id=chat_input.user_id,
            )
        except Exception as e:
            logger.error("Error processing chat message: %s", e, exc_info=True)
            response_text = "I encountered an error while processing your request. Please try again."
            metadata = {"error": str(e)}

        # 4. Record assistant turn
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        elapsed_ms = max(elapsed_ms, 0.01)
        metadata["latency_ms"] = elapsed_ms

        await self._session_manager.add_turn(
            session.session_id, "assistant", response_text, metadata
        )

        # 5. Return response
        return ChatOutput(
            response=response_text,
            session_id=session.session_id,
            agent=self.agent_id,
            metadata=metadata,
        )

    async def process_request(self, request: TOrchestratorRequest) -> TOrchestratorResponse:
        """
        Process a structured TOrchestrator request.

        Handles all TOrchestratorAction types.
        """
        start_time = time.perf_counter()

        if request.action == TOrchestratorAction.CHAT:
            chat_input = ChatInput(
                message=request.message or "",
                session_id=request.session_id,
                tenant_id=request.tenant_id,
                user_id=request.user_id,
            )
            output = await self.chat(chat_input)
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            elapsed_ms = max(elapsed_ms, 0.01)
            return TOrchestratorResponse(
                success=True,
                response=output.response,
                session_id=output.session_id,
                action=request.action,
                tools_used=output.metadata.get("tools_used", []),
                skills_used=output.metadata.get("skills_used", []),
                latency_ms=elapsed_ms,
                metadata=output.metadata,
            )

        elif request.action == TOrchestratorAction.RESUME_SESSION:
            session = await self._session_manager.resume_session(request.session_id or "")
            if session:
                return TOrchestratorResponse(
                    success=True,
                    response=f"Session resumed. You have {len(session.history)} turns in history.",
                    session_id=session.session_id,
                    action=request.action,
                    latency_ms=(time.perf_counter() - start_time) * 1000,
                )
            return TOrchestratorResponse(
                success=False,
                action=request.action,
                error="Session not found or cannot be resumed.",
                latency_ms=(time.perf_counter() - start_time) * 1000,
            )

        elif request.action == TOrchestratorAction.LIST_SESSIONS:
            sessions = await self._session_manager.list_sessions(
                request.tenant_id, request.user_id
            )
            session_list = [
                {"id": s.session_id, "state": s.state.value, "turns": len(s.history), "last_activity": s.last_activity.isoformat()}
                for s in sessions
            ]
            return TOrchestratorResponse(
                success=True,
                response=f"Found {len(sessions)} sessions.",
                action=request.action,
                latency_ms=(time.perf_counter() - start_time) * 1000,
                metadata={"sessions": session_list},
            )

        elif request.action == TOrchestratorAction.CLOSE_SESSION:
            closed = await self._session_manager.close_session(request.session_id or "")
            return TOrchestratorResponse(
                success=closed,
                response="Session closed." if closed else "Session not found.",
                action=request.action,
                latency_ms=(time.perf_counter() - start_time) * 1000,
            )

        return TOrchestratorResponse(
            success=False,
            action=request.action,
            error=f"Unknown action: {request.action}",
            latency_ms=(time.perf_counter() - start_time) * 1000,
        )

    # ─── Core Processing Pipeline ────────────────────────────────────

    async def _process_user_message(
        self,
        message: str,
        session: Session,
        tenant_id: str,
        user_id: str,
    ) -> tuple:
        """
        Core processing pipeline:
        1. Parse intent (rule-based, then Oracle if needed)
        2. Decompose into task plan
        3. Execute task steps
        4. Synthesize response

        Returns:
            Tuple of (response_text, metadata_dict)
        """
        metadata: Dict[str, Any] = {}

        # ── Step 1: Intent Classification ────────────────────────────
        intent = self._intent_parser.parse_rule_based(message)

        if intent is None:
            # Rule-based parsing was inconclusive — use Oracle
            intent = await self._classify_with_oracle(message, session)
            metadata["intent_source"] = "oracle"
        else:
            metadata["intent_source"] = "rules"

        metadata["intent_category"] = intent.category.value
        metadata["intent_confidence"] = intent.confidence
        logger.info("Intent classified: %s (confidence: %.2f)", intent.category.value, intent.confidence)

        # ── Step 2: Task Decomposition ───────────────────────────────
        plan = self._decomposer.decompose(
            intent=intent,
            tenant_id=tenant_id,
            user_id=user_id,
            session_id=session.session_id,
        )
        logger.info("Task plan created: %d steps", len(plan.steps))

        # ── Step 3: Execute Plan ─────────────────────────────────────
        plan = await self._execute_plan(plan, tenant_id, user_id, session)
        metadata["steps_executed"] = len([s for s in plan.steps if s.status == TaskStatus.COMPLETED])
        metadata["steps_failed"] = len([s for s in plan.steps if s.status == TaskStatus.FAILED])

        # Collect tool/skill usage for metadata
        tools_used = []
        skills_used = []
        for step in plan.steps:
            if step.status == TaskStatus.COMPLETED:
                if "execute_tool" in step.action:
                    tool_name = step.payload.get("tool_name", "")
                    if tool_name:
                        tools_used.append(tool_name)
                elif "execute_skill" in step.action:
                    skill_name = step.payload.get("skill_name", "")
                    if skill_name:
                        skills_used.append(skill_name)
        metadata["tools_used"] = tools_used
        metadata["skills_used"] = skills_used

        # ── Step 4: Response Synthesis ───────────────────────────────
        response_text = self._synthesizer.synthesize(plan)

        # If the response is from Oracle (the last step is Oracle), use it directly
        completed_steps = [s for s in plan.steps if s.status == TaskStatus.COMPLETED]
        if completed_steps:
            last_step = completed_steps[-1]
            if last_step.target_agent == "oracle" and last_step.result:
                oracle_content = last_step.result.get("content", "")
                if oracle_content:
                    response_text = self._synthesizer.synthesize_with_oracle_response(
                        oracle_content, plan
                    )

        return response_text, metadata

    async def _classify_with_oracle(self, message: str, session: Session) -> Intent:
        """
        Use Oracle for intent classification when rule-based parsing fails.
        """
        # Build context from session history
        session_context = await self._session_manager.get_context_for_oracle(
            session.session_id, max_turns=5, max_tokens=1000
        )

        # Build classification prompt
        prompt = self._intent_parser.build_classification_prompt(message, session_context)

        # Route to Oracle
        step = TaskStep(
            order=1,
            description="Classify intent via Oracle",
            target_agent="oracle",
            action="oracle.structured",
            payload={
                "prompt": prompt,
                "action": "structured",
                "response_format": "json",
                "temperature": 0.3,
                "max_tokens": 500,
                "system_prompt": "You are an intent classification engine. Respond only with the requested JSON.",
            }
        )

        step = await self._router.execute_step(
            step=step,
            tenant_id=session.tenant_id,
            user_id=session.user_id,
            session_id=session.session_id,
            timeout=15.0,
        )

        if step.status == TaskStatus.COMPLETED and step.result:
            oracle_output = step.result.get("content", "")
            if isinstance(oracle_output, str):
                return self._intent_parser.parse_oracle_response(oracle_output, message)

        # Fallback if Oracle classification fails
        logger.warning("Oracle classification failed. Falling back to QUESTION intent.")
        return Intent(
            category=IntentCategory.QUESTION,
            confidence=0.5,
            raw_input=message,
            requires_oracle=True,
        )

    async def _execute_plan(
        self,
        plan: TaskPlan,
        tenant_id: str,
        user_id: str,
        session: Session,
    ) -> TaskPlan:
        """
        Execute all steps in a task plan, respecting dependencies.

        Steps without dependencies can execute in parallel.
        Steps with dependencies wait for their prerequisites.
        """
        plan.status = TaskStatus.IN_PROGRESS
        context_data: Dict[str, Any] = {}  # step_id → result mapping

        # Inject session context into Oracle steps
        session_context = await self._session_manager.get_context_for_oracle(
            session.session_id, max_turns=10, max_tokens=2000
        )

        # Group steps by execution order
        steps_by_order: Dict[int, List[TaskStep]] = {}
        for step in plan.steps:
            steps_by_order.setdefault(step.order, []).append(step)

        # Execute in order
        for order in sorted(steps_by_order.keys()):
            steps_at_level = steps_by_order[order]

            # Check if all steps at this level have their dependencies met
            executable = []
            for step in steps_at_level:
                deps_met = all(
                    any(s.step_id == dep_id and s.status == TaskStatus.COMPLETED
                        for s in plan.steps)
                    for dep_id in step.depends_on
                )
                if deps_met:
                    # Inject session context for Oracle steps
                    if step.target_agent == "oracle" and session_context:
                        if "system_prompt" not in step.payload:
                            step.payload["system_prompt"] = ""
                        step.payload.setdefault("conversation_context", session_context)
                    executable.append(step)
                else:
                    step.status = TaskStatus.SKIPPED
                    step.error = "Dependencies not met (prerequisite failed)."

            # Execute all executable steps at this level concurrently
            if len(executable) == 1:
                # Single step — execute directly
                step = executable[0]
                step = await self._router.execute_step(
                    step=step,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    session_id=session.session_id,
                    timeout=step.payload.get("timeout_seconds", 60.0),
                    context_data=context_data,
                )
                if step.result:
                    context_data[step.step_id] = step.result
            elif len(executable) > 1:
                # Multiple steps — execute concurrently
                tasks = [
                    self._router.execute_step(
                        step=step,
                        tenant_id=tenant_id,
                        user_id=user_id,
                        session_id=session.session_id,
                        timeout=step.payload.get("timeout_seconds", 60.0),
                        context_data=context_data,
                    )
                    for step in executable
                ]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for i, result in enumerate(results):
                    if isinstance(result, Exception):
                        executable[i].status = TaskStatus.FAILED
                        executable[i].error = str(result)
                    else:
                        if result.result:
                            context_data[result.step_id] = result.result

        # Determine plan-level status
        all_statuses = [s.status for s in plan.steps]
        if all(s == TaskStatus.COMPLETED for s in all_statuses):
            plan.status = TaskStatus.COMPLETED
        elif any(s == TaskStatus.FAILED for s in all_statuses):
            # Partial success if at least one step completed
            if any(s == TaskStatus.COMPLETED for s in all_statuses):
                plan.status = TaskStatus.COMPLETED  # Partial success
            else:
                plan.status = TaskStatus.FAILED
        else:
            plan.status = TaskStatus.COMPLETED

        return plan

    # ─── Session Helpers ─────────────────────────────────────────────

    async def _resolve_session(self, chat_input: ChatInput) -> Session:
        """Get existing session or create a new one."""
        if chat_input.session_id:
            session = await self._session_manager.get_session(chat_input.session_id)
            if session:
                return session
            logger.warning(
                "Session %s not found. Creating new session.", chat_input.session_id
            )

        return await self._session_manager.create_session(
            tenant_id=chat_input.tenant_id,
            user_id=chat_input.user_id,
        )
