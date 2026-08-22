/*
  Sprint 3 Day 8: tenant settings, feature flags, and notification templates.
  Safe to rerun. Existing tenant configuration is never updated.
*/
SET NOCOUNT ON;
SET XACT_ABORT ON;

BEGIN TRANSACTION;

IF OBJECT_ID(N'dbo.TenantSetting', N'U') IS NULL
BEGIN
  CREATE TABLE dbo.TenantSetting (
    TenantSettingId UNIQUEIDENTIFIER NOT NULL CONSTRAINT DF_TenantSettingId DEFAULT NEWSEQUENTIALID(),
    TenantId UNIQUEIDENTIFIER NOT NULL,
    [Key] NVARCHAR(100) NOT NULL,
    [Value] NVARCHAR(MAX) NULL,
    ValueType NVARCHAR(30) NOT NULL,
    IsSensitive BIT NOT NULL CONSTRAINT DF_TenantSetting_IsSensitive DEFAULT(0),
    UpdatedAt DATETIME2(3) NOT NULL CONSTRAINT DF_TenantSetting_UpdatedAt DEFAULT SYSUTCDATETIME(),
    UpdatedById UNIQUEIDENTIFIER NULL,
    CONSTRAINT PK_TenantSetting PRIMARY KEY CLUSTERED (TenantSettingId),
    CONSTRAINT UQ_TenantSetting_TenantKey UNIQUE (TenantId, [Key]),
    CONSTRAINT CK_TenantSetting_ValueType CHECK (ValueType IN (N'string', N'integer', N'boolean', N'url', N'timezone', N'email')),
    CONSTRAINT FK_TenantSetting_Tenant FOREIGN KEY (TenantId) REFERENCES dbo.Tenant(TenantId) ON DELETE NO ACTION,
    CONSTRAINT FK_TenantSetting_UpdatedBy FOREIGN KEY (UpdatedById) REFERENCES dbo.[User](UserId) ON DELETE NO ACTION
  );
END;

IF OBJECT_ID(N'dbo.FeatureFlag', N'U') IS NULL
BEGIN
  CREATE TABLE dbo.FeatureFlag (
    FeatureFlagId UNIQUEIDENTIFIER NOT NULL CONSTRAINT DF_FeatureFlagId DEFAULT NEWSEQUENTIALID(),
    TenantId UNIQUEIDENTIFIER NOT NULL,
    [Key] NVARCHAR(100) NOT NULL,
    Enabled BIT NOT NULL CONSTRAINT DF_FeatureFlag_Enabled DEFAULT(0),
    Description NVARCHAR(500) NULL,
    UpdatedAt DATETIME2(3) NOT NULL CONSTRAINT DF_FeatureFlag_UpdatedAt DEFAULT SYSUTCDATETIME(),
    UpdatedById UNIQUEIDENTIFIER NULL,
    CONSTRAINT PK_FeatureFlag PRIMARY KEY CLUSTERED (FeatureFlagId),
    CONSTRAINT UQ_FeatureFlag_TenantKey UNIQUE (TenantId, [Key]),
    CONSTRAINT FK_FeatureFlag_Tenant FOREIGN KEY (TenantId) REFERENCES dbo.Tenant(TenantId) ON DELETE NO ACTION,
    CONSTRAINT FK_FeatureFlag_UpdatedBy FOREIGN KEY (UpdatedById) REFERENCES dbo.[User](UserId) ON DELETE NO ACTION
  );
END;

IF OBJECT_ID(N'dbo.NotificationTemplate', N'U') IS NULL
BEGIN
  CREATE TABLE dbo.NotificationTemplate (
    NotificationTemplateId UNIQUEIDENTIFIER NOT NULL CONSTRAINT DF_NotificationTemplateId DEFAULT NEWSEQUENTIALID(),
    TenantId UNIQUEIDENTIFIER NOT NULL,
    EventType NVARCHAR(100) NOT NULL,
    SubjectTemplate NVARCHAR(500) NOT NULL,
    BodyTemplate NVARCHAR(MAX) NOT NULL,
    IsActive BIT NOT NULL CONSTRAINT DF_NotificationTemplate_IsActive DEFAULT(1),
    UpdatedAt DATETIME2(3) NOT NULL CONSTRAINT DF_NotificationTemplate_UpdatedAt DEFAULT SYSUTCDATETIME(),
    UpdatedById UNIQUEIDENTIFIER NULL,
    CONSTRAINT PK_NotificationTemplate PRIMARY KEY CLUSTERED (NotificationTemplateId),
    CONSTRAINT UQ_NotificationTemplate_TenantEvent UNIQUE (TenantId, EventType),
    CONSTRAINT CK_NotificationTemplate_EventType CHECK (EventType IN (N'request.created', N'request.assigned', N'comment.added', N'request.closed')),
    CONSTRAINT FK_NotificationTemplate_Tenant FOREIGN KEY (TenantId) REFERENCES dbo.Tenant(TenantId) ON DELETE NO ACTION,
    CONSTRAINT FK_NotificationTemplate_UpdatedBy FOREIGN KEY (UpdatedById) REFERENCES dbo.[User](UserId) ON DELETE NO ACTION
  );
END;

MERGE dbo.TenantSetting AS target
USING (
  SELECT tenant.TenantId, defaults.[Key], defaults.[Value], defaults.ValueType
  FROM dbo.Tenant AS tenant
  CROSS JOIN (
    VALUES
      (N'web_base_url', N'http://127.0.0.1:5173', N'url'),
      (N'default_timezone', N'America/El_Salvador', N'timezone'),
      (N'default_page_size', N'20', N'integer'),
      (N'email_from', N'rt-api@localhost', N'email')
  ) AS defaults([Key], [Value], ValueType)
  WHERE tenant.Code = N'ACME'
) AS source(TenantId, [Key], [Value], ValueType)
ON target.TenantId = source.TenantId AND target.[Key] = source.[Key]
WHEN NOT MATCHED THEN
  INSERT (TenantSettingId, TenantId, [Key], [Value], ValueType, IsSensitive, UpdatedAt, UpdatedById)
  VALUES (NEWID(), source.TenantId, source.[Key], source.[Value], source.ValueType, 0, SYSUTCDATETIME(), NULL);

MERGE dbo.FeatureFlag AS target
USING (
  SELECT tenant.TenantId, defaults.[Key], defaults.Description
  FROM dbo.Tenant AS tenant
  CROSS JOIN (
    VALUES
      (N'adminConsole', N'Enable the administration console'),
      (N'slaEnabled', N'Enable SLA administration and reporting'),
      (N'exportsEnabled', N'Enable request exports'),
      (N'notificationTemplates', N'Enable tenant notification templates')
  ) AS defaults([Key], Description)
  WHERE tenant.Code = N'ACME'
) AS source(TenantId, [Key], Description)
ON target.TenantId = source.TenantId AND target.[Key] = source.[Key]
WHEN NOT MATCHED THEN
  INSERT (FeatureFlagId, TenantId, [Key], Enabled, Description, UpdatedAt, UpdatedById)
  VALUES (NEWID(), source.TenantId, source.[Key], 1, source.Description, SYSUTCDATETIME(), NULL);

MERGE dbo.NotificationTemplate AS target
USING (
  SELECT tenant.TenantId, defaults.EventType, defaults.SubjectTemplate, defaults.BodyTemplate
  FROM dbo.Tenant AS tenant
  CROSS JOIN (
    VALUES
      (N'request.created', N'Request created: {human_id}', N'A request was created.' + CHAR(13) + CHAR(10) + N'Human ID: {human_id}' + CHAR(13) + CHAR(10) + N'Title: {title}' + CHAR(13) + CHAR(10) + N'Request ID: {request_id}' + CHAR(13) + CHAR(10) + N'Link: {request_url}'),
      (N'request.assigned', N'Request assigned: {human_id}', N'A request was assigned.' + CHAR(13) + CHAR(10) + N'Human ID: {human_id}' + CHAR(13) + CHAR(10) + N'Title: {title}' + CHAR(13) + CHAR(10) + N'Request ID: {request_id}' + CHAR(13) + CHAR(10) + N'Link: {request_url}'),
      (N'comment.added', N'Comment added: {human_id}', N'A comment was added.' + CHAR(13) + CHAR(10) + N'Human ID: {human_id}' + CHAR(13) + CHAR(10) + N'Title: {title}' + CHAR(13) + CHAR(10) + N'Request ID: {request_id}' + CHAR(13) + CHAR(10) + N'Link: {request_url}'),
      (N'request.closed', N'Request closed: {human_id}', N'A request was closed.' + CHAR(13) + CHAR(10) + N'Human ID: {human_id}' + CHAR(13) + CHAR(10) + N'Title: {title}' + CHAR(13) + CHAR(10) + N'Request ID: {request_id}' + CHAR(13) + CHAR(10) + N'Link: {request_url}')
  ) AS defaults(EventType, SubjectTemplate, BodyTemplate)
  WHERE tenant.Code = N'ACME'
) AS source(TenantId, EventType, SubjectTemplate, BodyTemplate)
ON target.TenantId = source.TenantId AND target.EventType = source.EventType
WHEN NOT MATCHED THEN
  INSERT (NotificationTemplateId, TenantId, EventType, SubjectTemplate, BodyTemplate, IsActive, UpdatedAt, UpdatedById)
  VALUES (NEWID(), source.TenantId, source.EventType, source.SubjectTemplate, source.BodyTemplate, 1, SYSUTCDATETIME(), NULL);

COMMIT TRANSACTION;
