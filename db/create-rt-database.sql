/*
  Request Tracker — Database Bootstrap (SQL Server)
  See previous message for details.
*/

IF DB_ID(N'rt') IS NULL
BEGIN
  CREATE DATABASE [rt]
    COLLATE Latin1_General_100_CI_AS_SC_UTF8;
END
GO
USE [rt];
GO

IF OBJECT_ID('dbo.utc_now', 'FN') IS NOT NULL DROP FUNCTION dbo.utc_now;
GO
CREATE FUNCTION dbo.utc_now() RETURNS DATETIME2(3) AS
BEGIN
  RETURN SYSUTCDATETIME();
END
GO

-- Tenants
IF OBJECT_ID('dbo.Tenant','U') IS NOT NULL DROP TABLE dbo.Tenant;
CREATE TABLE dbo.Tenant (
  TenantId UNIQUEIDENTIFIER NOT NULL CONSTRAINT DF_TenantId DEFAULT NEWSEQUENTIALID(),
  Code NVARCHAR(32) NOT NULL,
  Name NVARCHAR(200) NOT NULL,
  IsActive BIT NOT NULL CONSTRAINT DF_Tenant_IsActive DEFAULT(1),
  CreatedAt DATETIME2(3) NOT NULL CONSTRAINT DF_Tenant_CreatedAt DEFAULT dbo.utc_now(),
  UpdatedAt DATETIME2(3) NULL,
  CONSTRAINT PK_Tenant PRIMARY KEY CLUSTERED (TenantId),
  CONSTRAINT UQ_Tenant_Code UNIQUE (Code)
);

-- Users
IF OBJECT_ID('dbo.[User]','U') IS NOT NULL DROP TABLE dbo.[User];
CREATE TABLE dbo.[User] (
  UserId UNIQUEIDENTIFIER NOT NULL CONSTRAINT DF_UserId DEFAULT NEWSEQUENTIALID(),
  Email NVARCHAR(320) NOT NULL,
  DisplayName NVARCHAR(200) NOT NULL,
  EmployeeCode NVARCHAR(50) NULL,
  AvatarUrl NVARCHAR(400) NULL,
  IsActive BIT NOT NULL CONSTRAINT DF_User_IsActive DEFAULT(1),
  CreatedAt DATETIME2(3) NOT NULL CONSTRAINT DF_User_CreatedAt DEFAULT dbo.utc_now(),
  UpdatedAt DATETIME2(3) NULL,
  CONSTRAINT PK_User PRIMARY KEY CLUSTERED (UserId),
  CONSTRAINT UQ_User_Email UNIQUE (Email)
);

-- Membership
IF OBJECT_ID('dbo.Membership','U') IS NOT NULL DROP TABLE dbo.Membership;
CREATE TABLE dbo.Membership (
  MembershipId UNIQUEIDENTIFIER NOT NULL CONSTRAINT DF_MembershipId DEFAULT NEWSEQUENTIALID(),
  TenantId UNIQUEIDENTIFIER NOT NULL,
  UserId UNIQUEIDENTIFIER NOT NULL,
  IsDefaultTenant BIT NOT NULL CONSTRAINT DF_Membership_Default DEFAULT(0),
  CreatedAt DATETIME2(3) NOT NULL CONSTRAINT DF_Membership_CreatedAt DEFAULT dbo.utc_now(),
  CONSTRAINT PK_Membership PRIMARY KEY CLUSTERED (MembershipId),
  CONSTRAINT UQ_Membership_TenantUser UNIQUE (TenantId, UserId),
  CONSTRAINT FK_Membership_Tenant FOREIGN KEY (TenantId) REFERENCES dbo.Tenant(TenantId) ON DELETE CASCADE,
  CONSTRAINT FK_Membership_User   FOREIGN KEY (UserId)   REFERENCES dbo.[User](UserId) ON DELETE CASCADE
);
CREATE INDEX IX_Membership_User ON dbo.Membership(UserId);
CREATE INDEX IX_Membership_Tenant ON dbo.Membership(TenantId);

-- Role
IF OBJECT_ID('dbo.[Role]','U') IS NOT NULL DROP TABLE dbo.[Role];
CREATE TABLE dbo.[Role] (
  RoleId UNIQUEIDENTIFIER NOT NULL CONSTRAINT DF_RoleId DEFAULT NEWSEQUENTIALID(),
  TenantId UNIQUEIDENTIFIER NOT NULL,
  Name NVARCHAR(100) NOT NULL,
  Description NVARCHAR(400) NULL,
  CreatedAt DATETIME2(3) NOT NULL CONSTRAINT DF_Role_CreatedAt DEFAULT dbo.utc_now(),
  CONSTRAINT PK_Role PRIMARY KEY CLUSTERED (RoleId),
  CONSTRAINT UQ_Role_TenantName UNIQUE (TenantId, Name),
  CONSTRAINT FK_Role_Tenant FOREIGN KEY (TenantId) REFERENCES dbo.Tenant(TenantId) ON DELETE CASCADE
);

-- Permission
IF OBJECT_ID('dbo.Permission','U') IS NOT NULL DROP TABLE dbo.Permission;
CREATE TABLE dbo.Permission (
  Code NVARCHAR(100) NOT NULL,
  Description NVARCHAR(400) NULL,
  CONSTRAINT PK_Permission PRIMARY KEY (Code)
);

-- RolePermission
IF OBJECT_ID('dbo.RolePermission','U') IS NOT NULL DROP TABLE dbo.RolePermission;
CREATE TABLE dbo.RolePermission (
  RoleId UNIQUEIDENTIFIER NOT NULL,
  PermissionCode NVARCHAR(100) NOT NULL,
  CONSTRAINT PK_RolePermission PRIMARY KEY (RoleId, PermissionCode),
  CONSTRAINT FK_RolePermission_Role FOREIGN KEY (RoleId) REFERENCES dbo.[Role](RoleId) ON DELETE CASCADE,
  CONSTRAINT FK_RolePermission_Perm FOREIGN KEY (PermissionCode) REFERENCES dbo.Permission(Code) ON DELETE CASCADE
);

-- MembershipRole
IF OBJECT_ID('dbo.MembershipRole','U') IS NOT NULL DROP TABLE dbo.MembershipRole;
CREATE TABLE dbo.MembershipRole (
  MembershipId UNIQUEIDENTIFIER NOT NULL,
  RoleId UNIQUEIDENTIFIER NOT NULL,
  CONSTRAINT PK_MembershipRole PRIMARY KEY (MembershipId, RoleId),
  CONSTRAINT FK_MembershipRole_M FOREIGN KEY (MembershipId) REFERENCES dbo.Membership(MembershipId) ON DELETE CASCADE,
  CONSTRAINT FK_MembershipRole_R FOREIGN KEY (RoleId) REFERENCES dbo.[Role](RoleId) ON DELETE CASCADE
);

-- Flow
IF OBJECT_ID('dbo.Flow','U') IS NOT NULL DROP TABLE dbo.Flow;
CREATE TABLE dbo.Flow (
  FlowId UNIQUEIDENTIFIER NOT NULL CONSTRAINT DF_FlowId DEFAULT NEWSEQUENTIALID(),
  TenantId UNIQUEIDENTIFIER NOT NULL,
  Name NVARCHAR(100) NOT NULL,
  Description NVARCHAR(400) NULL,
  CreatedAt DATETIME2(3) NOT NULL CONSTRAINT DF_Flow_CreatedAt DEFAULT dbo.utc_now(),
  CONSTRAINT PK_Flow PRIMARY KEY CLUSTERED (FlowId),
  CONSTRAINT UQ_Flow_TenantName UNIQUE (TenantId, Name),
  CONSTRAINT FK_Flow_Tenant FOREIGN KEY (TenantId) REFERENCES dbo.Tenant(TenantId) ON DELETE CASCADE
);

-- Status
IF OBJECT_ID('dbo.[Status]','U') IS NOT NULL DROP TABLE dbo.[Status];
CREATE TABLE dbo.[Status] (
  StatusId UNIQUEIDENTIFIER NOT NULL CONSTRAINT DF_StatusId DEFAULT NEWSEQUENTIALID(),
  TenantId UNIQUEIDENTIFIER NOT NULL,
  FlowId UNIQUEIDENTIFIER NOT NULL,
  Name NVARCHAR(50) NOT NULL,
  Category NVARCHAR(20) NOT NULL,
  IsTerminal BIT NOT NULL CONSTRAINT DF_Status_Term DEFAULT(0),
  CreatedAt DATETIME2(3) NOT NULL CONSTRAINT DF_Status_CreatedAt DEFAULT dbo.utc_now(),
  CONSTRAINT PK_Status PRIMARY KEY CLUSTERED (StatusId),
  CONSTRAINT FK_Status_Tenant FOREIGN KEY (TenantId) REFERENCES dbo.Tenant(TenantId) ON DELETE CASCADE,
  CONSTRAINT FK_Status_Flow FOREIGN KEY (FlowId) REFERENCES dbo.Flow(FlowId) ON DELETE CASCADE,
  CONSTRAINT CK_Status_Category CHECK (Category IN (N'open', N'in_progress', N'waiting', N'closed'))
);
CREATE INDEX IX_Status_Flow ON dbo.[Status](FlowId);

-- Transition
IF OBJECT_ID('dbo.Transition','U') IS NOT NULL DROP TABLE dbo.Transition;
CREATE TABLE dbo.Transition (
  TransitionId UNIQUEIDENTIFIER NOT NULL CONSTRAINT DF_TransitionId DEFAULT NEWSEQUENTIALID(),
  FlowId UNIQUEIDENTIFIER NOT NULL,
  FromStatusId UNIQUEIDENTIFIER NOT NULL,
  ToStatusId UNIQUEIDENTIFIER NOT NULL,
  GuardRolesJson NVARCHAR(MAX) NULL,
  GuardPermsJson NVARCHAR(MAX) NULL,
  AutoRules NVARCHAR(MAX) NULL,
  CreatedAt DATETIME2(3) NOT NULL CONSTRAINT DF_Transition_CreatedAt DEFAULT dbo.utc_now(),
  CONSTRAINT PK_Transition PRIMARY KEY CLUSTERED (TransitionId),
  CONSTRAINT FK_Transition_Flow FOREIGN KEY (FlowId) REFERENCES dbo.Flow(FlowId) ON DELETE CASCADE,
  CONSTRAINT FK_Transition_From FOREIGN KEY (FromStatusId) REFERENCES dbo.[Status](StatusId) ON DELETE CASCADE,
  CONSTRAINT FK_Transition_To FOREIGN KEY (ToStatusId) REFERENCES dbo.[Status](StatusId) ON DELETE CASCADE
);
CREATE INDEX IX_Transition_From ON dbo.Transition(FromStatusId);
CREATE INDEX IX_Transition_To ON dbo.Transition(ToStatusId);

-- Request
IF OBJECT_ID('dbo.Request','U') IS NOT NULL DROP TABLE dbo.Request;
CREATE TABLE dbo.Request (
  RequestId UNIQUEIDENTIFIER NOT NULL CONSTRAINT DF_RequestId DEFAULT NEWSEQUENTIALID(),
  TenantId UNIQUEIDENTIFIER NOT NULL,
  HumanId NVARCHAR(40) NOT NULL,
  Title NVARCHAR(200) NOT NULL,
  Description NVARCHAR(MAX) NULL,
  FlowId UNIQUEIDENTIFIER NOT NULL,
  StatusId UNIQUEIDENTIFIER NOT NULL,
  Priority NVARCHAR(20) NOT NULL CONSTRAINT DF_Request_Priority DEFAULT(N'normal'),
  RequesterId UNIQUEIDENTIFIER NOT NULL,
  AssigneeId UNIQUEIDENTIFIER NULL,
  CustomFields NVARCHAR(MAX) NULL,
  DueAt DATETIME2(3) NULL,
  CreatedAt DATETIME2(3) NOT NULL CONSTRAINT DF_Request_CreatedAt DEFAULT dbo.utc_now(),
  UpdatedAt DATETIME2(3) NOT NULL CONSTRAINT DF_Request_UpdatedAt DEFAULT dbo.utc_now(),
  RowVer ROWVERSION,
  CONSTRAINT PK_Request PRIMARY KEY CLUSTERED (RequestId),
  CONSTRAINT UQ_Request_HumanId UNIQUE (TenantId, HumanId),
  CONSTRAINT CK_Request_Priority CHECK (Priority IN (N'low', N'normal', N'high', N'urgent')),
  CONSTRAINT FK_Request_Tenant FOREIGN KEY (TenantId) REFERENCES dbo.Tenant(TenantId) ON DELETE CASCADE,
  CONSTRAINT FK_Request_Flow FOREIGN KEY (FlowId) REFERENCES dbo.Flow(FlowId),
  CONSTRAINT FK_Request_Status FOREIGN KEY (StatusId) REFERENCES dbo.[Status](StatusId),
  CONSTRAINT FK_Request_Requester FOREIGN KEY (RequesterId) REFERENCES dbo.[User](UserId),
  CONSTRAINT FK_Request_Assignee FOREIGN KEY (AssigneeId) REFERENCES dbo.[User](UserId)
);
CREATE INDEX IX_Request_Tenant ON dbo.Request(TenantId);
CREATE INDEX IX_Request_Status ON dbo.Request(StatusId);
CREATE INDEX IX_Request_Assignee ON dbo.Request(AssigneeId);
CREATE INDEX IX_Request_Updated ON dbo.Request(UpdatedAt);

-- Comment
IF OBJECT_ID('dbo.Comment','U') IS NOT NULL DROP TABLE dbo.Comment;
CREATE TABLE dbo.Comment (
  CommentId UNIQUEIDENTIFIER NOT NULL CONSTRAINT DF_CommentId DEFAULT NEWSEQUENTIALID(),
  TenantId UNIQUEIDENTIFIER NOT NULL,
  RequestId UNIQUEIDENTIFIER NOT NULL,
  AuthorId UNIQUEIDENTIFIER NOT NULL,
  GroupId UNIQUEIDENTIFIER NULL,
  MessageMd NVARCHAR(MAX) NOT NULL,
  Visibility NVARCHAR(10) NOT NULL CONSTRAINT DF_Comment_Vis DEFAULT(N'public'),
  CreatedAt DATETIME2(3) NOT NULL CONSTRAINT DF_Comment_CreatedAt DEFAULT dbo.utc_now(),
  CONSTRAINT PK_Comment PRIMARY KEY CLUSTERED (CommentId),
  CONSTRAINT CK_Comment_Visibility CHECK (Visibility IN (N'public', N'internal')),
  CONSTRAINT FK_Comment_Tenant FOREIGN KEY (TenantId) REFERENCES dbo.Tenant(TenantId) ON DELETE CASCADE,
  CONSTRAINT FK_Comment_Request FOREIGN KEY (RequestId) REFERENCES dbo.Request(RequestId) ON DELETE CASCADE,
  CONSTRAINT FK_Comment_Author FOREIGN KEY (AuthorId) REFERENCES dbo.[User](UserId)
);
CREATE INDEX IX_Comment_Request ON dbo.Comment(RequestId);
CREATE INDEX IX_Comment_Created ON dbo.Comment(CreatedAt);

-- Attachment
IF OBJECT_ID('dbo.Attachment','U') IS NOT NULL DROP TABLE dbo.Attachment;
CREATE TABLE dbo.Attachment (
  AttachmentId UNIQUEIDENTIFIER NOT NULL CONSTRAINT DF_AttachmentId DEFAULT NEWSEQUENTIALID(),
  TenantId UNIQUEIDENTIFIER NOT NULL,
  RequestId UNIQUEIDENTIFIER NOT NULL,
  CommentId UNIQUEIDENTIFIER NULL,
  GroupId UNIQUEIDENTIFIER NULL,
  Filename NVARCHAR(255) NOT NULL,
  ContentType NVARCHAR(100) NULL,
  SizeBytes BIGINT NULL,
  StorageUrl NVARCHAR(500) NOT NULL,
  Checksum NVARCHAR(128) NULL,
  ScanStatus NVARCHAR(20) NULL,
  CreatedAt DATETIME2(3) NOT NULL CONSTRAINT DF_Attachment_CreatedAt DEFAULT dbo.utc_now(),
  CONSTRAINT PK_Attachment PRIMARY KEY CLUSTERED (AttachmentId),
  CONSTRAINT FK_Attachment_Tenant FOREIGN KEY (TenantId) REFERENCES dbo.Tenant(TenantId) ON DELETE CASCADE,
  CONSTRAINT FK_Attachment_Request FOREIGN KEY (RequestId) REFERENCES dbo.Request(RequestId) ON DELETE CASCADE,
  CONSTRAINT FK_Attachment_Comment FOREIGN KEY (CommentId) REFERENCES dbo.Comment(CommentId)
);
CREATE INDEX IX_Attachment_Request ON dbo.Attachment(RequestId);

-- Activity
IF OBJECT_ID('dbo.Activity','U') IS NOT NULL DROP TABLE dbo.Activity;
CREATE TABLE dbo.Activity (
  ActivityId UNIQUEIDENTIFIER NOT NULL CONSTRAINT DF_ActivityId DEFAULT NEWSEQUENTIALID(),
  TenantId UNIQUEIDENTIFIER NOT NULL,
  RequestId UNIQUEIDENTIFIER NOT NULL,
  ActorId UNIQUEIDENTIFIER NULL,
  Type NVARCHAR(50) NOT NULL,
  Payload NVARCHAR(MAX) NULL,
  CreatedAt DATETIME2(3) NOT NULL CONSTRAINT DF_Activity_CreatedAt DEFAULT dbo.utc_now(),
  CONSTRAINT PK_Activity PRIMARY KEY CLUSTERED (ActivityId),
  CONSTRAINT FK_Activity_Tenant FOREIGN KEY (TenantId) REFERENCES dbo.Tenant(TenantId) ON DELETE CASCADE,
  CONSTRAINT FK_Activity_Request FOREIGN KEY (RequestId) REFERENCES dbo.Request(RequestId) ON DELETE CASCADE,
  CONSTRAINT FK_Activity_Actor FOREIGN KEY (ActorId) REFERENCES dbo.[User](UserId)
);
CREATE INDEX IX_Activity_Request ON dbo.Activity(RequestId);

-- Tag & junction
IF OBJECT_ID('dbo.Tag','U') IS NOT NULL DROP TABLE dbo.Tag;
CREATE TABLE dbo.Tag (
  TagId UNIQUEIDENTIFIER NOT NULL CONSTRAINT DF_TagId DEFAULT NEWSEQUENTIALID(),
  TenantId UNIQUEIDENTIFIER NOT NULL,
  Name NVARCHAR(50) NOT NULL,
  CONSTRAINT PK_Tag PRIMARY KEY CLUSTERED (TagId),
  CONSTRAINT UQ_Tag_TenantName UNIQUE (TenantId, Name),
  CONSTRAINT FK_Tag_Tenant FOREIGN KEY (TenantId) REFERENCES dbo.Tenant(TenantId) ON DELETE CASCADE
);

IF OBJECT_ID('dbo.RequestTag','U') IS NOT NULL DROP TABLE dbo.RequestTag;
CREATE TABLE dbo.RequestTag (
  RequestId UNIQUEIDENTIFIER NOT NULL,
  TagId UNIQUEIDENTIFIER NOT NULL,
  CONSTRAINT PK_RequestTag PRIMARY KEY (RequestId, TagId),
  CONSTRAINT FK_RequestTag_R FOREIGN KEY (RequestId) REFERENCES dbo.Request(RequestId) ON DELETE CASCADE,
  CONSTRAINT FK_RequestTag_T FOREIGN KEY (TagId) REFERENCES dbo.Tag(TagId) ON DELETE CASCADE
);

-- SavedSearch
IF OBJECT_ID('dbo.SavedSearch','U') IS NOT NULL DROP TABLE dbo.SavedSearch;
CREATE TABLE dbo.SavedSearch (
  SavedSearchId UNIQUEIDENTIFIER NOT NULL CONSTRAINT DF_SavedSearchId DEFAULT NEWSEQUENTIALID(),
  TenantId UNIQUEIDENTIFIER NOT NULL,
  OwnerId UNIQUEIDENTIFIER NOT NULL,
  Name NVARCHAR(100) NOT NULL,
  QueryParams NVARCHAR(MAX) NOT NULL,
  IsShared BIT NOT NULL CONSTRAINT DF_SavedSearch_Shared DEFAULT(0),
  CreatedAt DATETIME2(3) NOT NULL CONSTRAINT DF_SavedSearch_CreatedAt DEFAULT dbo.utc_now(),
  CONSTRAINT PK_SavedSearch PRIMARY KEY CLUSTERED (SavedSearchId),
  CONSTRAINT FK_SavedSearch_Tenant FOREIGN KEY (TenantId) REFERENCES dbo.Tenant(TenantId) ON DELETE CASCADE,
  CONSTRAINT FK_SavedSearch_Owner  FOREIGN KEY (OwnerId)  REFERENCES dbo.[User](UserId)
);

-- SLA
IF OBJECT_ID('dbo.SlaPolicy','U') IS NOT NULL DROP TABLE dbo.SlaPolicy;
CREATE TABLE dbo.SlaPolicy (
  PolicyId UNIQUEIDENTIFIER NOT NULL CONSTRAINT DF_SlaPolicyId DEFAULT NEWSEQUENTIALID(),
  TenantId UNIQUEIDENTIFIER NOT NULL,
  Name NVARCHAR(100) NOT NULL,
  AppliesTo NVARCHAR(MAX) NULL,
  Targets NVARCHAR(MAX) NULL,
  CreatedAt DATETIME2(3) NOT NULL CONSTRAINT DF_SlaPolicy_CreatedAt DEFAULT dbo.utc_now(),
  CONSTRAINT PK_SlaPolicy PRIMARY KEY CLUSTERED (PolicyId),
  CONSTRAINT FK_SlaPolicy_Tenant FOREIGN KEY (TenantId) REFERENCES dbo.Tenant(TenantId) ON DELETE CASCADE
);

IF OBJECT_ID('dbo.SlaTimer','U') IS NOT NULL DROP TABLE dbo.SlaTimer;
CREATE TABLE dbo.SlaTimer (
  SlaTimerId UNIQUEIDENTIFIER NOT NULL CONSTRAINT DF_SlaTimerId DEFAULT NEWSEQUENTIALID(),
  RequestId UNIQUEIDENTIFIER NOT NULL,
  PolicyId UNIQUEIDENTIFIER NOT NULL,
  StartedAt DATETIME2(3) NOT NULL CONSTRAINT DF_SlaTimer_Started DEFAULT dbo.utc_now(),
  PausedAt DATETIME2(3) NULL,
  StoppedAt DATETIME2(3) NULL,
  BreachedAt DATETIME2(3) NULL,
  CONSTRAINT PK_SlaTimer PRIMARY KEY CLUSTERED (SlaTimerId),
  CONSTRAINT FK_SlaTimer_Request FOREIGN KEY (RequestId) REFERENCES dbo.Request(RequestId) ON DELETE CASCADE,
  CONSTRAINT FK_SlaTimer_Policy  FOREIGN KEY (PolicyId)  REFERENCES dbo.SlaPolicy(PolicyId) ON DELETE CASCADE
);

-- FTS
IF NOT EXISTS (SELECT * FROM sys.fulltext_catalogs WHERE name = 'rt_catalog')
  CREATE FULLTEXT CATALOG rt_catalog;
IF EXISTS (SELECT * FROM sys.fulltext_indexes fti JOIN sys.objects o ON fti.object_id=o.object_id WHERE o.name='Request')
  DROP FULLTEXT INDEX ON dbo.Request;
CREATE FULLTEXT INDEX ON dbo.Request ( Title LANGUAGE 1033, Description LANGUAGE 1033 )
KEY INDEX PK_Request ON rt_catalog WITH CHANGE_TRACKING AUTO;

IF EXISTS (SELECT * FROM sys.fulltext_indexes fti JOIN sys.objects o ON fti.object_id=o.object_id WHERE o.name='Comment')
  DROP FULLTEXT INDEX ON dbo.Comment;
CREATE FULLTEXT INDEX ON dbo.Comment ( MessageMd LANGUAGE 1033 )
KEY INDEX PK_Comment ON rt_catalog WITH CHANGE_TRACKING AUTO;

IF EXISTS (SELECT * FROM sys.fulltext_indexes fti JOIN sys.objects o ON fti.object_id=o.object_id WHERE o.name='Attachment')
  DROP FULLTEXT INDEX ON dbo.Attachment;
CREATE FULLTEXT INDEX ON dbo.Attachment ( Filename LANGUAGE 1033 )
KEY INDEX PK_Attachment ON rt_catalog WITH CHANGE_TRACKING AUTO;

-- Seed minimal permissions
IF NOT EXISTS (SELECT 1 FROM dbo.Permission WHERE Code='requests.read')
  INSERT INTO dbo.Permission(Code, Description) VALUES
    (N'requests.read', N'Read requests'),
    (N'requests.write', N'Create/Update requests'),
    (N'requests.transition', N'Change request status'),
    (N'comments.write', N'Add comments'),
    (N'attachments.write', N'Upload attachments'),
    (N'admin.users', N'Manage users'),
    (N'admin.workflows', N'Manage workflows');