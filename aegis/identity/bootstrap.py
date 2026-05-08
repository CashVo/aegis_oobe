# aegis/identity/bootstrap.py
# Implements: Part V, §5.4 — Bootstrap / First-Run

"""
IdentityBootstrap — Handles first-run system initialization.

On first launch (no tenants exist):
1. System Manager detects empty Identity store.
2. Creates "Default" tenant.
3. Creates root user with is_root=True.
4. Root user session is established.

This is the ONLY time a user is created outside the normal authenticated flow.
This directly addresses RT-1 (Bootstrap Paradox) from Part XIII.
"""

import logging
from typing import Optional, Tuple

from aegis.identity.store import IdentityStore
from aegis.schemas.identity import Tenant, User

logger = logging.getLogger(__name__)


class IdentityBootstrap:
    """
    Manages the first-run bootstrap sequence for the Identity subsystem.

    This class is invoked by the System Manager when it detects that
    the Identity store is empty (no tenants exist).
    """

    def __init__(self, store: IdentityStore):
        self.store = store

    async def needs_bootstrap(self) -> bool:
        """Check if the system needs initial bootstrapping."""
        return await self.store.is_empty()

    async def execute(
        self,
        root_username: str = "root",
        root_display_name: str = "System Root",
        root_passphrase: Optional[str] = None,
        tenant_name: str = "Default",
    ) -> Tuple[Tenant, User]:
        """
        Execute the full bootstrap sequence.

        This creates:
        1. The "Default" tenant with all system roles provisioned.
        2. The root user with full (*) permissions.

        Args:
            root_username: Username for the root user.
            root_display_name: Display name for the root user.
            root_passphrase: Optional passphrase. If None, local trust mode.
            tenant_name: Name for the initial tenant.

        Returns:
            Tuple of (created Tenant, created root User).

        Raises:
            RuntimeError: If bootstrap is called when tenants already exist.
        """
        if not await self.needs_bootstrap():
            raise RuntimeError(
                "Bootstrap aborted: Identity store is not empty. "
                "Tenants already exist."
            )

        logger.info("=" * 60)
        logger.info("IDENTITY BOOTSTRAP — First-Run Initialization")
        logger.info("=" * 60)

        # Step 1: Create the Default tenant (provisions system roles)
        logger.info(f"Step 1: Creating tenant '{tenant_name}'...")
        tenant = await self.store.create_tenant(name=tenant_name)
        logger.info(f"  → Tenant created: {tenant.tenant_id}")

        # Step 2: Create the root user
        logger.info(f"Step 2: Creating root user '{root_username}'...")
        root_user = await self.store.create_user(
            tenant_id=tenant.tenant_id,
            username=root_username,
            display_name=root_display_name,
            role_name="root",
            is_root=True,
            passphrase=root_passphrase,
        )
        logger.info(f"  → Root user created: {root_user.user_id}")

        logger.info("=" * 60)
        logger.info("BOOTSTRAP COMPLETE")
        logger.info(f"  Tenant: {tenant.name} ({tenant.tenant_id})")
        logger.info(f"  Root User: {root_user.username} ({root_user.user_id})")
        logger.info("=" * 60)

        return tenant, root_user
