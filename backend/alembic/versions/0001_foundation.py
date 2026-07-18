"""Foundation report lifecycle, tenant RLS, and immutability guards.

Revision ID: 0001_foundation
Revises: None
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

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
    op.create_table(
        "organisations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("external_subject", sa.String(255), nullable=False, unique=True),
        sa.Column("status", sa.String(30), nullable=False),
    )
    op.create_table(
        "organisation_memberships",
        sa.Column(
            "organisation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organisations.id"),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            primary_key=True,
        ),
        sa.Column("role", sa.String(50), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
    )
    op.create_table(
        "projects",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organisation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_code", sa.String(50), nullable=False),
        sa.Column("project_name", sa.String(200), nullable=False),
        sa.Column("well_name", sa.String(200), nullable=False),
        sa.Column("time_zone", sa.String(100), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("unit_set", sa.String(100), nullable=False),
        sa.Column("current_configuration_snapshot_id", postgresql.UUID(as_uuid=True)),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.UniqueConstraint("organisation_id", "project_code"),
    )
    op.create_table(
        "project_memberships",
        sa.Column("organisation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id"),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            primary_key=True,
        ),
        sa.Column("capabilities", postgresql.JSONB(), nullable=False),
    )
    op.create_table(
        "project_configuration_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organisation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id"),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(30), nullable=False),
        sa.Column("data", postgresql.JSONB(), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.UniqueConstraint("project_id", "version_number"),
    )
    op.create_table(
        "project_configuration_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organisation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id"),
            nullable=False,
        ),
        sa.Column(
            "configuration_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("project_configuration_versions.id"),
            nullable=False,
        ),
        sa.Column("schema_version", sa.String(30), nullable=False),
        sa.Column("snapshot_json", postgresql.JSONB(), nullable=False),
        sa.Column("canonical_checksum", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "daily_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organisation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id"),
            nullable=False,
        ),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("shift_code", sa.String(30), nullable=False),
        sa.Column("report_number", sa.String(100), nullable=False),
        sa.Column(
            "active_configuration_snapshot_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("project_configuration_snapshots.id"),
            nullable=False,
        ),
        sa.Column("aggregate_state", sa.String(30), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.UniqueConstraint("project_id", "report_date", "shift_code"),
    )
    op.create_table(
        "daily_report_revisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organisation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id"),
            nullable=False,
        ),
        sa.Column(
            "daily_report_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("daily_reports.id"),
            nullable=False,
        ),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("revision_kind", sa.String(40), nullable=False),
        sa.Column("state", sa.String(30), nullable=False),
        sa.Column("based_on_revision_id", postgresql.UUID(as_uuid=True)),
        sa.Column(
            "configuration_snapshot_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("project_configuration_snapshots.id"),
            nullable=False,
        ),
        sa.Column("data", postgresql.JSONB(), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("submitted_by", postgresql.UUID(as_uuid=True)),
        sa.Column("approved_by", postgresql.UUID(as_uuid=True)),
        sa.Column("rejection_reason", sa.Text()),
        sa.UniqueConstraint("daily_report_id", "revision_number"),
    )
    op.create_table(
        "report_payload_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organisation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id"),
            nullable=False,
        ),
        sa.Column(
            "daily_report_revision_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("daily_report_revisions.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("payload_json", postgresql.JSONB(), nullable=False),
        sa.Column("payload_schema_version", sa.String(30), nullable=False),
        sa.Column("payload_checksum", sa.String(64), nullable=False),
        sa.Column("template_key", sa.String(100), nullable=False),
        sa.Column("template_version", sa.String(30), nullable=False),
    )
    op.create_table(
        "report_decisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organisation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id"),
            nullable=False,
        ),
        sa.Column(
            "daily_report_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("daily_reports.id"),
            nullable=False,
        ),
        sa.Column(
            "daily_report_revision_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("daily_report_revisions.id"),
            nullable=False,
        ),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("acted_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("reason", sa.Text()),
        sa.Column("expected_payload_checksum", sa.String(64)),
        sa.Column("from_state", sa.String(30)),
        sa.Column("to_state", sa.String(30), nullable=False),
    )
    op.create_table(
        "report_exports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organisation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id"),
            nullable=False,
        ),
        sa.Column(
            "payload_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("report_payload_versions.id"),
            nullable=False,
        ),
        sa.Column("export_type", sa.String(10), nullable=False),
        sa.Column("visibility", sa.String(20), nullable=False),
        sa.Column("export_kind", sa.String(20), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("binary_checksum", sa.String(64)),
        sa.Column("template_version", sa.String(30), nullable=False),
        sa.Column("renderer_version", sa.String(100), nullable=False),
    )
    op.create_table(
        "audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organisation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id")),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("entity_type", sa.String(100), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("before_json", postgresql.JSONB()),
        sa.Column("after_json", postgresql.JSONB()),
        sa.Column("reason", sa.Text()),
    )
    op.create_table(
        "idempotency_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organisation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("operation_type", sa.String(100), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("resource_type", sa.String(100), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=False),
        sa.Column("response_json", postgresql.JSONB(), nullable=False),
        sa.UniqueConstraint("organisation_id", "operation_type", "idempotency_key"),
    )

    for table in TENANT_TABLES:
        op.create_index(f"ix_{table}_organisation_id", table, ["organisation_id"])

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
          IF TG_OP = 'UPDATE' THEN
            IF OLD.state IN ('rejected', 'approved', 'superseded', 'cancelled') THEN
              RAISE EXCEPTION 'terminal report revision cannot be changed';
            END IF;

            IF OLD.state = 'submitted' THEN
              IF NEW.state NOT IN ('approved', 'rejected')
                 OR OLD.data IS DISTINCT FROM NEW.data
                 OR OLD.revision_number IS DISTINCT FROM NEW.revision_number
                 OR OLD.revision_kind IS DISTINCT FROM NEW.revision_kind
                 OR OLD.based_on_revision_id IS DISTINCT FROM NEW.based_on_revision_id
                 OR OLD.configuration_snapshot_id IS DISTINCT FROM NEW.configuration_snapshot_id
                 OR OLD.submitted_by IS DISTINCT FROM NEW.submitted_by
                 OR OLD.row_version IS DISTINCT FROM NEW.row_version
                 OR (NEW.state = 'approved' AND (
                   NEW.approved_by IS NULL
                   OR OLD.rejection_reason IS DISTINCT FROM NEW.rejection_reason
                 ))
                 OR (NEW.state = 'rejected' AND (
                   NULLIF(BTRIM(NEW.rejection_reason), '') IS NULL
                   OR OLD.approved_by IS DISTINCT FROM NEW.approved_by
                 )) THEN
                RAISE EXCEPTION 'invalid submitted report revision transition';
              END IF;
            ELSIF OLD.state IN ('draft', 'ready_for_review')
               AND NEW.state NOT IN (OLD.state, 'draft', 'ready_for_review', 'submitted') THEN
              RAISE EXCEPTION 'invalid mutable report revision transition';
            END IF;
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
    for table in reversed(TENANT_TABLES):
        op.drop_table(table)
    op.drop_table("organisation_memberships")
    op.drop_table("users")
    op.drop_table("organisations")
    op.execute("DROP FUNCTION IF EXISTS vantix_guard_revision_mutation()")
    op.execute("DROP FUNCTION IF EXISTS vantix_reject_mutation()")
