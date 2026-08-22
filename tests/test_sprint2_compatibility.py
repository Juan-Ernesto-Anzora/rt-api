from django.urls import resolve


def test_sprint2_slash_and_no_slash_aliases_still_resolve():
    paths = [
        "/api/dashboard/summary",
        "/api/dashboard/summary/",
        "/api/requests/00000000-0000-0000-0000-000000000000/comments",
        "/api/requests/00000000-0000-0000-0000-000000000000/comments/",
        "/api/requests/00000000-0000-0000-0000-000000000000/attachments",
        "/api/requests/00000000-0000-0000-0000-000000000000/attachments/",
    ]

    for path in paths:
        assert resolve(path).func is not None


def test_sprint2_search_and_upload_aliases_remain_available():
    assert resolve("/api/search").url_name == "search"
    assert resolve("/api/search/requests").url_name == "search-requests"
    assert resolve("/api/attachments/init").url_name == "attachments-init"
    assert resolve("/api/attachments/finalize").url_name == "attachments-finalize"
