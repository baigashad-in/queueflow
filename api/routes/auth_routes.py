from fastapi import APIRouter, HTTPException, Response
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from core.database import get_session
from core.db_models import ApiKey, Tenant 

router = APIRouter(prefix = "/auth", tags = ["Auth"])

@router.post("/login")
async def login(
    response:Response,
    body: dict,
    session: AsyncSession = Depends(get_session),
):
    """Validate an API key and set an HTTP-only cookie."""
    key = body.get("api_key", "")
    if not key:
        raise HTTPException(status_code = 400, detail = "api_key is required.")
    
    result = await session.execute(
        select(ApiKey).where(ApiKey.key == key, ApiKey.is_active == True)
    )
    api_key_record = result.scalar_one_or_none()
    if not api_key_record:
        raise HTTPException(status_code = 401, detail = "Invalid API key.")
    
    tenant_result = await session.execute(
        select(Tenant).where(Tenant.id == api_key_record.tenant_id, Tenant.is_active == True)
    )
    tenant = tenant_result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code = 401, detail = "tenant not found or inactive.")
    
    # Set HTTP-only cookie with the API key
    response.set_cookie(
        key = "qf_session",
        value = key,
        httponly = True, # JavaScript cannot read this
        secure = True,   # Set True when you have HTTPS
        samesite = "lax", # Prevent CSRF from other sites
        max_age = 86400, # Expires in 24 hours
    )

    return {"tenant_id": tenant.name, "message": "Logged in"}

@router.post("/logout")
async def logout(response: Response):
    """Clear the session cookie."""
    response.delete_cookie("qf_session")
    return {"message": "Logged out"}

