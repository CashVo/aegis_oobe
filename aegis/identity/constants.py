# aegis/identity/constants.py
# Implements: Part V, §5.2 — Default Roles

"""
System-wide constants for the Identity subsystem.
Default roles are created during tenant provisioning.
"""

DEFAULT_SYSTEM_ROLES = {
    "root": {
        "name": "root",
        "permissions": ["*"],
        "is_system_role": True,
    },
    "admin": {
        "name": "admin",
        "permissions": [
            "user.create", "user.update", "user.delete",
            "role.assign", "memory.read", "memory.write",
            "tool.execute", "skill.execute", "system.config",
        ],
        "is_system_role": True,
    },
    "member": {
        "name": "member",
        "permissions": [
            "memory.read", "memory.write.own",
            "tool.execute", "skill.execute",
        ],
        "is_system_role": True,
    },
    "observer": {
        "name": "observer",
        "permissions": ["memory.read.own"],
        "is_system_role": True,
    },
}
