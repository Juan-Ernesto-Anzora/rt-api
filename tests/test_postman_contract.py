import json
import re
from pathlib import Path

import yaml
from django.test import Client

COLLECTION_PATH = Path("postman/RT-Sprint-3.postman_collection.json")
SPRINT2_COLLECTION_PATH = Path("postman/RT-Sprint-2-Regression.postman_collection.json")
ENVIRONMENT_PATH = Path("postman/RT-Local.postman_environment.json")


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def iter_requests(items):
    for item in items:
        if "request" in item:
            yield item
        yield from iter_requests(item.get("item", []))


def test_collection_has_all_release_gate_folders_and_global_assertions():
    collection = load_json(COLLECTION_PATH)
    folder_names = [item["name"] for item in collection["item"]]

    assert folder_names == [
        "01 Authentication and Tenant",
        "02 Admin Permission Context",
        "03 Audit Pagination and Filters",
        "04 Workflow Administration",
        "05 Users Memberships Roles Permissions",
        "06 Final Admin Safeguards",
        "07 SLA Policy Administration",
        "08 Reports Summary",
        "09 CSV Export",
        "10 Tenant Settings",
        "11 Feature Flags",
        "12 Notification Templates",
        "13 Sprint 2 Request Lifecycle",
        "14 Search Attachments Comments Transitions Notifications",
    ]
    scripts = "\n".join(
        line
        for event in collection["event"]
        for line in event.get("script", {}).get("exec", [])
    )
    assert "No server error" in scripts
    assert "Canonical error envelope" in scripts
    assert "No technical disclosure" in scripts


def test_environment_declares_every_variable_without_secrets():
    collection_text = COLLECTION_PATH.read_text(encoding="utf-8")
    environment = load_json(ENVIRONMENT_PATH)
    values = {item["key"]: item["value"] for item in environment["values"]}
    references = set(re.findall(r"{{([A-Za-z0-9_]+)}}", collection_text))

    assert references <= set(values)
    for secret_key in ("username", "password", "TOKEN", "refresh_token"):
        assert values[secret_key] == ""
    assert values["allow_mutation"] == "false"
    assert "Bearer eyJ" not in collection_text
    assert "YourStrong" not in collection_text
    assert "minio12345" not in collection_text


def test_collection_api_methods_and_paths_exist_in_openapi():
    collection = load_json(COLLECTION_PATH)
    schema = yaml.safe_load(Client().get("/api/schema").content)
    operations = {
        (method.upper(), path)
        for path, path_item in schema["paths"].items()
        for method in path_item
        if method in {"get", "post", "patch", "delete", "put"}
    }
    variable_map = {
        "flow_id": "flow_id",
        "created_flow_id": "flow_id",
        "foreign_flow_id": "flow_id",
        "status_id": "status_id",
        "created_status_id": "status_id",
        "transition_id": "transition_id",
        "user_id": "user_id",
        "membership_id": "membership_id",
        "extra_membership_id": "membership_id",
        "admin_membership_id": "membership_id",
        "role_id": "role_id",
        "admin_role_id": "role_id",
        "permission_code": "permission_code",
        "sla_policy_id": "sla_policy_id",
        "notification_template_id": "template_id",
        "feature_flag_key": "key",
        "request_id": "requestid",
    }

    for item in iter_requests(collection["item"]):
        request = item["request"]
        url = (
            request["url"] if isinstance(request["url"], str) else request["url"]["raw"]
        )
        if not url.startswith("{{base_url}}"):
            assert item["name"] == "PUT Attachment to MinIO"
            continue
        path = url.removeprefix("{{base_url}}").split("?", 1)[0]
        for variable, parameter in variable_map.items():
            path = path.replace("{{" + variable + "}}", "{" + parameter + "}")
        if path.endswith(("/comments/", "/attachments/")):
            path = path.replace("{requestid}", "{request_pk}")
        assert (request["method"], path) in operations, (
            item["name"],
            request["method"],
            path,
        )


def test_every_mutating_admin_request_has_disposable_database_guard():
    collection = load_json(COLLECTION_PATH)
    for item in iter_requests(collection["item"]):
        method = item["request"]["method"]
        url = item["request"]["url"]
        if method not in {"POST", "PATCH", "DELETE", "PUT"}:
            continue
        if "/api/auth/" in url:
            continue
        scripts = "\n".join(
            line
            for event in item.get("event", [])
            if event["listen"] == "prerequest"
            for line in event.get("script", {}).get("exec", [])
        )
        assert "allow_mutation" in scripts, item["name"]


def test_sprint2_regression_collection_is_secret_free_and_uses_current_routes():
    collection = load_json(SPRINT2_COLLECTION_PATH)
    text = SPRINT2_COLLECTION_PATH.read_text(encoding="utf-8")
    names = [item["name"] for item in collection["item"]]

    assert names == [
        "Requests List",
        "Request Detail",
        "Request Bundle",
        "Comments",
        "Attachments",
        "Available Transitions",
        "Dashboard",
        "Search",
    ]
    assert "{{TOKEN}}" in text
    assert "Bearer eyJ" not in text
    assert "password" not in text.lower()
