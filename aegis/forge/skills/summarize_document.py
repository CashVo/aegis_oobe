# aegis/forge/skills/summarize_document.py
# Implements: Part VIII, §8.2 — summarize_document skill
"""
Skill: summarize_document
Read a local file and produce a structured summary.
"""

from aegis.forge.skills.base import SkillManifest, SkillResult


manifest = SkillManifest(
    name="summarize_document",
    description="Read a local file and produce a structured summary.",
    version="1.0.0",
    parameters_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the file to summarize."},
            "summary_type": {"type": "string", "default": "structured", "description": "Summary type: structured, executive, technical."},
            "max_length": {"type": "integer", "default": 500, "description": "Maximum summary length in words."},
        },
        "required": ["path"],
    },
    permissions_required=["file.read", "tool.execute", "skill.execute"],
    tools_used=["file_read"],
    requires_oracle=True,
    scope="system",
    timeout_seconds=60,
)


async def execute(params: dict, forge_context) -> SkillResult:
    """
    Read a file and produce a structured summary.

    Steps:
    1. Read file content via file_read tool.
    2. Send content to Oracle for summarization.

    Args:
        params: {"path": str, "summary_type": str, "max_length": int}
        forge_context: ForgeContext with tool/oracle access.

    Returns:
        SkillResult with structured summary.
    """
    path = params.get("path")
    summary_type = params.get("summary_type", "structured")
    max_length = params.get("max_length", 500)

    if not path:
        return SkillResult(success=False, error="Parameter 'path' is required.")

    steps = []

    # Step 1: Read file
    read_result = await forge_context.invoke_tool("file_read", {"path": path})
    if not read_result.success:
        return SkillResult(
            success=False,
            steps_executed=["tool:file_read (failed)"],
            error=f"Failed to read file: {read_result.error}",
        )

    content = read_result.data.get("content", "")
    size_bytes = read_result.data.get("size_bytes", 0)
    steps.append(f"Read file: {path} ({size_bytes} bytes)")

    if not content.strip():
        return SkillResult(
            success=False,
            steps_executed=steps,
            error="File is empty — nothing to summarize.",
        )

    # Step 2: Summarize via Oracle
    type_instructions = {
        "structured": "Produce a structured summary with sections: Overview, Key Points, Details, Conclusions.",
        "executive": "Produce an executive summary suitable for a busy decision-maker. Lead with the bottom line.",
        "technical": "Produce a technical summary highlighting architecture, implementation details, and dependencies.",
    }

    oracle_response = await forge_context.invoke_oracle({
        "action": "query",
        "prompt": f"Summarize the following document content (max {max_length} words):\n\n{content[:15000]}",
        "system_prompt": f"You are a document summarization specialist. {type_instructions.get(summary_type, type_instructions['structured'])}",
        "temperature": 0.3,
        "max_tokens": max_length * 2,  # Rough tokens-to-words ratio
    })

    steps.append(f"Summarized via Oracle ({summary_type} style)")

    if oracle_response.get("success"):
        return SkillResult(
            success=True,
            data={
                "path": path,
                "summary": oracle_response.get("content", ""),
                "summary_type": summary_type,
                "source_size_bytes": size_bytes,
                "model_used": oracle_response.get("model_used", "unknown"),
            },
            steps_executed=steps,
        )
    else:
        return SkillResult(
            success=False,
            steps_executed=steps,
            error=f"Oracle summarization failed: {oracle_response.get('error', 'Unknown error')}",
        )
