from pathlib import Path

MIGRATION = Path("backend/alembic/versions/0001_foundation.py").read_text(encoding="utf-8")
MEMBERSHIP_RLS = Path("backend/alembic/versions/0002_membership_bound_rls.py").read_text(
    encoding="utf-8"
)
TRANSITION_GUARD = Path("backend/alembic/versions/0004_harden_revision_transitions.py").read_text(
    encoding="utf-8"
)
CONFIGURATION_LIFECYCLE = Path(
    "backend/alembic/versions/0005_project_configuration_lifecycle.py"
).read_text(encoding="utf-8")


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


def test_vtx_prj_003_004_configuration_lifecycle_is_guarded_and_reversible() -> None:
    assert "project_configuration_versions_guard" in CONFIGURATION_LIFECYCLE
    assert "active project configuration is immutable" in CONFIGURATION_LIFECYCLE
    downgrade = CONFIGURATION_LIFECYCLE.split("def downgrade()", maxsplit=1)[1]
    assert "DROP TRIGGER IF EXISTS project_configuration_versions_guard" in downgrade
    assert "DROP FUNCTION IF EXISTS vantix_guard_configuration_mutation()" in downgrade


def test_vtx_auth_006_membership_rls_never_trusts_context_project_ids() -> None:
    assert "project_memberships_select_scope" in CONFIGURATION_LIFECYCLE
    assert "project_memberships_insert_scope" in CONFIGURATION_LIFECYCLE
    select_policy = CONFIGURATION_LIFECYCLE.split(
        "CREATE POLICY project_memberships_select_scope", maxsplit=1
    )[1].split("CREATE POLICY project_memberships_insert_scope", maxsplit=1)[0]
    assert "app.current_project_ids" not in select_policy


def test_vtx_prj_003_same_project_constraint_triggers_are_reversible() -> None:
    assert "vantix_enforce_same_project_ownership" in CONFIGURATION_LIFECYCLE
    assert "daily_report_revisions_snapshot_same_project" in CONFIGURATION_LIFECYCLE
    downgrade = CONFIGURATION_LIFECYCLE.split("def downgrade()", maxsplit=1)[1]
    assert "DROP FUNCTION IF EXISTS vantix_enforce_same_project_ownership()" in downgrade
