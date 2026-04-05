from fastapi import Depends, HTTPException, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from core.database import get_session
from core.db_models import Tenant, ApiKey

async def get_current_tenant(
        api_key: str = Header(..., alias = "X-API-Key"),
        session: AsyncSession = Depends(get_session),
) -> Tenant:
    """Dependency to get the current tenant based on the provided API key."""
    result = await session.execute(
        select(ApiKey).where(ApiKey.key == api_key, ApiKey.is_active == True)
    )
    api_key_record = result.scalar_one_or_none()
    if not api_key_record:
        raise HTTPException(status_code=401, detail="Invalid or inactive API key")
    
    tenant_result = await session.execute(
        select(Tenant).where(Tenant.id == api_key_record.tenant_id, Tenant.is_active == True)
    )
    tenant = tenant_result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=401, detail="Tenant not found or inactive")
    
    return tenant