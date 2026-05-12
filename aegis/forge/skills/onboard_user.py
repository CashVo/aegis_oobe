# aegis/forge/skills/onboard_user.py
# Implements: Part VIII, §8.2 — onboard_user skill
# Validates: UC-5 — User Onboarding
"""
Skill: onboard_user
Interactive skill to create a new user:
gather info → call Identity Agent → initialize Lexicon memory tiers.
"""

from aegis.forge.skills.base import SkillManifest, SkillResult


manifest = SkillManifest(
    name="onboard_user",
    description="Create a new user: validate input, create via Identity Agent, initialize Lexicon memory tiers.",
    version="1.0.0",
    parameters_schema={
        "type": "object",
        "properties": {
            "username": {"type": "string", "description": "Username for the new user."},
            "display_name": {"type": "string", "description": "Display name for the new user."},
            "email": {"type": "string", "description": "Optional email address."},
            "role": {"type": "string", "default": "member", "description": "Role to assign: member, admin, observer."},
            "tenant_id": {"type": "string", "description": "Tenant to create the user in (uses context tenant if not provided)."},
        },
        "required": ["username"],
    },
    permissions_required=["user.create", "memory.write"],
    tools_used=[],
    requires_oracle=False,
    scope="system",
    timeout_seconds=30,
)


async def execute(params: dict, forge_context) -> SkillResult:
    """
    Onboard a new user.

    Steps:
    1. Validate input parameters.
    2. Send CREATE_USER request to Identity Agent (via bus).
    3. Initialize Lexicon memory tiers for the new user.
    4. Return confirmation.

    NOTE: In full implementation, steps 2 & 3 are routed via the message bus
    to Identity and Lexicon agents respectively. For OOBE, we structure
    the requests and return them for the orchestrator to dispatch.

    Args:
        params: {"username": str, "display_name": str, "email": str, "role": str, "tenant_id": str}
        forge_context: ForgeContext.

    Returns:
        SkillResult with user creation details.
    """
    username = params.get("username")
    display_name = params.get("display_name", username)
    email = params.get("email")
    role = params.get("role", "member")
    tenant_id = params.get("tenant_id", forge_context.tenant_id)

    if not username:
        return SkillResult(success=False, error="Parameter 'username' is required.")

    # Validate role
    valid_roles = ["member", "admin", "observer"]
    if role not in valid_roles:
        return SkillResult(
            success=False,
            error=f"Invalid role '{role}'. Must be one of: {valid_roles}",
        )

    # Validate username format
    if len(username) < 2 or len(username) > 64:
        return SkillResult(success=False, error="Username must be 2-64 characters.")
    if not username.replace("_", "").replace("-", "").isalnum():
        return SkillResult(success=False, error="Username must be alphanumeric (underscores and hyphens allowed).")

    steps = []

    # Step 1: Construct Identity Agent request
    identity_request = {
        "action": "create_user",
        "tenant_id": tenant_id,
        "payload": {
            "username": username,
            "display_name": display_name,
            "email": email,
            "role": role,
            "is_root": False,
        },
    }
    steps.append(f"Prepared Identity CREATE_USER request for '{username}'")

    # Step 2: Construct Lexicon initialization request
    lexicon_init_request = {
        "action": "initialize_user_memory",
        "tenant_id": tenant_id,
        "payload": {
            "username": username,
            "tiers_to_initialize": ["L0", "L1", "L2", "L3", "L4"],
            "l0_defaults": {
                "display_name": display_name,
                "role": role,
                "created_via": "onboard_user skill",
            },
        },
    }
    steps.append(f"Prepared Lexicon memory initialization for '{username}'")

    # In full OOBE, these would be dispatched via the bus.
    # For now, return structured requests for the orchestrator.

    return SkillResult(
        success=True,
        data={
            "username": username,
            "display_name": display_name,
            "email": email,
            "role": role,
            "tenant_id": tenant_id,
            "identity_request": identity_request,
            "lexicon_init_request": lexicon_init_request,
            "message": f"User '{username}' onboarding prepared. Dispatch to Identity and Lexicon agents.",
        },
        steps_executed=steps,
    )
