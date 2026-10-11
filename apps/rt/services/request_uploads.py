import hashlib
import json
import uuid
from datetime import timedelta
from urllib.parse import quote

import boto3
from botocore.client import Config
from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings
from django.db import connection, transaction
from django.db.models.expressions import RawSQL
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.exceptions import APIException, NotFound, ValidationError

from apps.rt.models import Activity, Attachment, Comment

from .notification_service import notify_comment_added
from .request_workspace import WorkspaceConflict


class StorageUnavailable(APIException):
    status_code = 503
    default_code = "storage_unavailable"
    default_detail = "Attachment storage is temporarily unavailable."


def storage_client(*, endpoint_url=None):
    return boto3.client(
        "s3",
        endpoint_url=endpoint_url or settings.MINIO_ENDPOINT,
        aws_access_key_id=settings.MINIO_ACCESS_KEY,
        aws_secret_access_key=settings.MINIO_SECRET_KEY,
        config=Config(signature_version="s3v4"),
        region_name=settings.MINIO_REGION,
    )


def storage_url(key):
    endpoint = settings.MINIO_PUBLIC_URL or settings.MINIO_ENDPOINT
    return f"{endpoint.rstrip('/')}/{settings.MINIO_BUCKET}/{key}"


def object_key(attachment):
    prefixes = [
        f"{endpoint.rstrip('/')}/{settings.MINIO_BUCKET}/"
        for endpoint in (settings.MINIO_PUBLIC_URL, settings.MINIO_ENDPOINT)
        if endpoint
    ]
    prefix = next(
        (value for value in prefixes if attachment.storageurl.startswith(value)), None
    )
    if prefix is None:
        raise NotFound("Attachment object is unavailable.")
    key = attachment.storageurl[len(prefix) :]
    if key.startswith("attachments/") and not key.startswith(
        f"attachments/{attachment.tenantid_id}/{attachment.requestid_id}/"
    ):
        raise NotFound("Attachment object is unavailable.")
    if not key.startswith(("uploads/", "attachments/")) or any(
        part in {".", ".."} for part in key.split("/")
    ):
        raise NotFound("Attachment object is unavailable.")
    return key


def public_signer(client):
    return (
        storage_client(endpoint_url=settings.MINIO_PUBLIC_URL)
        if settings.MINIO_PUBLIC_URL
        else client
    )


def manifest_key(request, group_id):
    return (
        f".rt-upload-sessions/{request.tenantid_id}/{request.requestid}/{group_id}.json"
    )


def initiate_upload(request, files, actor):
    group_id = uuid.uuid4()
    client = storage_client()
    signer = public_signer(client)
    issued = []
    uploads = []
    expires_at = timezone.now() + timedelta(seconds=3600)
    try:
        for entry in files:
            filename = entry["filename"]
            if any(
                character in filename for character in ("/", "\\", "\r", "\n", "\x00")
            ) or filename in {".", ".."}:
                raise ValidationError({"files": ["Filename must be a plain filename."]})
            key = f"uploads/{group_id}/{uuid.uuid4()}-{filename}"
            published_example = f"attachments/{request.tenantid_id}/{request.requestid}/{group_id}/{uuid.uuid4()}-{filename}"
            if (
                len(storage_url(published_example))
                > Attachment._meta.get_field("storageurl").max_length
            ):
                raise ValidationError(
                    {"files": ["Filename is too long for the configured storage URL."]}
                )
            item = {**entry, "object_key": key}
            issued.append(item)
            uploads.append(
                {
                    **item,
                    "url": signer.generate_presigned_url(
                        "put_object",
                        Params={
                            "Bucket": settings.MINIO_BUCKET,
                            "Key": key,
                            "ContentType": entry["content_type"],
                        },
                        ExpiresIn=3600,
                    ),
                    "method": "PUT",
                    "headers": {"Content-Type": entry["content_type"]},
                }
            )
        manifest = {
            "tenant_id": str(request.tenantid_id),
            "request_id": str(request.requestid),
            "group_id": str(group_id),
            "issued_by": str(actor.userid),
            "expires_at": expires_at.isoformat(),
            "files": issued,
        }
        client.put_object(
            Bucket=settings.MINIO_BUCKET,
            Key=manifest_key(request, group_id),
            Body=json.dumps(manifest).encode(),
            ContentType="application/json",
        )
    except (ClientError, BotoCoreError) as exc:
        raise StorageUnavailable() from exc
    return {
        "request_id": str(request.requestid),
        "group_id": str(group_id),
        "uploads": uploads,
        "expires_at": expires_at.isoformat(),
    }


def finalize_fingerprint(data):
    files = [
        {
            key: item.get(key)
            for key in (
                "object_key",
                "filename",
                "content_type",
                "size_bytes",
                "checksum",
            )
        }
        for item in data["files"]
    ]
    for item in files:
        item["content_type"] = item["content_type"] or ""
        item["checksum"] = item["checksum"] or ""
    canonical = {
        "message": data.get("message") or "",
        "files": sorted(files, key=lambda item: item["object_key"]),
    }
    return hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def lock_group(tenant_id, group_id):
    with connection.cursor() as cursor:
        cursor.execute(
            "DECLARE @result int; EXEC @result=sys.sp_getapplock @Resource=%s, @LockMode='Exclusive', @LockOwner='Transaction', @LockTimeout=10000; SELECT @result;",
            [f"rt:upload:{tenant_id}:{group_id}"],
        )
        result = cursor.fetchone()[0]
    if result < 0:
        raise WorkspaceConflict("Upload group is busy; retry finalize.")


def finalized_response(request, group_id, comment_id, attachments):
    return {
        "request_id": str(request.requestid),
        "group_id": str(group_id),
        "comment_id": str(comment_id),
        "attachments": [
            {
                "attachment_id": str(item.attachmentid),
                "filename": item.filename,
                "storage_url": item.storageurl,
            }
            for item in attachments
        ],
    }


def checked_objects(client, request, group_id, data):
    try:
        response = client.get_object(
            Bucket=settings.MINIO_BUCKET, Key=manifest_key(request, group_id)
        )
        body = response["Body"]
        try:
            manifest = json.loads(body.read())
        finally:
            body.close()
    except ClientError as exc:
        if str(exc.response.get("Error", {}).get("Code")) in {
            "NoSuchKey",
            "404",
            "NotFound",
        }:
            raise NotFound("Upload session not found for this request.") from exc
        raise StorageUnavailable() from exc
    except (BotoCoreError, ValueError, KeyError) as exc:
        raise StorageUnavailable() from exc
    if (
        not isinstance(manifest, dict)
        or not isinstance(manifest.get("files"), list)
        or not all(
            isinstance(item, dict)
            and {"object_key", "filename", "content_type"}.issubset(item)
            for item in manifest["files"]
        )
    ):
        raise StorageUnavailable()
    if (
        manifest.get("tenant_id") != str(request.tenantid_id)
        or manifest.get("request_id") != str(request.requestid)
        or manifest.get("group_id") != str(group_id)
    ):
        raise NotFound("Upload session not found for this request.")
    try:
        expiry = parse_datetime(manifest.get("expires_at", ""))
    except (ValueError, TypeError) as exc:
        raise StorageUnavailable() from exc
    if expiry is None or timezone.is_naive(expiry):
        raise StorageUnavailable()
    if expiry <= timezone.now():
        raise WorkspaceConflict("Upload session expired; initialize a new group.")
    expected = {item["object_key"]: item for item in manifest["files"]}
    submitted = {item["object_key"]: item for item in data["files"]}
    if len(submitted) != len(data["files"]) or set(submitted) != set(expected):
        raise ValidationError(
            {"files": ["Finalize must contain exactly the issued object keys."]}
        )
    checked = []
    for key, item in submitted.items():
        issued = expected[key]
        if (
            not key.startswith(f"uploads/{group_id}/")
            or item["filename"] != issued["filename"]
        ):
            raise ValidationError(
                {"files": ["Object does not belong to the issued group."]}
            )
        try:
            head = client.head_object(Bucket=settings.MINIO_BUCKET, Key=key)
        except ClientError as exc:
            if str(exc.response.get("Error", {}).get("Code")) in {
                "NoSuchKey",
                "404",
                "NotFound",
            }:
                raise ValidationError(
                    {"files": ["An uploaded object is missing; retry its PUT."]}
                ) from exc
            raise StorageUnavailable() from exc
        except BotoCoreError as exc:
            raise StorageUnavailable() from exc
        size, content_type = head["ContentLength"], head.get("ContentType", "")
        if content_type != issued["content_type"] or (
            item.get("content_type") and item["content_type"] != content_type
        ):
            raise ValidationError(
                {"files": ["Object content type does not match init/finalize."]}
            )
        if any(
            value is not None and value != size
            for value in (issued.get("size_bytes"), item.get("size_bytes"))
        ):
            raise ValidationError(
                {"files": ["Object size does not match init/finalize."]}
            )
        if (
            item.get("checksum")
            and issued.get("checksum")
            and item["checksum"] != issued["checksum"]
        ):
            raise ValidationError({"files": ["Declared checksum differs from init."]})
        if not head.get("ETag"):
            raise StorageUnavailable()
        checked.append(
            {
                **item,
                "content_type": content_type,
                "size_bytes": size,
                "etag": head["ETag"],
            }
        )
    return checked


@transaction.atomic
def finalize_upload(request, data, actor):
    group_id = str(data["group_id"])
    lock_group(request.tenantid_id, group_id)
    previous = (
        Activity.objects.filter(
            tenantid=request.tenantid_id, type="attachments.finalized"
        )
        .annotate(
            upload_group=RawSQL(
                "JSON_VALUE(CASE WHEN ISJSON(Payload)=1 THEN Payload ELSE '{}' END,'$.group_id')",
                [],
            )
        )
        .filter(upload_group=group_id)
        .first()
    )
    if previous:
        payload = json.loads(previous.payload)
        if previous.requestid_id != request.requestid:
            raise WorkspaceConflict(
                "Upload group was already finalized with different content."
            )
        files = Attachment.objects.filter(
            tenantid=request.tenantid_id,
            requestid=request.requestid,
            groupid=group_id,
            commentid=payload["comment_id"],
        )
        by_id = {str(item.attachmentid): item for item in files}
        issued_ids = payload.get("issued_objects", {})
        retry_files = []
        for item in data["files"]:
            saved = by_id.get(issued_ids.get(item["object_key"]))
            retry_files.append(
                {
                    **item,
                    "content_type": item.get("content_type")
                    or (saved.contenttype if saved else ""),
                    "size_bytes": (
                        item.get("size_bytes")
                        if item.get("size_bytes") is not None
                        else saved.sizebytes if saved else None
                    ),
                    "checksum": item.get("checksum")
                    or (saved.checksum if saved else ""),
                }
            )
        if payload.get("finalize_fingerprint") != finalize_fingerprint(
            {**data, "files": retry_files}
        ):
            raise WorkspaceConflict(
                "Upload group was already finalized with different content."
            )
        files = [
            by_id[key] for key in payload.get("attachment_ids", by_id) if key in by_id
        ]
        return (
            finalized_response(request, group_id, payload["comment_id"], files),
            False,
        )
    if Comment.objects.filter(tenantid=request.tenantid_id, groupid=group_id).exists():
        raise WorkspaceConflict("Legacy upload group is already finalized.")
    client = storage_client()
    checked = checked_objects(client, request, group_id, data)
    fingerprint = finalize_fingerprint({**data, "files": checked})
    # Issued PUT URLs remain valid: publish an immutable server-only copy instead.
    for item in checked:
        final_key = f"attachments/{request.tenantid_id}/{request.requestid}/{group_id}/{uuid.uuid4()}-{item['filename']}"
        if (
            len(storage_url(final_key))
            > Attachment._meta.get_field("storageurl").max_length
        ):
            raise ValidationError(
                {"files": ["Filename is too long for the configured storage URL."]}
            )
        try:
            client.copy_object(
                Bucket=settings.MINIO_BUCKET,
                Key=final_key,
                CopySource={"Bucket": settings.MINIO_BUCKET, "Key": item["object_key"]},
                CopySourceIfMatch=item["etag"],
            )
        except ClientError as exc:
            if str(exc.response.get("Error", {}).get("Code")) in {
                "PreconditionFailed",
                "412",
            }:
                raise WorkspaceConflict(
                    "Upload changed during finalize; retry the operation."
                ) from exc
            raise StorageUnavailable() from exc
        except BotoCoreError as exc:
            raise StorageUnavailable() from exc
        item["final_object_key"] = final_key
    now = timezone.now()
    comment = Comment.objects.create(
        commentid=uuid.uuid4(),
        tenantid=request.tenantid,
        requestid=request,
        authorid=actor,
        groupid=group_id,
        messagemd=data.get("message") or "",
        visibility="public",
        createdat=now,
    )
    files = [
        Attachment(
            attachmentid=uuid.uuid4(),
            tenantid=request.tenantid,
            requestid=request,
            commentid=comment,
            groupid=group_id,
            filename=item["filename"],
            storageurl=storage_url(item["final_object_key"]),
            contenttype=item["content_type"],
            sizebytes=item["size_bytes"],
            checksum=item.get("checksum") or "",
            scanstatus="pending",
            createdat=now,
        )
        for item in checked
    ]
    Attachment.objects.bulk_create(files)
    Activity.objects.create(
        activityid=uuid.uuid4(),
        tenantid=request.tenantid,
        requestid=request,
        actorid=actor,
        type="attachments.finalized",
        createdat=now,
        payload=json.dumps(
            {
                "comment_id": str(comment.commentid),
                "group_id": group_id,
                "finalize_fingerprint": fingerprint,
                "attachment_ids": [str(item.attachmentid) for item in files],
                "issued_objects": {
                    item["object_key"]: str(file.attachmentid)
                    for item, file in zip(checked, files)
                },
                "filenames": [item.filename for item in files],
            }
        ),
    )
    transaction.on_commit(lambda: notify_comment_added(comment))
    return finalized_response(request, group_id, comment.commentid, files), True


def download_url(attachment):
    if attachment.scanstatus != "clean":
        raise WorkspaceConflict("Attachment is not clean and cannot be downloaded.")
    key = object_key(attachment)
    try:
        client = storage_client()
        client.head_object(Bucket=settings.MINIO_BUCKET, Key=key)
        url = public_signer(client).generate_presigned_url(
            "get_object",
            Params={
                "Bucket": settings.MINIO_BUCKET,
                "Key": key,
                "ResponseContentDisposition": "attachment; filename*=UTF-8''"
                + quote(attachment.filename, safe=""),
            },
            ExpiresIn=300,
        )
    except ClientError as exc:
        if str(exc.response.get("Error", {}).get("Code")) in {
            "NoSuchKey",
            "404",
            "NotFound",
        }:
            raise NotFound("Attachment object is unavailable.") from exc
        raise StorageUnavailable() from exc
    except BotoCoreError as exc:
        raise StorageUnavailable() from exc
    return {"url": url, "expires_at": timezone.now() + timedelta(seconds=300)}
