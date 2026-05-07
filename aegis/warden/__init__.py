# aegis/warden/__init__.py
"""
Warden — Security Gatekeeper for Project Aegis.
Implements: Part II §2.1 (Warden role)

A universal, synchronous security interceptor. Validates every inter-agent
message and every tool/skill invocation against the active permission model.
Can ALLOW, DENY, or ESCALATE any request.
"""

from aegis.warden.permission_model import PermissionModel, PermissionDeniedError
from aegis.warden.allowlist import AllowlistEngine
from aegis.warden.interceptor import MessageInterceptor
from aegis.warden.bypass import BypassManager

__all__ = [
    "PermissionModel",
    "PermissionDeniedError",
    "AllowlistEngine",
    "MessageInterceptor",
    "BypassManager",
]
