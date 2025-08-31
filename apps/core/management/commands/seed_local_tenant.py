# apps/core/management/commands/seed_local_tenant.py
import os
import uuid
from django.core.management.base import BaseCommand
from django.db import connection

class Command(BaseCommand):
    help = "Seed Tenant + Membership for local dev using SEED_TENANT_CODE and SEED_USER_EMAIL"

    def handle(self, *args, **kwargs):
        tenant_code = os.getenv("SEED_TENANT_CODE", "ACME")
        user_email = os.getenv("SEED_USER_EMAIL", "admin@example.com")

        # Get user id
        with connection.cursor() as cur:
            cur.execute("SELECT UserId FROM dbo.[User] WHERE Email = %s", [user_email])
            r = cur.fetchone()
        if not r:
            self.stderr.write(self.style.ERROR(f"User not found: {user_email}"))
            return
        user_id = r[0]

        # Upsert tenant by code
        with connection.cursor() as cur:
            cur.execute("SELECT TenantId FROM dbo.Tenant WHERE Code = %s", [tenant_code])
            row = cur.fetchone()
        if row:
            tenant_id = row[0]
        else:
            tenant_id = uuid.uuid4()
            with connection.cursor() as cur:
                cur.execute("""
                  INSERT INTO dbo.Tenant (TenantId, Code, Name)
                  VALUES (%s, %s, %s)
                """, [str(tenant_id), tenant_code, tenant_code])

        # Upsert membership
        with connection.cursor() as cur:
            cur.execute("""
              SELECT 1 FROM dbo.Membership WHERE UserId=%s AND TenantId=%s
            """, [str(user_id), str(tenant_id)])
            exists = cur.fetchone()

        if not exists:
            with connection.cursor() as cur:
                cur.execute("""
                  INSERT INTO dbo.Membership (MembershipId, UserId, TenantId)
                  VALUES (NEWID(), %s, %s)
                """, [str(user_id), str(tenant_id)])

        self.stdout.write(self.style.SUCCESS(
            f"Seeded tenant={tenant_code} ({tenant_id}) for user={user_email}"
        ))
