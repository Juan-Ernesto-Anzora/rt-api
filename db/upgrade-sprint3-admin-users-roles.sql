/*
  Sprint 3 Day 5-6: additive admin permission and canonical role seed.
  Safe to rerun. Existing roles and role-permission assignments are preserved.
*/
SET NOCOUNT ON;
SET XACT_ABORT ON;

BEGIN TRANSACTION;

MERGE dbo.Permission AS target
USING (
  VALUES
    (N'admin.audit.read', N'Read tenant audit activity'),
    (N'admin.permissions', N'Manage role permissions'),
    (N'admin.read', N'Access tenant administration'),
    (N'admin.roles', N'Manage roles and role assignments'),
    (N'admin.settings', N'Manage admin settings'),
    (N'admin.users', N'Manage users'),
    (N'admin.workflows', N'Manage workflows'),
    (N'attachments.write', N'Upload attachments'),
    (N'comments.write', N'Add comments'),
    (N'featureflags.manage', N'Manage feature flags'),
    (N'notifications.manage', N'Manage notifications'),
    (N'reports.export', N'Export reports'),
    (N'reports.read', N'Read reports'),
    (N'requests.read', N'Read requests'),
    (N'requests.transition', N'Change request status'),
    (N'requests.write', N'Create/Update requests'),
    (N'sla.manage', N'Manage SLA policies'),
    (N'tenant.settings.manage', N'Manage tenant settings')
) AS source(Code, Description)
ON target.Code = source.Code
WHEN NOT MATCHED THEN
  INSERT (Code, Description) VALUES (source.Code, source.Description);

MERGE dbo.[Role] AS target
USING (
  SELECT
    tenant.TenantId,
    role_seed.Name,
    role_seed.Description
  FROM dbo.Tenant AS tenant
  CROSS JOIN (
    VALUES
      (N'RT Admin', N'Full tenant administration'),
      (N'RT Manager', N'Request management and reporting'),
      (N'RT Agent', N'Request handling'),
      (N'RT Requester', N'Request creation and collaboration'),
      (N'RT Viewer', N'Read-only request and report access')
  ) AS role_seed(Name, Description)
) AS source(TenantId, Name, Description)
ON target.TenantId = source.TenantId AND target.Name = source.Name
WHEN NOT MATCHED THEN
  INSERT (RoleId, TenantId, Name, Description, CreatedAt)
  VALUES (NEWID(), source.TenantId, source.Name, source.Description, SYSUTCDATETIME());

MERGE dbo.RolePermission AS target
USING (
  SELECT role.RoleId, permission.Code AS PermissionCode
  FROM dbo.[Role] AS role
  CROSS JOIN dbo.Permission AS permission
  WHERE role.Name = N'RT Admin'

  UNION

  SELECT role.RoleId, mapping.PermissionCode
  FROM dbo.[Role] AS role
  INNER JOIN (
    VALUES
      (N'RT Manager', N'requests.read'),
      (N'RT Manager', N'requests.write'),
      (N'RT Manager', N'requests.transition'),
      (N'RT Manager', N'comments.write'),
      (N'RT Manager', N'attachments.write'),
      (N'RT Manager', N'reports.read'),
      (N'RT Manager', N'reports.export'),
      (N'RT Manager', N'admin.read'),
      (N'RT Manager', N'admin.audit.read'),
      (N'RT Agent', N'requests.read'),
      (N'RT Agent', N'requests.write'),
      (N'RT Agent', N'requests.transition'),
      (N'RT Agent', N'comments.write'),
      (N'RT Agent', N'attachments.write'),
      (N'RT Requester', N'requests.read'),
      (N'RT Requester', N'requests.write'),
      (N'RT Requester', N'comments.write'),
      (N'RT Requester', N'attachments.write'),
      (N'RT Viewer', N'requests.read'),
      (N'RT Viewer', N'reports.read')
  ) AS mapping(RoleName, PermissionCode)
    ON role.Name = mapping.RoleName
  INNER JOIN dbo.Permission AS permission
    ON permission.Code = mapping.PermissionCode
) AS source(RoleId, PermissionCode)
ON target.RoleId = source.RoleId
  AND target.PermissionCode = source.PermissionCode
WHEN NOT MATCHED THEN
  INSERT (RoleId, PermissionCode)
  VALUES (source.RoleId, source.PermissionCode);

COMMIT TRANSACTION;
