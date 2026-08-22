from pathlib import Path


def test_sprint3_upgrades_are_idempotent_and_ordered_in_docs():
    docs = Path("docs/sprint-3-api-verification.md").read_text(encoding="utf-8")
    expected = [
        "upgrade-sprint3-admin-workflows.sql",
        "upgrade-sprint3-admin-users-roles.sql",
        "upgrade-sprint3-sla-reports.sql",
        "upgrade-sprint3-admin-settings.sql",
        "upgrade-sprint3-api-polish.sql",
    ]
    positions = [docs.index(name) for name in expected]

    assert positions == sorted(positions)
    polish = Path("db/upgrade-sprint3-api-polish.sql").read_text(encoding="utf-8")
    assert "IF NOT EXISTS" in polish
    assert "IX_Activity_TenantCreated" in polish
    assert "INSERT" not in polish
    assert "UPDATE " not in polish
    assert "DELETE " not in polish


def test_tracked_environment_example_contains_placeholders_not_old_credentials():
    settings = Path("rt_api/settings.py").read_text(encoding="utf-8")
    example = Path(".env.example").read_text(encoding="utf-8")
    combined = settings + example

    for old_value in ("srctpassW12345", "YourStrong!Passw0rd", "minio12345"):
        assert old_value not in combined
    assert "replace-with-" in example
    assert 'DB_PASSWORD = os.getenv("DB_PASSWORD", "")' in settings
