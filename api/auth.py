from typing import Optional

from fastapi import Depends, HTTPException, Header, Request

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from core.database import get_api_session
from core.db_models import Tenant, ApiKey
from core.key_utils import parse_api_key, verify_api_key

async def get_current_tenant(
        request: Request,
        api_key: Optional[str] = Header(None, alias = "X-API-Key"),
        session: AsyncSession = Depends(get_api_session),
) -> Tenant:
    """Get Tenant from API key header or Session cookie.
    
    Auth flow: parse the key into (prefix, secret), index-lookup by prefix,
    then bcrypt-verify the full key against the stored hash. Same rejection
    message for "prefix doesn't exist" and "prefix exists but hash doesn't
    match" so attackers can't enumerate valid prefixes.
    """

    # Try header first (programmatic API access), then cookie (dashboard)
    key = api_key or request.cookies.get("qf_session")

    if not key:
        raise HTTPException(status_code = 401, detail = "Missing API key or session")
    
    parsed = parse_api_key(key)
    if not parsed:
        raise HTTPException(status_code = 401, detail = "Invalid or inactive API key")
    prefix, _secret = parsed

    result = await session.execute(
        select(ApiKey).where(ApiKey.prefix == prefix, ApiKey.is_active == True)
    )
    
    api_key_record = result.scalar_one_or_none()
    if not api_key_record or not verify_api_key(key, api_key_record.key_hash):
        raise HTTPException(status_code = 401, detail="Invalid or inactive API key")
    
    tenant_result = await session.execute(
        select(Tenant).where(Tenant.id == api_key_record.tenant_id, Tenant.is_active == True)
    )
    tenant = tenant_result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code = 401, detail = "Tenant not found or inactive")
    
    return tenant

async def require_admin_tenant(
        tenant: Tenant = Depends(get_current_tenant),
) -> Tenant:
    """Require the caller's tenant to have admin privileges.
    
    Builds on get_current_tenant: caller must be authenticated AND
    is_admin = True. Used to gate  routes like POST /tenants/ that
    shouldn't be self-service.
    """
    if not tenant.is_admin:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    return tenant
