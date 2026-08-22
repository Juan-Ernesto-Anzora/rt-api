/* Sprint 3 Day 9: support tenant-scoped newest-first audit reads. */
SET NOCOUNT ON;
SET XACT_ABORT ON;

IF OBJECT_ID(N'dbo.Activity', N'U') IS NULL
  THROW 51020, 'dbo.Activity must exist before applying the Day 9 upgrade.', 1;

IF NOT EXISTS (
  SELECT 1
  FROM sys.indexes
  WHERE object_id = OBJECT_ID(N'dbo.Activity')
    AND name = N'IX_Activity_TenantCreated'
)
  CREATE INDEX IX_Activity_TenantCreated
    ON dbo.Activity(TenantId, CreatedAt DESC);
