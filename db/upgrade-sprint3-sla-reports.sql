/*
  Sprint 3 Day 7: evolve the existing SLA policy table in place and add
  editable ACME demo defaults. Safe to rerun; existing policy values are never
  updated. Apply after tenant creation.
*/
SET NOCOUNT ON;
SET XACT_ABORT ON;

IF OBJECT_ID(N'dbo.SlaPolicy', N'U') IS NULL
  THROW 51000, 'dbo.SlaPolicy must exist before applying the Day 7 upgrade.', 1;

IF EXISTS (SELECT 1 FROM dbo.SlaPolicy)
   AND (
     COL_LENGTH(N'dbo.SlaPolicy', N'Priority') IS NULL
     OR COL_LENGTH(N'dbo.SlaPolicy', N'ResponseMinutes') IS NULL
     OR COL_LENGTH(N'dbo.SlaPolicy', N'ResolutionMinutes') IS NULL
   )
  THROW 51001, 'Legacy SLA rows require explicit target mapping before upgrade.', 1;

BEGIN TRANSACTION;

IF COL_LENGTH(N'dbo.SlaPolicy', N'Priority') IS NULL
  ALTER TABLE dbo.SlaPolicy ADD Priority NVARCHAR(20) NOT NULL;

IF COL_LENGTH(N'dbo.SlaPolicy', N'ResponseMinutes') IS NULL
  ALTER TABLE dbo.SlaPolicy ADD ResponseMinutes INT NOT NULL;

IF COL_LENGTH(N'dbo.SlaPolicy', N'ResolutionMinutes') IS NULL
  ALTER TABLE dbo.SlaPolicy ADD ResolutionMinutes INT NOT NULL;

IF COL_LENGTH(N'dbo.SlaPolicy', N'IsActive') IS NULL
  ALTER TABLE dbo.SlaPolicy ADD IsActive BIT NOT NULL
    CONSTRAINT DF_SlaPolicy_IsActive DEFAULT(1);

IF COL_LENGTH(N'dbo.SlaPolicy', N'UpdatedAt') IS NULL
  ALTER TABLE dbo.SlaPolicy ADD UpdatedAt DATETIME2(3) NULL;

IF NOT EXISTS (
  SELECT 1 FROM sys.check_constraints
  WHERE parent_object_id = OBJECT_ID(N'dbo.SlaPolicy')
    AND name = N'CK_SlaPolicy_Priority'
)
  EXEC(N'ALTER TABLE dbo.SlaPolicy ADD CONSTRAINT CK_SlaPolicy_Priority
    CHECK (Priority IN (N''low'', N''normal'', N''high'', N''urgent''));');

IF NOT EXISTS (
  SELECT 1 FROM sys.check_constraints
  WHERE parent_object_id = OBJECT_ID(N'dbo.SlaPolicy')
    AND name = N'CK_SlaPolicy_ResponseMinutes'
)
  EXEC(N'ALTER TABLE dbo.SlaPolicy ADD CONSTRAINT CK_SlaPolicy_ResponseMinutes
    CHECK (ResponseMinutes > 0);');

IF NOT EXISTS (
  SELECT 1 FROM sys.check_constraints
  WHERE parent_object_id = OBJECT_ID(N'dbo.SlaPolicy')
    AND name = N'CK_SlaPolicy_ResolutionMinutes'
)
  EXEC(N'ALTER TABLE dbo.SlaPolicy ADD CONSTRAINT CK_SlaPolicy_ResolutionMinutes
    CHECK (ResolutionMinutes > 0);');

IF NOT EXISTS (
  SELECT 1 FROM sys.check_constraints
  WHERE parent_object_id = OBJECT_ID(N'dbo.SlaPolicy')
    AND name = N'CK_SlaPolicy_TargetOrder'
)
  EXEC(N'ALTER TABLE dbo.SlaPolicy ADD CONSTRAINT CK_SlaPolicy_TargetOrder
    CHECK (ResponseMinutes <= ResolutionMinutes);');

IF NOT EXISTS (
  SELECT 1 FROM sys.indexes
  WHERE object_id = OBJECT_ID(N'dbo.SlaPolicy')
    AND name = N'UQ_SlaPolicy_TenantName'
)
  EXEC(N'CREATE UNIQUE INDEX UQ_SlaPolicy_TenantName
    ON dbo.SlaPolicy(TenantId, Name);');

IF NOT EXISTS (
  SELECT 1 FROM sys.indexes
  WHERE object_id = OBJECT_ID(N'dbo.SlaPolicy')
    AND name = N'IX_SlaPolicy_TenantActivePriority'
)
  EXEC(N'CREATE INDEX IX_SlaPolicy_TenantActivePriority
    ON dbo.SlaPolicy(TenantId, IsActive, Priority);');

EXEC(N'MERGE dbo.SlaPolicy AS target
USING (
  SELECT
    tenant.TenantId,
    defaults.Name,
    defaults.Priority,
    defaults.ResponseMinutes,
    defaults.ResolutionMinutes
  FROM dbo.Tenant AS tenant
  CROSS JOIN (
    VALUES
      (N''Low'', N''low'', 240, 4320),
      (N''Normal'', N''normal'', 120, 1440),
      (N''High'', N''high'', 30, 480),
      (N''Urgent'', N''urgent'', 15, 120)
  ) AS defaults(Name, Priority, ResponseMinutes, ResolutionMinutes)
  WHERE tenant.Code = N''ACME''
) AS source(TenantId, Name, Priority, ResponseMinutes, ResolutionMinutes)
ON target.TenantId = source.TenantId AND target.Name = source.Name
WHEN NOT MATCHED THEN
  INSERT (
    PolicyId,
    TenantId,
    Name,
    AppliesTo,
    Targets,
    Priority,
    ResponseMinutes,
    ResolutionMinutes,
    IsActive,
    CreatedAt,
    UpdatedAt
  )
  VALUES (
    NEWID(),
    source.TenantId,
    source.Name,
    NULL,
    NULL,
    source.Priority,
    source.ResponseMinutes,
    source.ResolutionMinutes,
    1,
    SYSUTCDATETIME(),
    NULL
  );');

COMMIT TRANSACTION;
