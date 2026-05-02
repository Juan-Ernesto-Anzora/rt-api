from rest_framework import serializers

from .models import Activity, Attachment, Comment, Request

# No necesitas importar Flow, Status, User aquí si usas UUIDField
# from .models import Flow, Status, User


class RequestSerializer(serializers.ModelSerializer):
    # --- INICIO DEL CAMBIO ---
    # Renombramos los campos para que coincidan directamente con los atributos del modelo
    # y eliminamos el parámetro `source`.
    flowid_id = serializers.UUIDField()
    statusid_id = serializers.UUIDField()
    requesterid_id = serializers.UUIDField()
    assigneeid_id = serializers.UUIDField(required=False, allow_null=True)
    # --- FIN DEL CAMBIO ---

    class Meta:
        model = Request
        # Actualizamos la lista de campos para reflejar los nuevos nombres
        fields = [
            "requestid",
            "humanid",
            "title",
            "description",
            "flowid_id",
            "statusid_id",
            "requesterid_id",
            "assigneeid_id",
            "priority",
            "dueat",
            "createdat",
            "updatedat",
        ]
        read_only_fields = ["requestid", "humanid", "createdat", "updatedat"]

    # def create(self, validated_data):
    # Opcional pero recomendado:
    # Tu tabla ya genera el RequestId con DEFAULT (newsequentialid()).
    # Es mejor dejar que la base de datos lo genere.
    # Puedes eliminar esta lógica de generación de UUID.
    # if "requestid" not in validated_data or not validated_data.get("requestid"):
    #     validated_data["requestid"] = uuid.uuid4()
    # return super().create(validated_data)


class CommentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Comment
        fields = [
            "commentid",
            "requestid",
            "authorid",
            "messagemd",
            "visibility",
            "createdat",
        ]


class AttachmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Attachment
        fields = [
            "attachmentid",
            "requestid",
            "commentid",
            "groupid",
            "filename",
            "contenttype",
            "sizebytes",
            "storageurl",
            "checksum",
            "scanstatus",
            "createdat",
        ]
        read_only_fields = ["attachmentid", "createdat"]


class AttachmentInitFileSerializer(serializers.Serializer):
    filename = serializers.CharField(max_length=255)
    content_type = serializers.CharField(max_length=100)
    size_bytes = serializers.IntegerField(required=False, min_value=0)
    checksum = serializers.CharField(required=False, allow_blank=True)


class AttachmentInitRequestSerializer(serializers.Serializer):
    request_id = serializers.UUIDField()
    files = AttachmentInitFileSerializer(many=True, allow_empty=False)


class PresignedUploadSerializer(serializers.Serializer):
    filename = serializers.CharField()
    content_type = serializers.CharField()
    size_bytes = serializers.IntegerField(required=False)
    checksum = serializers.CharField(required=False, allow_blank=True)
    object_key = serializers.CharField()
    url = serializers.CharField()
    method = serializers.CharField()
    headers = serializers.DictField()


class AttachmentInitResponseSerializer(serializers.Serializer):
    request_id = serializers.UUIDField()
    group_id = serializers.UUIDField()
    uploads = PresignedUploadSerializer(many=True)


class AttachmentFinalizeFileSerializer(serializers.Serializer):
    object_key = serializers.CharField(max_length=500)
    filename = serializers.CharField(max_length=255)
    content_type = serializers.CharField(
        max_length=100, required=False, allow_blank=True
    )
    size_bytes = serializers.IntegerField(required=False, min_value=0)
    checksum = serializers.CharField(required=False, allow_blank=True)


class AttachmentFinalizeRequestSerializer(serializers.Serializer):
    request_id = serializers.UUIDField()
    group_id = serializers.UUIDField()
    message = serializers.CharField(allow_blank=True, required=False)
    files = AttachmentFinalizeFileSerializer(many=True, allow_empty=False)


class ActivitySerializer(serializers.ModelSerializer):
    class Meta:
        model = Activity
        fields = ["activityid", "requestid", "actorid", "type", "payload", "createdat"]
