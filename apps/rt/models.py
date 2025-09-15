import uuid

from django.db import models


class CustomUUIDField(models.UUIDField):
    def get_db_prep_value(self, value, connection, prepared=False):
        if value is None:
            return None
        if not isinstance(value, uuid.UUID):
            value = self.to_python(value)
        # Always return hyphenated string for MSSQL compatibility
        return str(value)


class Tenant(models.Model):
    tenantid = CustomUUIDField(db_column="TenantId", primary_key=True, editable=False)
    code = models.CharField(
        db_column="Code",
        unique=True,
        max_length=32,
        db_collation="Latin1_General_100_CI_AS_SC_UTF8",
    )  # Field name made lowercase.
    name = models.CharField(
        db_column="Name",
        max_length=200,
        db_collation="Latin1_General_100_CI_AS_SC_UTF8",
    )  # Field name made lowercase.
    isactive = models.BooleanField(db_column="IsActive")  # Field name made lowercase.
    createdat = models.DateTimeField(
        db_column="CreatedAt"
    )  # Field name made lowercase.
    updatedat = models.DateTimeField(
        db_column="UpdatedAt", blank=True, null=True
    )  # Field name made lowercase.

    class Meta:
        managed = False
        db_table = "Tenant"


class User(models.Model):
    userid = CustomUUIDField(db_column="UserId", primary_key=True, editable=False)
    email = models.CharField(
        db_column="Email",
        unique=True,
        max_length=320,
        db_collation="Latin1_General_100_CI_AS_SC_UTF8",
    )  # Field name made lowercase.
    displayname = models.CharField(
        db_column="DisplayName",
        max_length=200,
        db_collation="Latin1_General_100_CI_AS_SC_UTF8",
    )  # Field name made lowercase.
    employeecode = models.CharField(
        db_column="EmployeeCode",
        max_length=50,
        db_collation="Latin1_General_100_CI_AS_SC_UTF8",
        blank=True,
        null=True,
    )  # Field name made lowercase.
    avatarurl = models.CharField(
        db_column="AvatarUrl",
        max_length=400,
        db_collation="Latin1_General_100_CI_AS_SC_UTF8",
        blank=True,
        null=True,
    )  # Field name made lowercase.
    isactive = models.BooleanField(db_column="IsActive")  # Field name made lowercase.
    createdat = models.DateTimeField(
        db_column="CreatedAt"
    )  # Field name made lowercase.
    updatedat = models.DateTimeField(
        db_column="UpdatedAt", blank=True, null=True
    )  # Field name made lowercase.

    class Meta:
        managed = False
        db_table = "dbo.User"


class Role(models.Model):
    roleid = CustomUUIDField(db_column="RoleId", primary_key=True, editable=False)
    tenantid = models.ForeignKey(
        "Tenant", models.DO_NOTHING, db_column="TenantId"
    )  # Field name made lowercase.
    name = models.CharField(
        db_column="Name",
        max_length=100,
        db_collation="Latin1_General_100_CI_AS_SC_UTF8",
    )  # Field name made lowercase.
    description = models.CharField(
        db_column="Description",
        max_length=400,
        db_collation="Latin1_General_100_CI_AS_SC_UTF8",
        blank=True,
        null=True,
    )  # Field name made lowercase.
    createdat = models.DateTimeField(
        db_column="CreatedAt"
    )  # Field name made lowercase.

    class Meta:
        managed = False
        db_table = "Role"
        unique_together = (("tenantid", "name"),)


class Permission(models.Model):
    code = models.CharField(
        db_column="Code",
        primary_key=True,
        max_length=100,
        db_collation="Latin1_General_100_CI_AS_SC_UTF8",
    )  # Field name made lowercase.
    description = models.CharField(
        db_column="Description",
        max_length=400,
        db_collation="Latin1_General_100_CI_AS_SC_UTF8",
        blank=True,
        null=True,
    )  # Field name made lowercase.

    class Meta:
        managed = False
        db_table = "Permission"


class Membership(models.Model):
    membershipid = CustomUUIDField(
        db_column="MembershipId", primary_key=True, editable=False
    )
    tenantid = models.ForeignKey(
        "Tenant", models.DO_NOTHING, db_column="TenantId"
    )  # Field name made lowercase.
    userid = models.ForeignKey(
        "User", models.DO_NOTHING, db_column="UserId"
    )  # Field name made lowercase.
    isdefaulttenant = models.BooleanField(
        db_column="IsDefaultTenant"
    )  # Field name made lowercase.
    createdat = models.DateTimeField(
        db_column="CreatedAt"
    )  # Field name made lowercase.

    class Meta:
        managed = False
        db_table = "Membership"
        unique_together = (("tenantid", "userid"),)


class Flow(models.Model):
    flowid = CustomUUIDField(db_column="FlowId", primary_key=True, editable=False)
    tenantid = models.ForeignKey(
        "Tenant", models.DO_NOTHING, db_column="TenantId"
    )  # Field name made lowercase.
    name = models.CharField(
        db_column="Name",
        max_length=100,
        db_collation="Latin1_General_100_CI_AS_SC_UTF8",
    )  # Field name made lowercase.
    description = models.CharField(
        db_column="Description",
        max_length=400,
        db_collation="Latin1_General_100_CI_AS_SC_UTF8",
        blank=True,
        null=True,
    )  # Field name made lowercase.
    createdat = models.DateTimeField(
        db_column="CreatedAt"
    )  # Field name made lowercase.

    class Meta:
        managed = False
        db_table = "Flow"
        unique_together = (("tenantid", "name"),)


class Tag(models.Model):
    tagid = CustomUUIDField(db_column="TagId", primary_key=True, editable=False)
    tenantid = models.ForeignKey(
        "Tenant", models.DO_NOTHING, db_column="TenantId"
    )  # Field name made lowercase.
    name = models.CharField(
        db_column="Name", max_length=50, db_collation="Latin1_General_100_CI_AS_SC_UTF8"
    )  # Field name made lowercase.

    class Meta:
        managed = False
        db_table = "Tag"
        unique_together = (("tenantid", "name"),)


class Slapolicy(models.Model):
    policyid = CustomUUIDField(db_column="PolicyId", primary_key=True, editable=False)
    tenantid = models.ForeignKey(
        "Tenant", models.DO_NOTHING, db_column="TenantId"
    )  # Field name made lowercase.
    name = models.CharField(
        db_column="Name",
        max_length=100,
        db_collation="Latin1_General_100_CI_AS_SC_UTF8",
    )  # Field name made lowercase.
    appliesto = models.TextField(
        db_column="AppliesTo",
        db_collation="Latin1_General_100_CI_AS_SC_UTF8",
        blank=True,
        null=True,
    )  # Field name made lowercase.
    targets = models.TextField(
        db_column="Targets",
        db_collation="Latin1_General_100_CI_AS_SC_UTF8",
        blank=True,
        null=True,
    )  # Field name made lowercase.
    createdat = models.DateTimeField(
        db_column="CreatedAt"
    )  # Field name made lowercase.

    class Meta:
        managed = False
        db_table = "SlaPolicy"


# CHILD TABLES
class Status(models.Model):
    statusid = CustomUUIDField(db_column="StatusId", primary_key=True, editable=False)
    tenantid = models.ForeignKey(
        "Tenant", models.DO_NOTHING, db_column="TenantId"
    )  # Field name made lowercase.
    flowid = models.ForeignKey(
        Flow, models.DO_NOTHING, db_column="FlowId"
    )  # Field name made lowercase.
    name = models.CharField(
        db_column="Name", max_length=50, db_collation="Latin1_General_100_CI_AS_SC_UTF8"
    )  # Field name made lowercase.
    category = models.CharField(
        db_column="Category",
        max_length=20,
        db_collation="Latin1_General_100_CI_AS_SC_UTF8",
    )  # Field name made lowercase.
    isterminal = models.BooleanField(
        db_column="IsTerminal"
    )  # Field name made lowercase.
    createdat = models.DateTimeField(
        db_column="CreatedAt"
    )  # Field name made lowercase.

    class Meta:
        managed = False
        db_table = "Status"


class Transition(models.Model):
    transitionid = CustomUUIDField(
        db_column="TransitionId", primary_key=True, editable=False
    )
    flowid = models.ForeignKey(
        Flow, models.DO_NOTHING, db_column="FlowId"
    )  # Field name made lowercase.
    fromstatusid = models.ForeignKey(
        Status, models.DO_NOTHING, db_column="FromStatusId"
    )  # Field name made lowercase.
    tostatusid = models.ForeignKey(
        Status,
        models.DO_NOTHING,
        db_column="ToStatusId",
        related_name="transition_tostatusid_set",
    )  # Field name made lowercase.
    guardrolesjson = models.TextField(
        db_column="GuardRolesJson",
        db_collation="Latin1_General_100_CI_AS_SC_UTF8",
        blank=True,
        null=True,
    )  # Field name made lowercase.
    guardpermsjson = models.TextField(
        db_column="GuardPermsJson",
        db_collation="Latin1_General_100_CI_AS_SC_UTF8",
        blank=True,
        null=True,
    )  # Field name made lowercase.
    autorules = models.TextField(
        db_column="AutoRules",
        db_collation="Latin1_General_100_CI_AS_SC_UTF8",
        blank=True,
        null=True,
    )  # Field name made lowercase.
    createdat = models.DateTimeField(
        db_column="CreatedAt"
    )  # Field name made lowercase.

    class Meta:
        managed = False
        db_table = "Transition"


class Request(models.Model):
    requestid = CustomUUIDField(
        db_column="RequestId", primary_key=True, default=uuid.uuid4, editable=False
    )  # Field name made lowercase.
    tenantid = models.ForeignKey(
        "Tenant", models.DO_NOTHING, db_column="TenantId"
    )  # Field name made lowercase.
    humanid = models.CharField(
        db_column="HumanId",
        max_length=40,
        db_collation="Latin1_General_100_CI_AS_SC_UTF8",
    )  # Field name made lowercase.
    title = models.CharField(
        db_column="Title",
        max_length=200,
        db_collation="Latin1_General_100_CI_AS_SC_UTF8",
    )  # Field name made lowercase.
    description = models.TextField(
        db_column="Description",
        db_collation="Latin1_General_100_CI_AS_SC_UTF8",
        blank=True,
        null=True,
    )  # Field name made lowercase.
    flowid = models.ForeignKey(
        Flow, models.DO_NOTHING, db_column="FlowId"
    )  # Field name made lowercase.
    statusid = models.ForeignKey(
        "Status", models.DO_NOTHING, db_column="StatusId"
    )  # Field name made lowercase.
    priority = models.CharField(
        db_column="Priority",
        max_length=20,
        db_collation="Latin1_General_100_CI_AS_SC_UTF8",
    )  # Field name made lowercase.
    requesterid = models.ForeignKey(
        "User", models.DO_NOTHING, db_column="RequesterId"
    )  # Field name made lowercase.
    assigneeid = models.ForeignKey(
        "User",
        models.DO_NOTHING,
        db_column="AssigneeId",
        related_name="request_assigneeid_set",
        blank=True,
        null=True,
    )  # Field name made lowercase.
    customfields = models.TextField(
        db_column="CustomFields",
        db_collation="Latin1_General_100_CI_AS_SC_UTF8",
        blank=True,
        null=True,
    )  # Field name made lowercase.
    dueat = models.DateTimeField(
        db_column="DueAt", blank=True, null=True
    )  # Field name made lowercase.
    createdat = models.DateTimeField(
        db_column="CreatedAt"
    )  # Field name made lowercase.
    updatedat = models.DateTimeField(
        db_column="UpdatedAt"
    )  # Field name made lowercase.
    # rowver = models.TextField(db_column='RowVer')  # Field name made lowercase. This field type is a guess.

    class Meta:
        managed = False
        db_table = "Request"
        unique_together = (("tenantid", "humanid"),)


class Comment(models.Model):
    commentid = CustomUUIDField(db_column="CommentId", primary_key=True, editable=False)
    tenantid = models.ForeignKey(
        "Tenant", models.DO_NOTHING, db_column="TenantId"
    )  # Field name made lowercase.
    requestid = models.ForeignKey(
        "Request", models.DO_NOTHING, db_column="RequestId"
    )  # Field name made lowercase.
    authorid = models.ForeignKey(
        "User", models.DO_NOTHING, db_column="AuthorId"
    )  # Field name made lowercase.
    groupid = models.CharField(
        db_column="GroupId", max_length=36, blank=True, null=True
    )  # Field name made lowercase.
    messagemd = models.TextField(
        db_column="MessageMd", db_collation="Latin1_General_100_CI_AS_SC_UTF8"
    )  # Field name made lowercase.
    visibility = models.CharField(
        db_column="Visibility",
        max_length=10,
        db_collation="Latin1_General_100_CI_AS_SC_UTF8",
    )  # Field name made lowercase.
    createdat = models.DateTimeField(
        db_column="CreatedAt"
    )  # Field name made lowercase.

    class Meta:
        managed = False
        db_table = "Comment"


class Attachment(models.Model):
    attachmentid = CustomUUIDField(
        db_column="AttachmentId", primary_key=True, editable=False
    )
    tenantid = models.ForeignKey(
        "Tenant", models.DO_NOTHING, db_column="TenantId"
    )  # Field name made lowercase.
    requestid = models.ForeignKey(
        "Request", models.DO_NOTHING, db_column="RequestId"
    )  # Field name made lowercase.
    commentid = models.ForeignKey(
        "Comment", models.DO_NOTHING, db_column="CommentId", blank=True, null=True
    )  # Field name made lowercase.
    groupid = models.CharField(
        db_column="GroupId", max_length=36, blank=True, null=True
    )  # Field name made lowercase.
    filename = models.CharField(
        db_column="Filename",
        max_length=255,
        db_collation="Latin1_General_100_CI_AS_SC_UTF8",
    )  # Field name made lowercase.
    contenttype = models.CharField(
        db_column="ContentType",
        max_length=100,
        db_collation="Latin1_General_100_CI_AS_SC_UTF8",
        blank=True,
        null=True,
    )  # Field name made lowercase.
    sizebytes = models.BigIntegerField(
        db_column="SizeBytes", blank=True, null=True
    )  # Field name made lowercase.
    storageurl = models.CharField(
        db_column="StorageUrl",
        max_length=500,
        db_collation="Latin1_General_100_CI_AS_SC_UTF8",
    )  # Field name made lowercase.
    checksum = models.CharField(
        db_column="Checksum",
        max_length=128,
        db_collation="Latin1_General_100_CI_AS_SC_UTF8",
        blank=True,
        null=True,
    )  # Field name made lowercase.
    scanstatus = models.CharField(
        db_column="ScanStatus",
        max_length=20,
        db_collation="Latin1_General_100_CI_AS_SC_UTF8",
        blank=True,
        null=True,
    )  # Field name made lowercase.
    createdat = models.DateTimeField(
        db_column="CreatedAt"
    )  # Field name made lowercase.

    class Meta:
        managed = False
        db_table = "Attachment"


class Activity(models.Model):
    activityid = CustomUUIDField(
        db_column="ActivityId", primary_key=True, editable=False
    )
    tenantid = models.ForeignKey(
        "Tenant", models.DO_NOTHING, db_column="TenantId"
    )  # Field name made lowercase.
    requestid = models.ForeignKey(
        "Request", models.DO_NOTHING, db_column="RequestId"
    )  # Field name made lowercase.
    actorid = models.ForeignKey(
        "User", models.DO_NOTHING, db_column="ActorId", blank=True, null=True
    )  # Field name made lowercase.
    type = models.CharField(
        db_column="Type", max_length=50, db_collation="Latin1_General_100_CI_AS_SC_UTF8"
    )  # Field name made lowercase.
    payload = models.TextField(
        db_column="Payload",
        db_collation="Latin1_General_100_CI_AS_SC_UTF8",
        blank=True,
        null=True,
    )  # Field name made lowercase.
    createdat = models.DateTimeField(
        db_column="CreatedAt"
    )  # Field name made lowercase.

    class Meta:
        managed = False
        db_table = "Activity"


class Savedsearch(models.Model):
    savedsearchid = CustomUUIDField(
        db_column="SavedSearchId", primary_key=True, editable=False
    )
    tenantid = models.ForeignKey(
        "Tenant", models.DO_NOTHING, db_column="TenantId"
    )  # Field name made lowercase.
    ownerid = models.ForeignKey(
        "User", models.DO_NOTHING, db_column="OwnerId"
    )  # Field name made lowercase.
    name = models.CharField(
        db_column="Name",
        max_length=100,
        db_collation="Latin1_General_100_CI_AS_SC_UTF8",
    )  # Field name made lowercase.
    queryparams = models.TextField(
        db_column="QueryParams", db_collation="Latin1_General_100_CI_AS_SC_UTF8"
    )  # Field name made lowercase.
    isshared = models.BooleanField(db_column="IsShared")  # Field name made lowercase.
    createdat = models.DateTimeField(
        db_column="CreatedAt"
    )  # Field name made lowercase.

    class Meta:
        managed = False
        db_table = "SavedSearch"


# M:N tables

# class Membershiprole(models.Model):
#    pk = models.CompositePrimaryKey('MembershipId', 'RoleId')
#    membershipid = models.ForeignKey(Membership, models.DO_NOTHING, db_column='MembershipId')  # Field name made lowercase.
#    roleid = models.ForeignKey('Role', models.DO_NOTHING, db_column='RoleId')  # Field name made lowercase.
#
#    class Meta:
#        managed = False
#        db_table = 'MembershipRole'

# class Rolepermission(models.Model):
#     pk = models.CompositePrimaryKey('RoleId', 'PermissionCode')
#     roleid = models.ForeignKey(Role, models.DO_NOTHING, db_column='RoleId')  # Field name made lowercase.
#     permissioncode = models.ForeignKey(Permission, models.DO_NOTHING, db_column='PermissionCode')  # Field name made lowercase.
#
#     class Meta:
#         managed = False
#         db_table = 'RolePermission'

# class Requesttag(models.Model):
#    pk = models.CompositePrimaryKey('RequestId', 'TagId')
#    requestid = models.ForeignKey(Request, models.DO_NOTHING, db_column='RequestId')  # Field name made lowercase.
#    tagid = models.ForeignKey('Tag', models.DO_NOTHING, db_column='TagId')  # Field name made lowercase.
#
#    class Meta:
#        managed = False
#        db_table = 'RequestTag'
