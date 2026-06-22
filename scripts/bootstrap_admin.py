"""Bootstrap an Admin tenant -> API key for a fresh QueueFlow installation.

Run once per installation, before any HTTP traffic. Subsequent tenants
are created via POST /tenants/ using this admin's API key.

Usage:
    docker compose exec api python scripts/bootstrap_admin.py \\
        --name "MyOrg"

Optional:
    --key SECRET    Use a specific API key value (otherwise generated).
                    Useful for scripted/reproducible deploys.
    --idempotent    Exit cleanly if an admin tenant already exists,
                    without creating duplicates.
"""

import argparse
import asyncio
import secrets
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession

from core.config import settings
from core.db_models import Tenant, ApiKey


async def main(name: str, key: str | None, idempotent: bool) -> int:
    engine = create_async_engine(settings.database_url)
    try:
        async with AsyncSession(engine) as session:
            # Refuse to create a second admin - bootstrap is a one-time operation
            existing = await session.execute(
                select(Tenant).where(Tenant.is_admin == True, Tenant.is_active  == True)
            )
            existing_admin = existing.scalar_one_or_none()
            if existing_admin:
                if idempotent:
                    print(
                        f"Admin tenant already exists: {existing_admin.name} "
                        f"({existing_admin.id}). Nothing to do.",
                        file = sys.stderr,
                    )
                    return 0
                print(
                    f"ERROR: an admin tenant already exists "
                    f"({existing_admin.name} / {existing_admin.id}). "
                    f"Pass --idempotent to no-op when present.",
                    file = sys.stderr,
                )
                return 1
            

            tenant = Tenant(name = name, is_admin = True, is_active = True)
            session.add(tenant)
            await session.flush()
            await session.refresh(tenant)

            api_key_value = key or secrets.token_urlsafe(32)
            api_key = ApiKey(
                tenant_id = tenant.id,
                key = api_key_value,
                label = "bootstrap",
                is_active = True,
            )

            session.add(api_key)
            # Capture values before commit. commit() expires all instance
            # attributes by default; re-reading them afterwards triggers
            # a lazy DB load, which doesn't work cleanly under async without
            # greenlet plumbing. Local vars sidestep that entirely.
            
            tenant_name = tenant.name
            tenant_id_str = str(tenant.id)

            await session.commit()

            print("=" * 60)
            print("Admin tenant created.")
            print(f" Name:      {tenant_name}")
            print(f" Tenant ID: {tenant_id_str}")
            print(f" API Key:   {api_key_value}")
            print("=" * 60)
            print(
                "Store this API key now - it cannot be retrieved later. "
                "Use it as X-API-Key for all admin operations.",
                file = sys.stderr
            )
            return 0
    finally:
        await engine.dispose()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description = __doc__.split("\n\n")[0])
    parser.add_argument("--name", required = True, help = "Admin tenant display name")
    parser.add_argument("--key", default = None, help = "Optional fixed API key value")
    parser.add_argument(
        "--idempotent",
        action = "store_true",
        help = "Exit cleanly if an admin tenant already exists",
    )
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.name, args.key, args.idempotent)))