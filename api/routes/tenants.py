from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from sqlalchemy import select
import uuid
import logging

from core.database import get_api_session
from core.db_models import Tenant, ApiKey
from core.key_utils import generate_api_key

from api.schemas import TenantCreateRequest, TenantResponse, ApiKeyCreateRequest, ApiKeyResponse, ApiKeyCreateResponse
from api.auth import get_current_tenant, require_admin_tenant

router = APIRouter(prefix = "/tenants", tags = ["Tenants"])
logger = logging.getLogger(__name__)

@router.post("/", response_model = TenantResponse, status_code = 201)
async def create_tenant(
    request: TenantCreateRequest,
    session: AsyncSession = Depends(get_api_session),
    _admin: Tenant = Depends(require_admin_tenant), # admin only
):
    """Create a new tenant. Admin only."""
    # Check if tenant name already exists
    existing_tenant = await session.execute(
        select(Tenant).where(Tenant.name == request.name)
    )
    if existing_tenant.scalar_one_or_none():
        raise HTTPException(status_code = 409, detail = f"Tenant with name '{request.name}' already exists")
    tenant = Tenant(name = request.name)
    session.add(tenant)
    await session.commit()
    await session.refresh(tenant)
    return tenant

@router.post("/{tenant_id}/api-keys", response_model = ApiKeyCreateResponse, status_code = 201)
async def create_api_key(
    tenant_id: str,
    request: ApiKeyCreateRequest,
    session: AsyncSession = Depends(get_api_session),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Create a new API key for a tenant.
    
    Caller must be authenticated as the tenant in the path, OR be an admin.

    The cleartext key is returned in the response body ONCE. It is not
    stored in the database (only prefix + bcrypt hash are stored) and
    cannot be retrieved later. The caller must save the value at creation
    time or generate a new key.
    """
    try:
        tenant_uuid = uuid.UUID(tenant_id)
    except ValueError:
        raise HTTPException(status_code = 400, detail = "Invalid tenant ID format")
    
    # Owenership check
    if current_tenant.id != tenant_uuid and not current_tenant.is_admin:
        raise HTTPException(status_code = 403, detail = "Forbidden")
    
    result = await session.execute(
        select(Tenant).where(Tenant.id == tenant_uuid, Tenant.is_active == True)
    )
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code = 404, detail = "Tenant not found or inactive")
    
    full_key, prefix, key_hash = generate_api_key()
    api_key = ApiKey(
        tenant_id = tenant.id,
        prefix = prefix,
        key_hash = key_hash,
        label = request.label,
    )
    session.add(api_key)
    await session.commit()
    await session.refresh(api_key)
    return ApiKeyCreateResponse(
        id = api_key.id,
        tenant_id = api_key.tenant_id,
        prefix = api_key.prefix,
        key = full_key,
        label = api_key.label,
        is_active = api_key.is_active,
        created_at = api_key.created_at,
    )

@router.get("/{tenant_id}/api-keys", response_model = list[ApiKeyResponse])
async def list_api_keys(
    tenant_id: str,
    session: AsyncSession = Depends(get_api_session),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """List all API keys for a tenant.
    
    Caller must be authenticated as the tenant in the path, OR be an admin.
    """
    try:
        tenant_uuid = uuid.UUID(tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid tenant ID format")
    
    # Ownership check
    if current_tenant.id != tenant_uuid and not current_tenant.is_admin:
        raise HTTPException(status_code=403, detail="Forbidden")

    result = await session.execute(
        select(ApiKey).where(ApiKey.tenant_id == tenant_uuid)
    )
    api_keys = result.scalars().all()
    return api_keys