# aegis/forge/skills/web_research.py
# Implements: Part VIII, §8.2 — web_research skill
"""
Skill: web_research
Conduct multi-step web research: search → fetch → extract → summarize.
"""

from aegis.forge.skills.base import SkillManifest, SkillResult


manifest = SkillManifest(
    name="web_research",
    description="Conduct multi-step web research: search, fetch, extract, and summarize.",
    version="1.0.0",
    parameters_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The research query/topic."},
            "urls": {"type": "array", "items": {"type": "string"}, "description": "Optional specific URLs to research."},
            "max_sources": {"type": "integer", "default": 3, "description": "Maximum number of sources to fetch."},
            "summary_style": {"type": "string", "default": "concise", "description": "Summary style: concise, detailed, bullet_points."},
        },
        "required": ["query"],
    },
    permissions_required=["network.http", "tool.execute", "skill.execute"],
    tools_used=["http_get"],
    requires_oracle=True,
    scope="system",
    timeout_seconds=120,
)


async def execute(params: dict, forge_context) -> SkillResult:
    """
    Execute multi-step web research.

    Steps:
    1. If URLs provided, use them. Otherwise, construct search URL.
    2. Fetch content from each URL via http_get tool.
    3. Extract relevant text content.
    4. Summarize via Oracle.

    Args:
        params: {"query": str, "urls": list[str], "max_sources": int, "summary_style": str}
        forge_context: ForgeContext with tool/oracle access.

    Returns:
        SkillResult with research summary and sources.
    """
    query = params.get("query")
    urls = params.get("urls", [])
    max_sources = params.get("max_sources", 3)
    summary_style = params.get("summary_style", "concise")

    if not query:
        return SkillResult(success=False, error="Parameter 'query' is required.")

    steps = []
    fetched_content = []

    # Step 1: Determine URLs to fetch
    if not urls:
        # Use a search engine URL as fallback
        search_url = f"https://www.google.com/search?q={query.replace(' ', '+')}"
        urls = [search_url]
        steps.append(f"Generated search URL for: {query}")

    # Step 2: Fetch content from URLs
    for i, url in enumerate(urls[:max_sources]):
        result = await forge_context.invoke_tool("http_get", {"url": url, "timeout": 15})
        if result.success and result.data:
            body = result.data.get("body", "")
            # Truncate to reasonable size for LLM processing
            truncated = body[:10000] if len(body) > 10000 else body
            fetched_content.append({
                "url": url,
                "content": truncated,
                "status": result.data.get("status_code", 0),
            })
            steps.append(f"Fetched: {url} (status: {result.data.get('status_code')})")
        else:
            steps.append(f"Failed to fetch: {url} — {result.error}")

    if not fetched_content:
        return SkillResult(
            success=False,
            data={"query": query, "sources_attempted": len(urls)},
            steps_executed=steps,
            error="Could not fetch any sources.",
        )

    # Step 3 & 4: Summarize via Oracle
    combined_text = "\n\n---\n\n".join(
        [f"Source: {c['url']}\n{c['content']}" for c in fetched_content]
    )

    style_instructions = {
        "concise": "Provide a concise 2-3 paragraph summary.",
        "detailed": "Provide a detailed summary covering all key points.",
        "bullet_points": "Provide a summary as structured bullet points.",
    }

    oracle_response = await forge_context.invoke_oracle({
        "action": "query",
        "prompt": f"Based on the following web content, answer this research query: {query}\n\n{combined_text}",
        "system_prompt": f"You are a research assistant. {style_instructions.get(summary_style, style_instructions['concise'])} Cite sources where possible.",
        "temperature": 0.3,
        "max_tokens": 2000,
    })

    steps.append("Summarized content via Oracle")

    if oracle_response.get("success"):
        return SkillResult(
            success=True,
            data={
                "query": query,
                "summary": oracle_response.get("content", ""),
                "sources": [{"url": c["url"], "status": c["status"]} for c in fetched_content],
                "sources_fetched": len(fetched_content),
                "model_used": oracle_response.get("model_used", "unknown"),
            },
            steps_executed=steps,
        )
    else:
        return SkillResult(
            success=False,
            data={"query": query, "raw_content": [c["url"] for c in fetched_content]},
            steps_executed=steps,
            error=f"Oracle summarization failed: {oracle_response.get('error', 'Unknown error')}",
        )
