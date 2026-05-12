# aegis/forge/skills/red_team_analysis.py
# Implements: Part VIII, §8.2 — red_team_analysis skill
"""
Skill: red_team_analysis
Analyze a given specification/plan for risks, blind spots, and failure modes.
"""

from aegis.forge.skills.base import SkillManifest, SkillResult


manifest = SkillManifest(
    name="red_team_analysis",
    description="Analyze a given specification/plan for risks, blind spots, and failure modes.",
    version="1.0.0",
    parameters_schema={
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "The specification, plan, or document content to analyze."},
            "focus_areas": {"type": "array", "items": {"type": "string"}, "description": "Optional specific areas to focus on (e.g., 'security', 'scalability')."},
            "severity_threshold": {"type": "string", "default": "medium", "description": "Minimum severity to report: low, medium, high, critical."},
        },
        "required": ["content"],
    },
    permissions_required=["skill.execute"],
    tools_used=[],
    requires_oracle=True,
    scope="system",
    timeout_seconds=90,
)


async def execute(params: dict, forge_context) -> SkillResult:
    """
    Perform red team analysis on provided content.

    Steps:
    1. Construct a red-team analysis prompt.
    2. Send to Oracle for analysis.
    3. Structure and return findings.

    Args:
        params: {"content": str, "focus_areas": list[str], "severity_threshold": str}
        forge_context: ForgeContext with oracle access.

    Returns:
        SkillResult with structured risk analysis.
    """
    content = params.get("content")
    focus_areas = params.get("focus_areas", [])
    severity_threshold = params.get("severity_threshold", "medium")

    if not content:
        return SkillResult(success=False, error="Parameter 'content' is required.")

    steps = []

    # Build focus area instructions
    focus_instruction = ""
    if focus_areas:
        focus_instruction = f"\nFocus especially on these areas: {', '.join(focus_areas)}."

    system_prompt = (
        "You are a senior security and systems architect performing a Red Team analysis. "
        "Your job is to find risks, blind spots, failure modes, and vulnerabilities in the "
        "provided specification or plan. Be thorough, adversarial, and constructive.\n\n"
        "For each finding, provide:\n"
        "1. Risk ID (RT-XXX)\n"
        "2. Severity (critical/high/medium/low)\n"
        "3. Category (security/reliability/scalability/design/operational)\n"
        "4. Description of the risk\n"
        "5. Attack vector or failure scenario\n"
        "6. Recommended mitigation\n\n"
        f"Minimum severity to report: {severity_threshold}.{focus_instruction}\n\n"
        "Output as structured JSON with a 'findings' array."
    )

    oracle_response = await forge_context.invoke_oracle({
        "action": "structured",
        "prompt": f"Perform a Red Team analysis on the following:\n\n{content[:15000]}",
        "system_prompt": system_prompt,
        "temperature": 0.4,
        "max_tokens": 3000,
        "response_format": "json",
    })

    steps.append("Red team analysis via Oracle")

    if oracle_response.get("success"):
        return SkillResult(
            success=True,
            data={
                "analysis": oracle_response.get("content", ""),
                "focus_areas": focus_areas,
                "severity_threshold": severity_threshold,
                "content_length": len(content),
                "model_used": oracle_response.get("model_used", "unknown"),
            },
            steps_executed=steps,
        )
    else:
        return SkillResult(
            success=False,
            steps_executed=steps,
            error=f"Oracle analysis failed: {oracle_response.get('error', 'Unknown error')}",
        )
