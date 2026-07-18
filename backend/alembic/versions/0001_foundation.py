"""Foundation report lifecycle, tenant RLS, and immutability guards.

Revision ID: 0001_foundation
Revises: None
"""

from alembic import op
from app import models  # noqa: F401
from app.db import Base

revision = "0001_foundation"
down_revision = None
branch_labels = None
depends_on = None

TENANT_TABLES = (
    "projects",
    "project_memberships",
    "project_configuration_versions",
    "project_configuration_snapshots",
    "daily_reports",
    "daily_report_revisions",
    "report_payload_versions",
    "report_decisions",
    "report_exports",
    "audit_events",
    "idempotency_records",
)

PROJECT_TABLE_EXPRESSIONS = {
    "projects": "id",
    "project_memberships": "project_id",
    "project_configuration_versions": "project_id",
    "project_configuration_snapshots": "project_id",
    "daily_reports": "project_id",
    "daily_report_revisions": "project_id",
    "report_payload_versions": "project_id",
    "report_decisions": "project_id",
    "report_exports": "project_id",
    "audit_events": "project_id",
}


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)

    op.execute(
        """
        CREATE OR REPLACE FUNCTION vantix_reject_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          RAISE EXCEPTION 'immutable Vantix record cannot be changed';
        END;
        $$;

        CREATE OR REPLACE FUNCTION vantix_guard_revision_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP = 'DELETE'
             AND OLD.state IN (
               'submitted', 'rejected', 'approved', 'superseded', 'cancelled'
             ) THEN
            RAISE EXCEPTION 'immutable report revision cannot be changed';
          END IF;
          IF TG_OP = 'UPDATE'
             AND OLD.state IN ('submitted', 'rejected', 'approved', 'superseded', 'cancelled')
             AND (
               OLD.data IS DISTINCT FROM NEW.data
               OR OLD.revision_number IS DISTINCT FROM NEW.revision_number
               OR OLD.revision_kind IS DISTINCT FROM NEW.revision_kind
               OR OLD.based_on_revision_id IS DISTINCT FROM NEW.based_on_revision_id
               OR OLD.configuration_snapshot_id IS DISTINCT FROM NEW.configuration_snapshot_id
               OR OLD.submitted_by IS DISTINCT FROM NEW.submitted_by
             ) THEN
            RAISE EXCEPTION 'immutable report revision content cannot be changed';
          END IF;
          RETURN NEW;
        END;
        $$;
        """
    )

    for table in TENANT_TABLES:
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        op.execute(
            f"""
            CREATE POLICY {table}_tenant_policy ON "{table}"
            USING (
              organisation_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid
              OR current_setting('app.is_system_service', true) = 'true'
            )
            WITH CHECK (
              organisation_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid
              OR current_setting('app.is_system_service', true) = 'true'
            )
            """
        )

    project_list = (
        "string_to_array(NULLIF(current_setting('app.current_project_ids', true), ''), ',')"
    )
    for table, project_column in PROJECT_TABLE_EXPRESSIONS.items():
        if table == "projects":
            for command in ("SELECT", "UPDATE", "DELETE"):
                op.execute(
                    f"""
                    CREATE POLICY {table}_{command.lower()}_project_scope
                    ON "{table}" AS RESTRICTIVE FOR {command}
                    USING (
                      {project_column}::text = ANY({project_list})
                      OR current_setting('app.is_system_service', true) = 'true'
                    )
                    """
                )
            continue
        op.execute(
            f"""
            CREATE POLICY {table}_project_scope
            ON "{table}" AS RESTRICTIVE FOR ALL
            USING (
              ({project_column} IS NULL AND '{table}' = 'audit_events')
              OR {project_column}::text = ANY({project_list})
              OR current_setting('app.is_system_service', true) = 'true'
            )
            WITH CHECK (
              ({project_column} IS NULL AND '{table}' = 'audit_events')
              OR {project_column}::text = ANY({project_list})
              OR current_setting('app.is_system_service', true) = 'true'
            )
            """
        )

    op.execute(
        """
        CREATE TRIGGER project_configuration_snapshots_immutable
        BEFORE UPDATE OR DELETE ON project_configuration_snapshots
        FOR EACH ROW EXECUTE FUNCTION vantix_reject_mutation();

        CREATE TRIGGER report_payload_versions_immutable
        BEFORE UPDATE OR DELETE ON report_payload_versions
        FOR EACH ROW EXECUTE FUNCTION vantix_reject_mutation();

        CREATE TRIGGER audit_events_immutable
        BEFORE UPDATE OR DELETE ON audit_events
        FOR EACH ROW EXECUTE FUNCTION vantix_reject_mutation();

        CREATE TRIGGER daily_report_revisions_immutable
        BEFORE UPDATE OR DELETE ON daily_report_revisions
        FOR EACH ROW EXECUTE FUNCTION vantix_guard_revision_mutation();

        CREATE UNIQUE INDEX one_mutable_draft_per_report
        ON daily_report_revisions (daily_report_id)
        WHERE state IN ('draft', 'ready_for_review');

        CREATE UNIQUE INDEX one_current_submission_per_report
        ON daily_report_revisions (daily_report_id)
        WHERE state = 'submitted';
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
    op.execute("DROP FUNCTION IF EXISTS vantix_guard_revision_mutation()")
    op.execute("DROP FUNCTION IF EXISTS vantix_reject_mutation()")
