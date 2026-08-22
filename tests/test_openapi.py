from django.test import Client


def test_openapi_has_canonical_paths_and_version():
    response = Client().get("/api/schema")
    content = response.content.decode()

    assert response.status_code == 200
    assert "version: 0.2.0" in content
    assert "/api/dashboard/summary/:" in content
    assert "/api/dashboard/summary\n" not in content
    assert "/api/requests/{request_pk}/comments/:" in content
    assert "/api/requests/{request_pk}/attachments/:" in content
    assert "entity_id" in content
    assert "page_size" in content
    assert "payload_json" in content
    assert "notificationtemplateid" not in content
