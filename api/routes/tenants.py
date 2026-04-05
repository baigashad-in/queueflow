from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import uuid
import logging

from core.database import get_session
from core.db_models import Tenant, ApiKey
from api.schemas import TenantCreateRequest, TenantResponse, ApiKeyCreateRequest, ApiKeyResponse

router = APIRouter(prefix = "/tenants", tags = ["Tenants"])
logger = logging.getLogger(__name__)

@router.post("/", response_model = TenantResponse, status_code = 201)
async def create_tenant(
    request: TenantCreateRequest,
    session: AsyncSession = Depends(get_session),
):
    """Create a new tenant."""
    tenant = Tenant(name = request.name)
    session.add(tenant)
    await session.commit()
    await session.refresh(tenant)
    return tenant

@router.post("/{tenant_id}/api-keys", response_model = ApiKeyResponse, status_code = 201)
async def create_api_key(
    tenant_id: str,
    request: ApiKeyCreateRequest,
    session: AsyncSession = Depends(get_session),
):
    """Create a new API key for a tenant."""
    try:
        tenant_uuid = uuid.UUID(tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid tenant ID format")
    
    result = await session.execute(
        select(Tenant).where(Tenant.id == tenant_uuid, Tenant.is_active == True)
    )
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found or inactive")
    
    api_key = ApiKey(
        tenant_id = tenant.id,
        label = request.label,
    )
    session.add(api_key)
    await session.commit()
    await session.refresh(api_key)
    return api_key

@router.get("/{tenant_id}/api-keys", response_model = list[ApiKeyResponse])
async def list_api_keys(
    tenant_id: str,
    session: AsyncSession = Depends(get_session),
):
    """List all API keys for a tenant."""
    try:
        tenant_uuid = uuid.UUID(tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid tenant ID format")
    
    result = await session.execute(
        select(ApiKey).where(ApiKey.tenant_id == tenant_uuid)
    )
    api_keys = result.scalars().all()
    return api_keys