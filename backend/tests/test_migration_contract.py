from pathlib import Path

MIGRATION = Path("backend/alembic/versions/0001_foundation.py").read_text(encoding="utf-8")


def test_vtx_auth_004_005_tenant_tables_enable_and_force_rls() -> None:
    assert "ENABLE ROW LEVEL SECURITY" in MIGRATION
    assert "FORCE ROW LEVEL SECURITY" in MIGRATION
    assert "app.current_org_id" in MIGRATION
    assert "AS RESTRICTIVE" in MIGRATION
    assert "app.current_project_ids" in MIGRATION
    db_adapter = Path("backend/app/db.py").read_text(encoding="utf-8")
    assert "set_config" in db_adapter
    assert "true)" in db_adapter


def test_vtx_api_002_idempotency_is_scoped_by_organisation_and_operation() -> None:
    models = Path("backend/app/models.py").read_text(encoding="utf-8")
    assert 'UniqueConstraint("organisation_id", "operation_type", "idempotency_key")' in models


def test_vtx_mvp_004_006_009_database_immutability_guards_exist() -> None:
    assert "project_configuration_snapshots_immutable" in MIGRATION
    assert "report_payload_versions_immutable" in MIGRATION
    assert "daily_report_revisions_immutable" in MIGRATION


def test_vtx_aud_002_audit_events_are_append_only() -> None:
    assert "audit_events_immutable" in MIGRATION
