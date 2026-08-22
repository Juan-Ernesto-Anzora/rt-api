import uuid

import boto3
from botocore.client import Config
from django.conf import settings
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from rt_api.exceptions import error_envelope

from .serializers import (
    HealthResponseSerializer,
    PresignUploadRequestSerializer,
    PresignUploadResponseSerializer,
)


class HealthView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(responses=HealthResponseSerializer)
    def get(self, request):
        return Response({"status": "ok"}, status=status.HTTP_200_OK)


class PresignUploadView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=PresignUploadRequestSerializer,
        responses=PresignUploadResponseSerializer,
    )
    def post(self, request):
        serializer = PresignUploadRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                error_envelope(
                    "validation_error",
                    "Invalid request payload.",
                    [
                        {"field": field, "message": str(message)}
                        for field, messages in serializer.errors.items()
                        for message in messages
                    ],
                ),
                status=400,
            )
        filename = serializer.validated_data["filename"]
        content_type = serializer.validated_data["content_type"]

        key = f"uploads/{uuid.uuid4()}-{filename}"
        s3 = boto3.client(
            "s3",
            endpoint_url=settings.MINIO_ENDPOINT,
            aws_access_key_id=settings.MINIO_ACCESS_KEY,
            aws_secret_access_key=settings.MINIO_SECRET_KEY,
            region_name=settings.MINIO_REGION,
            config=Config(signature_version="s3v4"),
        )

        url = s3.generate_presigned_url(
            ClientMethod="put_object",
            Params={
                "Bucket": settings.MINIO_BUCKET,
                "Key": key,
                "ContentType": content_type,
            },
            ExpiresIn=3600,
        )
        return Response(
            {
                "url": url,
                "method": "PUT",
                "headers": {"Content-Type": content_type},
                "object_key": key,
            }
        )
