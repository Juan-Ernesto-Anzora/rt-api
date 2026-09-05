SELECT
  N'ExpectedTables' AS CheckName,
  COUNT(*) AS ActualCount,
  18 AS ExpectedCount
FROM sys.tables
WHERE name IN (
  N'Tenant', N'User', N'Membership', N'MembershipRole', N'Role',
  N'Permission', N'RolePermission', N'Flow', N'Status', N'Transition',
  N'Request', N'Comment', N'Attachment', N'Activity', N'SlaPolicy',
  N'TenantSetting', N'FeatureFlag', N'NotificationTemplate'
);

SELECT
  N'SlaPolicyRequiredColumns' AS CheckName,
  COUNT(*) AS ActualCount,
  11 AS ExpectedCount
FROM sys.columns
WHERE object_id = OBJECT_ID(N'dbo.SlaPolicy')
  AND name IN (
    N'PolicyId', N'TenantId', N'Name', N'AppliesTo', N'Targets', N'CreatedAt',
    N'Priority', N'ResponseMinutes', N'ResolutionMinutes', N'IsActive', N'UpdatedAt'
  );

SELECT Code
FROM dbo.Permission
ORDER BY Code;

SELECT
  tenant.Code AS TenantCode,
  role.Name AS RoleName,
  COUNT(DISTINCT membership_role.MembershipId) AS MembershipCount,
  COUNT(DISTINCT role_permission.PermissionCode) AS PermissionCount
FROM dbo.Tenant AS tenant
JOIN dbo.Role AS role ON role.TenantId = tenant.TenantId
LEFT JOIN dbo.MembershipRole AS membership_role ON membership_role.RoleId = role.RoleId
LEFT JOIN dbo.RolePermission AS role_permission ON role_permission.RoleId = role.RoleId
WHERE role.Name IN (N'RT Admin', N'RT Manager', N'RT Agent', N'RT Requester', N'RT Viewer')
GROUP BY tenant.Code, role.Name
ORDER BY tenant.Code, role.Name;

SELECT N'DuplicateTenantCode' AS CheckName, COUNT(*) AS ViolationCount
FROM (SELECT Code FROM dbo.Tenant GROUP BY Code HAVING COUNT(*) > 1) AS duplicate_rows
UNION ALL
SELECT N'DuplicateMembership', COUNT(*)
FROM (SELECT TenantId, UserId FROM dbo.Membership GROUP BY TenantId, UserId HAVING COUNT(*) > 1) AS duplicate_rows
UNION ALL
SELECT N'DuplicateRole', COUNT(*)
FROM (SELECT TenantId, Name FROM dbo.Role GROUP BY TenantId, Name HAVING COUNT(*) > 1) AS duplicate_rows
UNION ALL
SELECT N'DuplicateMembershipRole', COUNT(*)
FROM (SELECT MembershipId, RoleId FROM dbo.MembershipRole GROUP BY MembershipId, RoleId HAVING COUNT(*) > 1) AS duplicate_rows
UNION ALL
SELECT N'DuplicateRolePermission', COUNT(*)
FROM (SELECT RoleId, PermissionCode FROM dbo.RolePermission GROUP BY RoleId, PermissionCode HAVING COUNT(*) > 1) AS duplicate_rows
UNION ALL
SELECT N'DuplicateSlaPolicy', COUNT(*)
FROM (SELECT TenantId, Name FROM dbo.SlaPolicy GROUP BY TenantId, Name HAVING COUNT(*) > 1) AS duplicate_rows
UNION ALL
SELECT N'DuplicateTenantSetting', COUNT(*)
FROM (SELECT TenantId, [Key] FROM dbo.TenantSetting GROUP BY TenantId, [Key] HAVING COUNT(*) > 1) AS duplicate_rows
UNION ALL
SELECT N'DuplicateFeatureFlag', COUNT(*)
FROM (SELECT TenantId, [Key] FROM dbo.FeatureFlag GROUP BY TenantId, [Key] HAVING COUNT(*) > 1) AS duplicate_rows
UNION ALL
SELECT N'DuplicateNotificationTemplate', COUNT(*)
FROM (SELECT TenantId, EventType FROM dbo.NotificationTemplate GROUP BY TenantId, EventType HAVING COUNT(*) > 1) AS duplicate_rows;

SELECT N'StatusFlowTenantMismatch' AS CheckName, COUNT(*) AS ViolationCount
FROM dbo.Status AS status_row
JOIN dbo.Flow AS flow ON flow.FlowId = status_row.FlowId
WHERE status_row.TenantId <> flow.TenantId
UNION ALL
SELECT N'RequestFlowTenantMismatch', COUNT(*)
FROM dbo.Request AS request_row
JOIN dbo.Flow AS flow ON flow.FlowId = request_row.FlowId
WHERE request_row.TenantId <> flow.TenantId
UNION ALL
SELECT N'RequestStatusTenantOrFlowMismatch', COUNT(*)
FROM dbo.Request AS request_row
JOIN dbo.Status AS status_row ON status_row.StatusId = request_row.StatusId
WHERE request_row.TenantId <> status_row.TenantId OR request_row.FlowId <> status_row.FlowId
UNION ALL
SELECT N'TransitionFlowMismatch', COUNT(*)
FROM dbo.Transition AS transition_row
JOIN dbo.Status AS from_status ON from_status.StatusId = transition_row.FromStatusId
JOIN dbo.Status AS to_status ON to_status.StatusId = transition_row.ToStatusId
WHERE transition_row.FlowId <> from_status.FlowId OR transition_row.FlowId <> to_status.FlowId
UNION ALL
SELECT N'MembershipRoleTenantMismatch', COUNT(*)
FROM dbo.MembershipRole AS membership_role
JOIN dbo.Membership AS membership ON membership.MembershipId = membership_role.MembershipId
JOIN dbo.Role AS role ON role.RoleId = membership_role.RoleId
WHERE membership.TenantId <> role.TenantId
UNION ALL
SELECT N'CommentTenantMismatch', COUNT(*)
FROM dbo.Comment AS comment_row
JOIN dbo.Request AS request_row ON request_row.RequestId = comment_row.RequestId
WHERE comment_row.TenantId <> request_row.TenantId
UNION ALL
SELECT N'AttachmentTenantMismatch', COUNT(*)
FROM dbo.Attachment AS attachment
JOIN dbo.Request AS request_row ON request_row.RequestId = attachment.RequestId
WHERE attachment.TenantId <> request_row.TenantId
UNION ALL
SELECT N'ActivityTenantMismatch', COUNT(*)
FROM dbo.Activity AS activity
JOIN dbo.Request AS request_row ON request_row.RequestId = activity.RequestId
WHERE activity.RequestId IS NOT NULL AND activity.TenantId <> request_row.TenantId;

SELECT
  table_row.name AS TableName,
  index_row.name AS IndexName,
  index_row.is_unique,
  index_row.is_primary_key
FROM sys.tables AS table_row
JOIN sys.indexes AS index_row ON index_row.object_id = table_row.object_id
WHERE index_row.name IN (
  N'IX_Request_Tenant', N'IX_Request_Status', N'IX_Request_Assignee',
  N'IX_Request_Updated', N'IX_Comment_Request', N'IX_Comment_Created',
  N'IX_Attachment_Request', N'IX_Activity_Request',
  N'IX_Activity_TenantCreated', N'IX_Membership_Tenant',
  N'UQ_Role_TenantName', N'IX_SlaPolicy_TenantActivePriority',
  N'UQ_TenantSetting_TenantKey', N'UQ_FeatureFlag_TenantKey',
  N'UQ_NotificationTemplate_TenantEvent'
)
ORDER BY table_row.name, index_row.name;

SELECT
  OBJECT_NAME(fulltext_index.object_id) AS TableName,
  fulltext_index.change_tracking_state_desc AS ChangeTracking
FROM sys.fulltext_indexes AS fulltext_index
WHERE OBJECT_NAME(fulltext_index.object_id) IN (N'Request', N'Comment', N'Attachment')
ORDER BY TableName;

SELECT tenant.Code AS TenantCode, COUNT(*) AS SlaPolicyCount
FROM dbo.SlaPolicy AS policy
JOIN dbo.Tenant AS tenant ON tenant.TenantId = policy.TenantId
GROUP BY tenant.Code
ORDER BY tenant.Code;

SELECT tenant.Code AS TenantCode, setting.[Key], setting.ValueType, setting.IsSensitive
FROM dbo.TenantSetting AS setting
JOIN dbo.Tenant AS tenant ON tenant.TenantId = setting.TenantId
ORDER BY tenant.Code, setting.[Key];

SELECT tenant.Code AS TenantCode, flag.[Key], flag.Enabled
FROM dbo.FeatureFlag AS flag
JOIN dbo.Tenant AS tenant ON tenant.TenantId = flag.TenantId
ORDER BY tenant.Code, flag.[Key];

SELECT tenant.Code AS TenantCode, template.EventType, template.IsActive
FROM dbo.NotificationTemplate AS template
JOIN dbo.Tenant AS tenant ON tenant.TenantId = template.TenantId
ORDER BY tenant.Code, template.EventType;
