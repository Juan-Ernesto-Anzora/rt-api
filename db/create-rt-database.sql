/*
  Request Tracker — Clean Schema for SQL Server 2022+
  Goal: avoid multiple cascade paths. We keep ONE cascade route to each leaf.
  Strategy:
    - Tenant CASCADE only to top-level roots: Flow, Request, Role, Tag, SlaPolicy, Membership.
    - Child tables cascade from their immediate parent only (e.g., Request -> Comment/Attachment/Activity CASCADE).
    - No direct Tenant CASCADE to child tables that already cascade via Request/Flow.
    - For many-to-many tables (MembershipRole, RequestTag, RolePermission): CASCADE from one side only; NO ACTION on the other.
    - No INSTEAD OF triggers needed. Deletions that would break NO ACTION must be done in app/service code beforehand.

  If you previously created any triggers named TR_* from earlier experiments, drop them first:
    IF OBJECT_ID('TR_Role_Delete','TR') IS NOT NULL DROP TRIGGER TR_Role_Delete;
*/

-- 0) Create database (UTF-8 collation). Comment if DB already exists.
IF DB_ID(N'rt') IS NULL
BEGIN
  CREATE DATABASE [rt] COLLATE Latin1_General_100_CI_AS_SC_UTF8;
END
GO
USE [rt];
GO

-- Utility function for UTC timestamps
IF OBJECT_ID('dbo.utc_now', 'FN') IS NOT NULL DROP FUNCTION dbo.utc_now;
GO
CREATE FUNCTION dbo.utc_now() RETURNS DATETIME2(3) AS
BEGIN
  RETURN SYSUTCDATETIME();
END
GO

-------------------------------------------------------------------------------
-- DROP TABLES (clean build). Comment this whole block if starting from empty DB
-------------------------------------------------------------------------------
IF OBJECT_ID('dbo.RequestTag','U') IS NOT NULL DROP TABLE dbo.RequestTag;
IF OBJECT_ID('dbo.RolePermission','U') IS NOT NULL DROP TABLE dbo.RolePermission;
IF OBJECT_ID('dbo.MembershipRole','U') IS NOT NULL DROP TABLE dbo.MembershipRole;
IF OBJECT_ID('dbo.SlaTimer','U') IS NOT NULL DROP TABLE dbo.SlaTimer;
IF OBJECT_ID('dbo.SavedSearch','U') IS NOT NULL DROP TABLE dbo.SavedSearch;
IF OBJECT_ID('dbo.Activity','U') IS NOT NULL DROP TABLE dbo.Activity;
IF OBJECT_ID('dbo.Attachment','U') IS NOT NULL DROP TABLE dbo.Attachment;
IF OBJECT_ID('dbo.Comment','U') IS NOT NULL DROP TABLE dbo.Comment;
IF OBJECT_ID('dbo.[Status]','U') IS NOT NULL DROP TABLE dbo.[Status];
IF OBJECT_ID('dbo.Transition','U') IS NOT NULL DROP TABLE dbo.Transition;
IF OBJECT_ID('dbo.Request','U') IS NOT NULL DROP TABLE dbo.Request;
IF OBJECT_ID('dbo.SlaPolicy','U') IS NOT NULL DROP TABLE dbo.SlaPolicy;
IF OBJECT_ID('dbo.Tag','U') IS NOT NULL DROP TABLE dbo.Tag;
IF OBJECT_ID('dbo.Flow','U') IS NOT NULL DROP TABLE dbo.Flow;
IF OBJECT_ID('dbo.Membership','U') IS NOT NULL DROP TABLE dbo.Membership;
IF OBJECT_ID('dbo.[Role]','U') IS NOT NULL DROP TABLE dbo.[Role];
IF OBJECT_ID('dbo.Permission','U') IS NOT NULL DROP TABLE dbo.Permission;
IF OBJECT_ID('dbo.[User]','U') IS NOT NULL DROP TABLE dbo.[User];
IF OBJECT_ID('dbo.Tenant','U') IS NOT NULL DROP TABLE dbo.Tenant;
GO

-------------------------------------------------------------------------------
-- ROOT TABLES
-------------------------------------------------------------------------------

CREATE TABLE dbo.Tenant (
  TenantId UNIQUEIDENTIFIER NOT NULL CONSTRAINT DF_TenantId DEFAULT NEWSEQUENTIALID(),
  Code      NVARCHAR(32) NOT NULL,
  Name      NVARCHAR(200) NOT NULL,
  IsActive  BIT NOT NULL CONSTRAINT DF_Tenant_IsActive DEFAULT(1),
  CreatedAt DATETIME2(3) NOT NULL CONSTRAINT DF_Tenant_CreatedAt DEFAULT dbo.utc_now(),
  UpdatedAt DATETIME2(3) NULL,
  CONSTRAINT PK_Tenant PRIMARY KEY CLUSTERED (TenantId),
  CONSTRAINT UQ_Tenant_Code UNIQUE (Code)
);

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

-- Roles are tenant-scoped root
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

-- Permissions are global (no tenant FK)
CREATE TABLE dbo.Permission (
  Code NVARCHAR(100) NOT NULL,
  Description NVARCHAR(400) NULL,
  CONSTRAINT PK_Permission PRIMARY KEY (Code)
);

-- Membership = user in tenant (root-level for cascade from Tenant and User)
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

-- Flow is root-level per tenant
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

-- Tags are root-level per tenant
CREATE TABLE dbo.Tag (
  TagId UNIQUEIDENTIFIER NOT NULL CONSTRAINT DF_TagId DEFAULT NEWSEQUENTIALID(),
  TenantId UNIQUEIDENTIFIER NOT NULL,
  Name NVARCHAR(50) NOT NULL,
  CONSTRAINT PK_Tag PRIMARY KEY CLUSTERED (TagId),
  CONSTRAINT UQ_Tag_TenantName UNIQUE (TenantId, Name),
  CONSTRAINT FK_Tag_Tenant FOREIGN KEY (TenantId) REFERENCES dbo.Tenant(TenantId) ON DELETE CASCADE
);

-- SLA policy is root-level per tenant
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

-------------------------------------------------------------------------------
-- CHILD TABLES
-------------------------------------------------------------------------------

-- Status belongs to Flow; keep TenantId (guard) but NO ACTION to avoid multi-cascade via Flow
CREATE TABLE dbo.[Status] (
  StatusId UNIQUEIDENTIFIER NOT NULL CONSTRAINT DF_StatusId DEFAULT NEWSEQUENTIALID(),
  TenantId UNIQUEIDENTIFIER NOT NULL,
  FlowId UNIQUEIDENTIFIER NOT NULL,
  Name NVARCHAR(50) NOT NULL,
  Category NVARCHAR(20) NOT NULL,
  IsTerminal BIT NOT NULL CONSTRAINT DF_Status_Term DEFAULT(0),
  CreatedAt DATETIME2(3) NOT NULL CONSTRAINT DF_Status_CreatedAt DEFAULT dbo.utc_now(),
  CONSTRAINT PK_Status PRIMARY KEY CLUSTERED (StatusId),
  CONSTRAINT FK_Status_Tenant FOREIGN KEY (TenantId) REFERENCES dbo.Tenant(TenantId) ON DELETE NO ACTION,
  CONSTRAINT FK_Status_Flow   FOREIGN KEY (FlowId)   REFERENCES dbo.Flow(FlowId) ON DELETE CASCADE,
  CONSTRAINT CK_Status_Category CHECK (Category IN (N'open', N'in_progress', N'waiting', N'closed'))
);
CREATE INDEX IX_Status_Flow ON dbo.[Status](FlowId);

-- Transition belongs to Flow; references Status (NO ACTION) to avoid multiple cascade paths
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
  CONSTRAINT FK_Transition_From FOREIGN KEY (FromStatusId) REFERENCES dbo.[Status](StatusId) ON DELETE NO ACTION,
  CONSTRAINT FK_Transition_To   FOREIGN KEY (ToStatusId)   REFERENCES dbo.[Status](StatusId) ON DELETE NO ACTION
);
CREATE INDEX IX_Transition_From ON dbo.Transition(FromStatusId);
CREATE INDEX IX_Transition_To ON dbo.Transition(ToStatusId);

-- Request belongs to Flow and Status; cascade only from Tenant (root) to Request; NO ACTION on Flow/Status
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
  CONSTRAINT FK_Request_Tenant    FOREIGN KEY (TenantId) REFERENCES dbo.Tenant(TenantId) ON DELETE CASCADE,
  CONSTRAINT FK_Request_Flow      FOREIGN KEY (FlowId)   REFERENCES dbo.Flow(FlowId) ON DELETE NO ACTION,
  CONSTRAINT FK_Request_Status    FOREIGN KEY (StatusId) REFERENCES dbo.[Status](StatusId) ON DELETE NO ACTION,
  CONSTRAINT FK_Request_Requester FOREIGN KEY (RequesterId) REFERENCES dbo.[User](UserId) ON DELETE NO ACTION,
  CONSTRAINT FK_Request_Assignee  FOREIGN KEY (AssigneeId)  REFERENCES dbo.[User](UserId) ON DELETE NO ACTION
);
CREATE INDEX IX_Request_Tenant ON dbo.Request(TenantId);
CREATE INDEX IX_Request_Status ON dbo.Request(StatusId);
CREATE INDEX IX_Request_Assignee ON dbo.Request(AssigneeId);
CREATE INDEX IX_Request_Updated ON dbo.Request(UpdatedAt);

-- Comment cascades from Request only; NO ACTION to Tenant
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
  CONSTRAINT FK_Comment_Tenant  FOREIGN KEY (TenantId)  REFERENCES dbo.Tenant(TenantId) ON DELETE NO ACTION,
  CONSTRAINT FK_Comment_Request FOREIGN KEY (RequestId) REFERENCES dbo.Request(RequestId) ON DELETE CASCADE,
  CONSTRAINT FK_Comment_Author  FOREIGN KEY (AuthorId)  REFERENCES dbo.[User](UserId) ON DELETE NO ACTION
);
CREATE INDEX IX_Comment_Request ON dbo.Comment(RequestId);
CREATE INDEX IX_Comment_Created ON dbo.Comment(CreatedAt);

-- Attachment cascades from Request only
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
  CONSTRAINT FK_Attachment_Tenant   FOREIGN KEY (TenantId)  REFERENCES dbo.Tenant(TenantId) ON DELETE NO ACTION,
  CONSTRAINT FK_Attachment_Request  FOREIGN KEY (RequestId) REFERENCES dbo.Request(RequestId) ON DELETE CASCADE,
  CONSTRAINT FK_Attachment_Comment  FOREIGN KEY (CommentId) REFERENCES dbo.Comment(CommentId) ON DELETE NO ACTION
);
CREATE INDEX IX_Attachment_Request ON dbo.Attachment(RequestId);

-- Activity cascades from Request only
CREATE TABLE dbo.Activity (
  ActivityId UNIQUEIDENTIFIER NOT NULL CONSTRAINT DF_ActivityId DEFAULT NEWSEQUENTIALID(),
  TenantId UNIQUEIDENTIFIER NOT NULL,
  RequestId UNIQUEIDENTIFIER NOT NULL,
  ActorId UNIQUEIDENTIFIER NULL,
  Type NVARCHAR(50) NOT NULL,
  Payload NVARCHAR(MAX) NULL,
  CreatedAt DATETIME2(3) NOT NULL CONSTRAINT DF_Activity_CreatedAt DEFAULT dbo.utc_now(),
  CONSTRAINT PK_Activity PRIMARY KEY CLUSTERED (ActivityId),
  CONSTRAINT FK_Activity_Tenant  FOREIGN KEY (TenantId)  REFERENCES dbo.Tenant(TenantId) ON DELETE NO ACTION,
  CONSTRAINT FK_Activity_Request FOREIGN KEY (RequestId) REFERENCES dbo.Request(RequestId) ON DELETE CASCADE,
  CONSTRAINT FK_Activity_Actor   FOREIGN KEY (ActorId)   REFERENCES dbo.[User](UserId) ON DELETE NO ACTION
);
CREATE INDEX IX_Activity_Request ON dbo.Activity(RequestId);

-- SavedSearch cascades from Tenant; NO ACTION from Owner
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
  CONSTRAINT FK_SavedSearch_Owner  FOREIGN KEY (OwnerId)  REFERENCES dbo.[User](UserId) ON DELETE NO ACTION
);

-- M:N tables ---------------------------------------------------------------

-- MembershipRole: CASCADE from Membership only; NO ACTION from Role
CREATE TABLE dbo.MembershipRole (
  MembershipId UNIQUEIDENTIFIER NOT NULL,
  RoleId UNIQUEIDENTIFIER NOT NULL,
  CONSTRAINT PK_MembershipRole PRIMARY KEY (MembershipId, RoleId),
  CONSTRAINT FK_MembershipRole_M FOREIGN KEY (MembershipId) REFERENCES dbo.Membership(MembershipId) ON DELETE CASCADE,
  CONSTRAINT FK_MembershipRole_R FOREIGN KEY (RoleId) REFERENCES dbo.[Role](RoleId) ON DELETE NO ACTION
);

-- RolePermission: CASCADE from Role; NO ACTION from Permission
CREATE TABLE dbo.RolePermission (
  RoleId UNIQUEIDENTIFIER NOT NULL,
  PermissionCode NVARCHAR(100) NOT NULL,
  CONSTRAINT PK_RolePermission PRIMARY KEY (RoleId, PermissionCode),
  CONSTRAINT FK_RolePermission_Role FOREIGN KEY (RoleId) REFERENCES dbo.[Role](RoleId) ON DELETE CASCADE,
  CONSTRAINT FK_RolePermission_Perm FOREIGN KEY (PermissionCode) REFERENCES dbo.Permission(Code) ON DELETE NO ACTION
);

-- RequestTag: CASCADE from Request only; NO ACTION from Tag
CREATE TABLE dbo.RequestTag (
  RequestId UNIQUEIDENTIFIER NOT NULL,
  TagId UNIQUEIDENTIFIER NOT NULL,
  CONSTRAINT PK_RequestTag PRIMARY KEY (RequestId, TagId),
  CONSTRAINT FK_RequestTag_R FOREIGN KEY (RequestId) REFERENCES dbo.Request(RequestId) ON DELETE CASCADE,
  CONSTRAINT FK_RequestTag_T FOREIGN KEY (TagId) REFERENCES dbo.Tag(TagId) ON DELETE NO ACTION
);

-------------------------------------------------------------------------------
-- FULL-TEXT SEARCH
-------------------------------------------------------------------------------
IF NOT EXISTS (SELECT * FROM sys.fulltext_catalogs WHERE name = 'rt_catalog')
  CREATE FULLTEXT CATALOG rt_catalog;

IF EXISTS (SELECT * FROM sys.fulltext_indexes fti JOIN sys.objects o ON fti.object_id=o.object_id WHERE o.name='Request')
  DROP FULLTEXT INDEX ON dbo.Request;
CREATE FULLTEXT INDEX ON dbo.Request
(
  Title LANGUAGE 1033,
  Description LANGUAGE 1033
)
KEY INDEX PK_Request ON rt_catalog WITH CHANGE_TRACKING AUTO;

IF EXISTS (SELECT * FROM sys.fulltext_indexes fti JOIN sys.objects o ON fti.object_id=o.object_id WHERE o.name='Comment')
  DROP FULLTEXT INDEX ON dbo.Comment;
CREATE FULLTEXT INDEX ON dbo.Comment
(
  MessageMd LANGUAGE 1033
)
KEY INDEX PK_Comment ON rt_catalog WITH CHANGE_TRACKING AUTO;

IF EXISTS (SELECT * FROM sys.fulltext_indexes fti JOIN sys.objects o ON fti.object_id=o.object_id WHERE o.name='Attachment')
  DROP FULLTEXT INDEX ON dbo.Attachment;
CREATE FULLTEXT INDEX ON dbo.Attachment
(
  Filename LANGUAGE 1033
)
KEY INDEX PK_Attachment ON rt_catalog WITH CHANGE_TRACKING AUTO;

-------------------------------------------------------------------------------
-- SEED minimal permissions
-------------------------------------------------------------------------------
IF NOT EXISTS (SELECT 1 FROM dbo.Permission WHERE Code='requests.read')
  INSERT INTO dbo.Permission(Code, Description) VALUES
    (N'requests.read', N'Read requests'),
    (N'requests.write', N'Create/Update requests'),
    (N'requests.transition', N'Change request status'),
    (N'comments.write', N'Add comments'),
    (N'attachments.write', N'Upload attachments'),
    (N'admin.users', N'Manage users'),
    (N'admin.workflows', N'Manage workflows');
