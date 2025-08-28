import uuid
import boto3
from botocore.client import Config
from django.conf import settings
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework import status

class HealthView(APIView):
    permission_classes = [AllowAny]
    def get(self, request):
        return Response({"status": "ok"}, status=status.HTTP_200_OK)

class PresignUploadView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        filename = request.data.get("filename")
        content_type = request.data.get("content_type", "application/octet-stream")
        if not filename:
            return Response({"detail": "filename is required"}, status=400)

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
        return Response({"url": url, "method": "PUT", "headers": {"Content-Type": content_type}, "object_key": key})