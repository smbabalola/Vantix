from pathlib import Path

MIGRATION = Path("backend/alembic/versions/0001_foundation.py").read_text(encoding="utf-8")
MEMBERSHIP_RLS = Path("backend/alembic/versions/0002_membership_bound_rls.py").read_text(
    encoding="utf-8"
)
TRANSITION_GUARD = Path("backend/alembic/versions/0004_harden_revision_transitions.py").read_text(
    encoding="utf-8"
)


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


def test_vtx_mvp_001_migration_history_is_self_contained_and_reversible() -> None:
    assert "Base.metadata" not in MIGRATION
    assert "op.create_table" in MIGRATION
    assert "ORIGINAL_PROJECT_TABLES" in MEMBERSHIP_RLS
    assert "CREATE POLICY" in MEMBERSHIP_RLS.split("def downgrade()", maxsplit=1)[1]


def test_vtx_mvp_006_terminal_state_transition_guard_is_installed() -> None:
    assert "terminal report revision cannot be changed" in TRANSITION_GUARD
    assert "NEW.state NOT IN ('approved', 'rejected')" in TRANSITION_GUARD
