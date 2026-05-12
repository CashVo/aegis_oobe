# aegis/forge/skills/rlm_protocol.py
# Implements: Part VIII, §8.2 — RLM_protocol skill
"""
Skill: rlm_protocol
Reflective Learning Memory — after completing a task, extract lessons learned
and promote them to Lexicon (L1/L2).
"""

from aegis.forge.skills.base import SkillManifest, SkillResult


manifest = SkillManifest(
    name="rlm_protocol",
    description="Reflective Learning Memory — extract lessons learned from a completed task and promote to Lexicon memory.",
    version="1.0.0",
    parameters_schema={
        "type": "object",
        "properties": {
            "task_description": {"type": "string", "description": "Description of the completed task."},
            "task_outcome": {"type": "string", "description": "What happened — outcome, results, observations."},
            "context": {"type": "string", "description": "Additional context about the task environment."},
            "domain": {"type": "string", "description": "Knowledge domain for categorization (e.g., 'python', 'architecture')."},
        },
        "required": ["task_description", "task_outcome"],
    },
    permissions_required=["skill.execute", "memory.write"],
    tools_used=[],
    requires_oracle=True,
    scope="system",
    timeout_seconds=60,
)


async def execute(params: dict, forge_context) -> SkillResult:
    """
    Execute Reflective Learning Memory protocol.

    Steps:
    1. Send task description + outcome to Oracle for reflection.
    2. Oracle extracts: lessons learned, patterns, knowledge to retain.
    3. Store extracted knowledge in Lexicon via context store.
    4. Promote to appropriate tier (L1 for facts, L2 for procedures).

    Args:
        params: {"task_description": str, "task_outcome": str, "context": str, "domain": str}
        forge_context: ForgeContext with oracle and lexicon access.

    Returns:
        SkillResult with extracted lessons and promotion status.
    """
    task_description = params.get("task_description")
    task_outcome = params.get("task_outcome")
    context = params.get("context", "")
    domain = params.get("domain", "general")

    if not task_description:
        return SkillResult(success=False, error="Parameter 'task_description' is required.")
    if not task_outcome:
        return SkillResult(success=False, error="Parameter 'task_outcome' is required.")

    steps = []

    # Step 1: Reflect via Oracle
    system_prompt = (
        "You are a learning extraction system. Analyze the completed task and extract:\n"
        "1. **Factual Knowledge** (L1): New facts, tools, libraries, APIs, or domain knowledge learned.\n"
        "2. **Procedural Knowledge** (L2): Patterns, workflows, conventions, or processes that worked well.\n"
        "3. **Anti-Patterns**: Things that didn't work or should be avoided.\n"
        "4. **Connections**: How this relates to existing knowledge.\n\n"
        "Output as JSON with keys: factual_knowledge (array), procedural_knowledge (array), "
        "anti_patterns (array), connections (array). Each item should have 'content' and 'confidence' (0-1) fields."
    )

    prompt = (
        f"Task: {task_description}\n\n"
        f"Outcome: {task_outcome}\n\n"
        f"Context: {context}\n\n"
        f"Domain: {domain}\n\n"
        "Extract all reusable knowledge from this experience."
    )

    oracle_response = await forge_context.invoke_oracle({
        "action": "structured",
        "prompt": prompt,
        "system_prompt": system_prompt,
        "temperature": 0.3,
        "max_tokens": 2000,
        "response_format": "json",
    })

    steps.append("Reflective analysis via Oracle")

    if not oracle_response.get("success"):
        return SkillResult(
            success=False,
            steps_executed=steps,
            error=f"Oracle reflection failed: {oracle_response.get('error', 'Unknown error')}",
        )

    extracted = oracle_response.get("content", {})
    steps.append(f"Extracted knowledge for domain: {domain}")

    # Step 2: Store in Lexicon (via bus)
    # Store as episodic memory (L3) first, then promote
    store_response = await forge_context.get_context(
        query=f"RLM: {task_description}",
        scope=["L1", "L2"],
        token_budget=500,
    )
    steps.append("Queried existing Lexicon context for deduplication")

    # NOTE: Actual Lexicon STORE_MEMORY and PROMOTE_MEMORY would be done via
    # bus messages to the Lexicon agent. In OOBE, we structure the data
    # for Lexicon consumption and return it for the orchestrator to route.

    return SkillResult(
        success=True,
        data={
            "task_description": task_description,
            "domain": domain,
            "extracted_knowledge": extracted,
            "promotion_targets": {
                "L1_factual": "factual_knowledge items with confidence > 0.7",
                "L2_procedural": "procedural_knowledge items with confidence > 0.7",
            },
            "model_used": oracle_response.get("model_used", "unknown"),
            "existing_context_checked": bool(store_response.get("fragments")),
        },
        steps_executed=steps,
    )
