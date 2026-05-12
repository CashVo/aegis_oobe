# aegis/forge/skills/manage_git_workflow.py
# Implements: Part VIII, §8.2 — manage_git_workflow skill
# Validates: UC-4 — Git Workflow
"""
Skill: manage_git_workflow
Execute a full feature branch lifecycle:
create branch → stage → commit → push → merge to main → push.
"""

from aegis.forge.skills.base import SkillManifest, SkillResult


manifest = SkillManifest(
    name="manage_git_workflow",
    description="Execute a full feature branch lifecycle: create branch, stage, commit, push, merge to main, push.",
    version="1.0.0",
    parameters_schema={
        "type": "object",
        "properties": {
            "branch_name": {"type": "string", "description": "Name of the feature branch to create."},
            "commit_message": {"type": "string", "description": "Commit message for the staged changes."},
            "cwd": {"type": "string", "default": ".", "description": "Repository working directory."},
            "files_to_stage": {"type": "array", "items": {"type": "string"}, "default": ["."], "description": "Files to stage (default: all)."},
            "push": {"type": "boolean", "default": True, "description": "Whether to push to remote."},
            "merge_to_main": {"type": "boolean", "default": True, "description": "Whether to merge branch into main."},
            "main_branch": {"type": "string", "default": "main", "description": "Name of the main branch."},
        },
        "required": ["branch_name", "commit_message"],
    },
    permissions_required=["git.execute", "shell.execute"],
    tools_used=["git_command", "execute_shell_command"],
    requires_oracle=False,
    scope="system",
    timeout_seconds=120,
)


async def execute(params: dict, forge_context) -> SkillResult:
    """
    Execute a full Git feature branch workflow.

    Steps:
    1. Create and checkout feature branch
    2. Stage specified files
    3. Commit with message
    4. Push feature branch (if enabled)
    5. Checkout main branch
    6. Merge feature branch into main
    7. Push main (if enabled)

    Args:
        params: Git workflow parameters.
        forge_context: ForgeContext with tool access.

    Returns:
        SkillResult with workflow execution details.
    """
    branch_name = params.get("branch_name")
    commit_message = params.get("commit_message")
    cwd = params.get("cwd", ".")
    files_to_stage = params.get("files_to_stage", ["."])
    push = params.get("push", True)
    merge_to_main = params.get("merge_to_main", True)
    main_branch = params.get("main_branch", "main")

    if not branch_name:
        return SkillResult(success=False, error="Parameter 'branch_name' is required.")
    if not commit_message:
        return SkillResult(success=False, error="Parameter 'commit_message' is required.")

    steps = []
    results = {}

    async def git(args: str) -> dict:
        """Helper to run git commands and track steps."""
        result = await forge_context.invoke_tool("git_command", {"args": args, "cwd": cwd})
        return {"success": result.success, "data": result.data, "error": result.error}

    # Step 1: Create and checkout feature branch
    r = await git(f"checkout -b {branch_name}")
    steps.append(f"git checkout -b {branch_name}")
    results["create_branch"] = r
    if not r["success"]:
        # Branch might already exist — try checkout
        r = await git(f"checkout {branch_name}")
        steps.append(f"git checkout {branch_name} (fallback)")
        results["checkout_branch"] = r
        if not r["success"]:
            return SkillResult(
                success=False,
                data=results,
                steps_executed=steps,
                error=f"Failed to create/checkout branch '{branch_name}': {r['error']}",
            )

    # Step 2: Stage files
    stage_args = " ".join(files_to_stage)
    r = await git(f"add {stage_args}")
    steps.append(f"git add {stage_args}")
    results["stage"] = r
    if not r["success"]:
        return SkillResult(
            success=False,
            data=results,
            steps_executed=steps,
            error=f"Failed to stage files: {r['error']}",
        )

    # Step 3: Commit
    r = await git(f'commit -m "{commit_message}"')
    steps.append(f"git commit -m \"{commit_message}\"")
    results["commit"] = r
    if not r["success"]:
        # Check if it's "nothing to commit"
        error_msg = r.get("error", "") or ""
        if "nothing to commit" in error_msg.lower():
            steps.append("Nothing to commit — working tree clean")
            results["commit_note"] = "Nothing to commit"
        else:
            return SkillResult(
                success=False,
                data=results,
                steps_executed=steps,
                error=f"Failed to commit: {r['error']}",
            )

    # Step 4: Push feature branch
    if push:
        r = await git(f"push -u origin {branch_name}")
        steps.append(f"git push -u origin {branch_name}")
        results["push_feature"] = r
        if not r["success"]:
            # Gracefully handle no remote
            error_msg = r.get("error", "") or ""
            if "remote" in error_msg.lower() or "not found" in error_msg.lower():
                steps.append("No remote configured — push skipped (graceful)")
                results["push_note"] = "No remote configured"
            else:
                return SkillResult(
                    success=False,
                    data=results,
                    steps_executed=steps,
                    error=f"Failed to push feature branch: {r['error']}",
                )

    # Step 5 & 6: Merge to main
    if merge_to_main:
        # Checkout main
        r = await git(f"checkout {main_branch}")
        steps.append(f"git checkout {main_branch}")
        results["checkout_main"] = r
        if not r["success"]:
            return SkillResult(
                success=False,
                data=results,
                steps_executed=steps,
                error=f"Failed to checkout {main_branch}: {r['error']}",
            )

        # Merge feature branch
        r = await git(f"merge {branch_name}")
        steps.append(f"git merge {branch_name}")
        results["merge"] = r
        if not r["success"]:
            return SkillResult(
                success=False,
                data=results,
                steps_executed=steps,
                error=f"Merge failed: {r['error']}",
            )

        # Step 7: Push main
        if push:
            r = await git(f"push origin {main_branch}")
            steps.append(f"git push origin {main_branch}")
            results["push_main"] = r
            if not r["success"]:
                error_msg = r.get("error", "") or ""
                if "remote" in error_msg.lower() or "not found" in error_msg.lower():
                    steps.append("No remote configured — push main skipped (graceful)")
                    results["push_main_note"] = "No remote configured"
                else:
                    return SkillResult(
                        success=False,
                        data=results,
                        steps_executed=steps,
                        error=f"Failed to push main: {r['error']}",
                    )

    return SkillResult(
        success=True,
        data={
            "branch": branch_name,
            "main_branch": main_branch,
            "commit_message": commit_message,
            "merged": merge_to_main,
            "pushed": push,
            "results": results,
        },
        steps_executed=steps,
    )
