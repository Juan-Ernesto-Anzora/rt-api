from django.test import Client

def test_docs_is_public():
    c = Client()
    resp = c.get("/api/docs")
    assert resp.status_code in (200, 302)  # swagger puede redirigir a static ui
