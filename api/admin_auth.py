from fastapi import Depends, HTTPException
from api.auth import get_current_tenant
from core.db_models import Tenant

async def get_admin_tenant(
        tenant: Tenant = Depends(get_current_tenant),
) -> Tenant:
    """Require the authenticated tenant to be an admin."""
    if not tenant.is_admin:
        raise HTTPException(status_code = 403, detail= "Admin access required")
    return tenant