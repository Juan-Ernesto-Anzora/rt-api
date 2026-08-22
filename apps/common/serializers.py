from rest_framework import serializers


class ErrorDetailSerializer(serializers.Serializer):
    field = serializers.CharField(allow_blank=True)
    message = serializers.CharField()


class ErrorEnvelopeSerializer(serializers.Serializer):
    code = serializers.CharField()
    message = serializers.CharField()
    details = ErrorDetailSerializer(many=True)


class HealthResponseSerializer(serializers.Serializer):
    status = serializers.CharField()


class PresignUploadRequestSerializer(serializers.Serializer):
    filename = serializers.CharField(max_length=255)
    content_type = serializers.CharField(
        required=False, default="application/octet-stream", max_length=100
    )


class PresignUploadResponseSerializer(serializers.Serializer):
    url = serializers.URLField()
    method = serializers.CharField()
    headers = serializers.DictField(child=serializers.CharField())
    object_key = serializers.CharField()
