# aegis/agents/torchestrator/synthesizer.py
# Implements: Part II §2.1 — Response Synthesis
#
# The Synthesizer combines results from multiple task steps into a
# coherent final response for the user.

import logging
from typing import Any, Dict, List, Optional

from aegis.schemas.torchestrator import TaskPlan, TaskStatus, TaskStep

logger = logging.getLogger(__name__)


class ResponseSynthesizer:
    """
    Synthesizes final user-facing responses from task execution results.

    Strategies:
    - Single-step: Pass through the result directly.
    - Multi-step: Combine results based on the plan's synthesis_instructions.
    - Error: Produce a clear error message with context.
    """

    def __init__(self):
        logger.info("ResponseSynthesizer initialized.")

    def synthesize(self, plan: TaskPlan) -> str:
        """
        Synthesize a final response from a completed TaskPlan.

        Args:
            plan: The executed TaskPlan with results in each step.

        Returns:
            A string response ready for the user.
        """
        # Check for plan-level failure
        if plan.status == TaskStatus.FAILED:
            return self._synthesize_error(plan)

        # Collect completed step results
        completed_steps = [s for s in plan.steps if s.status == TaskStatus.COMPLETED]
        failed_steps = [s for s in plan.steps if s.status == TaskStatus.FAILED]

        if not completed_steps and failed_steps:
            return self._synthesize_error(plan)

        # Single-step plan: return result directly
        if len(plan.steps) == 1 and completed_steps:
            return self._extract_response_content(completed_steps[0])

        # Multi-step plan: combine results
        return self._synthesize_multi_step(plan, completed_steps, failed_steps)

    def synthesize_with_oracle_response(self, oracle_content: str, plan: TaskPlan) -> str:
        """
        When the final step is an Oracle query, use its response directly.

        Args:
            oracle_content: The Oracle's generated response.
            plan: The task plan for metadata context.

        Returns:
            The Oracle response (potentially with error notes appended).
        """
        failed_steps = [s for s in plan.steps if s.status == TaskStatus.FAILED]

        if failed_steps:
            # Append a note about failed sub-steps
            error_notes = "\n\n---\n*Note: Some sub-tasks encountered issues:*\n"
            for step in failed_steps:
                error_notes += f"- {step.description}: {step.error}\n"
            return oracle_content + error_notes

        return oracle_content

    def _synthesize_multi_step(
        self,
        plan: TaskPlan,
        completed_steps: List[TaskStep],
        failed_steps: List[TaskStep]
    ) -> str:
        """Combine multiple step results into one response."""
        parts: List[str] = []

        for step in completed_steps:
            content = self._extract_response_content(step)
            if content:
                parts.append(content)

        response = "\n\n".join(parts)

        # Add error notes if any steps failed
        if failed_steps:
            response += "\n\n---\n*Some steps encountered issues:*\n"
            for step in failed_steps:
                response += f"- {step.description}: {step.error or 'Unknown error'}\n"

        return response if response else "Task completed but produced no output."

    def _synthesize_error(self, plan: TaskPlan) -> str:
        """Generate an error response for a failed plan."""
        failed_steps = [s for s in plan.steps if s.status == TaskStatus.FAILED]

        if not failed_steps:
            return "I encountered an unexpected error while processing your request. Please try again."

        if len(failed_steps) == 1:
            step = failed_steps[0]
            return (
                f"I wasn't able to complete your request. "
                f"The step \"{step.description}\" failed: {step.error or 'Unknown error'}"
            )

        error_msg = "I encountered multiple issues while processing your request:\n"
        for step in failed_steps:
            error_msg += f"- {step.description}: {step.error or 'Unknown error'}\n"
        return error_msg

    def _extract_response_content(self, step: TaskStep) -> str:
        """Extract the displayable content from a step's result."""
        if not step.result:
            return ""

        result = step.result

        # Oracle responses have a 'content' field
        if "content" in result:
            content = result["content"]
            if isinstance(content, str):
                return content
            elif isinstance(content, dict):
                return str(content)

        # Forge/Tool responses have a 'data' field
        if "data" in result:
            data = result["data"]
            if isinstance(data, str):
                return data
            elif isinstance(data, dict):
                # Try to format dict data nicely
                return self._format_dict_result(data, step.description)

        # Generic result
        if "result" in result:
            return str(result["result"])

        # Last resort: dump the whole result
        if "success" in result and result.get("success"):
            # Filter out metadata keys
            display_keys = {k: v for k, v in result.items() if k not in ("success", "execution_time_ms")}
            if display_keys:
                return self._format_dict_result(display_keys, step.description)
            return f"✓ {step.description} completed successfully."

        return str(result)

    def _format_dict_result(self, data: Dict[str, Any], context: str = "") -> str:
        """Format a dictionary result for user display."""
        parts = []
        for key, value in data.items():
            if isinstance(value, list):
                parts.append(f"**{key.replace('_', ' ').title()}:**")
                for item in value:
                    parts.append(f"  - {item}")
            elif isinstance(value, dict):
                parts.append(f"**{key.replace('_', ' ').title()}:** {value}")
            else:
                parts.append(f"**{key.replace('_', ' ').title()}:** {value}")
        return "\n".join(parts)

    def build_synthesis_prompt(self, plan: TaskPlan, step_results: List[Dict[str, Any]]) -> str:
        """
        Build a prompt for Oracle-based synthesis when automatic
        synthesis is insufficient.

        Used for complex multi-step results that need natural language
        weaving.
        """
        prompt = f"""Synthesize the following task results into a clear, helpful response for the user.

Original user request: "{plan.intent.raw_input}"
Synthesis instructions: {plan.synthesis_instructions}

Step results:
"""
        for i, result in enumerate(step_results, 1):
            prompt += f"\nStep {i}: {result}\n"

        prompt += """
\nProvide a cohesive, natural response that addresses the user's original request.
Do not mention internal step numbers or agent names. Respond as if you did all the work yourself.
"""
        return prompt
