import logging

from fastapi import APIRouter, Depends, Query, HTTPException

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from core.database import get_session
from core.db_models import Tenant, TaskRecord, ApiKey

from api.admin_auth import get_admin_tenant
from api.schemas import TaskResponse, TenantResponse

router = APIRouter(prefix = "/admin", tags = ["Admin"])
logger = logging.getLogger(__name__)

@router.get("/tenants")
async def list_all_tenants(
    session: AsyncSession = Depends(get_session),
    admin: Tenant = Depends(get_admin_tenant),
):
    """List all tenants with their task counts."""
    result = await session.execute(select(Tenant))
    tenants = result.scalars().all()

    tenant_list = []
    for t in tenants:
        count_result = await session.execute(
            select(func.count(TaskRecord.id)).where(TaskRecord.tenant_id == t.id)
        )
        task_count = count_result.scalar()

        key_result = await session.execute(
            select(func.count(ApiKey.id)).where(ApiKey.tenant_id == t.id)
        )
        key_count = key_result.scalar()

        tenant_list.append({
            "id": str(t.id),
            "name": t.name,
            "is_active": t.is_active,
            "is_admin": t.is_admin,
            "created_at": t.created_at.isoformat(),
            "task_count": task_count,
            "api_key_count": key_count,
        })
    return tenant_list

@router.get("/tasks")
async def list_all_tasks(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str = Query(None),
    session: AsyncSession = Depends(get_session),
    admin: Tenant = Depends(get_admin_tenant),
):
    """List all tasks across all tenants."""
    query = select(TaskRecord)
    count_query = select(func.count(TaskRecord.id))

    if status:
        query = query.where(TaskRecord.status == status)
        count_query = count_query.where(TaskRecord.status == status)

    query = query.order_by(TaskRecord.created_at.desc())
    query = query.limit(page_size).offset((page - 1)* page_size)

    result = await session.execute(query)
    tasks = result.scalars().all()

    total_result = await session.execute(count_query)
    total = total_result.scalar()

    return {
        "tasks": [
            {
                "id": str(t.id),
                "task_number": t.task_number,
                "task_name": t.task_name,
                "status": t.status,
                "priority": t.priority,
                "retry_count": t.retry_count,
                "max_retries": t.max_retries,
                "error_message": t.error_message,
                "tenant_id": str(t.tenant_id) if t.tenant_id else None,
                "created_at": t.created_at.isoformat(),
                "updated_at": t.updated_at.isoformat() if t.updated_at else None,
            }
            for t in tasks
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }

@router.get("/stats")
async def system_stats(
    session: AsyncSession = Depends(get_session),
    admin: Tenant = Depends(get_admin_tenant),
):
    """Get system-wide statistics."""
    # Total tenants
    tenant_count = (await session.execute(select(func.count(Tenant.id)))).scalar()

    # Total tasks
    task_count = (await session.execute(select(func.count(TaskRecord.id)))).scalar()

    # Tasks by status
    status_result = await session.execute(
        select(TaskRecord.status, func.count(TaskRecord.id)).group_by(TaskRecord.status)
    )
    status_breakdown = {row[0]: row[1] for row in status_result.all()}

    # Tasks by type
    type_result = await session.execute(
        select(TaskRecord.task_name, func.count(TaskRecord.id)).group_by(TaskRecord.task_name)
    )
    type_breakdown = {row[0]: row[1] for row in type_result.all()}

    return {
        "total_tenants": tenant_count,
        "total_tasks": task_count,
        "tasks_by_status": status_breakdown,
        "tasks_by_type": type_breakdown,
    }


@router.post("/tenants/{tenant_id}/toggle")
async def toggle_tenant(
    tenant_id: str,
    session: AsyncSession = Depends(get_session),
    admin: Tenant = Depends(get_admin_tenant),
):
    """Activate or deactivate a tenant."""
    import uuid
    try:
        tid = uuid.UUID(tenant_id)
    except ValueError:
        raise HTTPException(status_code = 400, detail = "Invalid tenant ID")
    
    result = await session.execute(select(Tenant).where(Tenant.id == tid))
    tenant = result.scalar_one_or_none()
    if not tenant:
        from fastapi import HTTPException
        raise HTTPException(status_code = 404, detail = "Tenant not found")
    
    tenant.is_active = not tenant.is_active
    await session.commit()

    return{
        "id": str(tenant.id),
        "name": tenant.name,
        "is_active": tenant.is_active,
        "message": f"Tenant {'activated' if tenant.is_active else 'deactivated'}", 
    }

