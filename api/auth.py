from fastapi import Depends, HTTPException, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from core.database import get_session
from core.db_models import Tenant, ApiKey
from typing import Optional

async def get_current_tenant(
        request: Request,
        api_key: Optional[str] = Header(None, alias = "X-API-Key"),
        session: AsyncSession = Depends(get_session),
) -> Tenant:
    """Get Tenant from API key header or Session cookie."""

    # Try header first (for programmatic API access)
    key = api_key

    # Fall back to cookie (for browser dashboard)
    if not key:
        key = request.cookies.get("qf_session")

    if not key:
        raise HTTPException(status_code=401, detail="Missing API key or session")
    

    result = await session.execute(
        select(ApiKey).where(ApiKey.key == key, ApiKey.is_active == True)
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