/*
  Sprint 3 Day 3-4 upgrade for existing RT databases.

  Admin configuration audit events belong to a tenant but not to a Request,
  so Activity.RequestId must accept NULL. Permission inserts are idempotent.
*/

SET NOCOUNT ON;
SET XACT_ABORT ON;

BEGIN TRANSACTION;

IF EXISTS (
  SELECT 1
  FROM sys.columns AS c
  INNER JOIN sys.tables AS t ON t.object_id = c.object_id
  INNER JOIN sys.schemas AS s ON s.schema_id = t.schema_id
  WHERE s.name = N'dbo'
    AND t.name = N'Activity'
    AND c.name = N'RequestId'
    AND c.is_nullable = 0
)
  ALTER TABLE dbo.Activity ALTER COLUMN RequestId UNIQUEIDENTIFIER NULL;

MERGE dbo.Permission AS target
USING (
  VALUES
    (N'admin.read', N'Access tenant administration'),
    (N'admin.audit.read', N'Read tenant audit activity'),
    (N'admin.workflows', N'Manage workflows')
) AS source(Code, Description)
ON target.Code = source.Code
WHEN NOT MATCHED THEN
  INSERT (Code, Description) VALUES (source.Code, source.Description);

COMMIT TRANSACTION;
