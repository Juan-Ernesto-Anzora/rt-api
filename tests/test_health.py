from django.test import Client


def test_health_ok():
    c = Client()
    resp = c.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
