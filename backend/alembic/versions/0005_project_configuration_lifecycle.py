"""Add the versioned project-configuration lifecycle.

Revision ID: 0005_project_config_lifecycle
Revises: 0004_harden_revision_transitions
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005_project_config_lifecycle"
down_revision = "0004_harden_revision_transitions"
branch_labels = None
depends_on = None

PROJECT_TABLES = {
    "projects": "id",
    "project_configuration_versions": "project_id",
    "project_configuration_snapshots": "project_id",
    "daily_reports": "project_id",
    "daily_report_revisions": "project_id",
    "report_payload_versions": "project_id",
    "report_decisions": "project_id",
    "report_exports": "project_id",
    "audit_events": "project_id",
}


def _elevated_organisation_role(table: str) -> str:
    return f"""
      EXISTS (
        SELECT 1 FROM organisation_memberships organisation_access
        WHERE organisation_access.organisation_id = {table}.organisation_id
          AND organisation_access.user_id = NULLIF(
            current_setting('app.current_user_id', true), ''
          )::uuid
          AND organisation_access.status = 'active'
          AND organisation_access.role IN ('organisation_admin', 'operations_manager')
      )
    """


def upgrade() -> None:
    for table, column in (
        ("organisations", "created_at"),
        ("project_configuration_snapshots", "created_at"),
        ("report_decisions", "acted_at"),
        ("audit_events", "occurred_at"),
    ):
        op.alter_column(table, column, nullable=False)
    op.add_column("projects", sa.Column("operator_name", sa.String(200)))
    op.add_column("projects", sa.Column("client_name", sa.String(200)))
    op.add_column("projects", sa.Column("rig_name", sa.String(200)))
    op.add_column("projects", sa.Column("location_text", sa.String(500)))
    op.add_column("projects", sa.Column("reporting_start_date", sa.Date()))
    op.add_column(
        "projects",
        sa.Column("status", sa.String(30), nullable=False, server_default="draft"),
    )
    op.add_column(
        "projects", sa.Column("current_configuration_version_id", postgresql.UUID(as_uuid=True))
    )
    op.add_column("project_configuration_versions", sa.Column("effective_from", sa.Date()))
    op.add_column("project_configuration_versions", sa.Column("change_summary", sa.Text()))
    op.add_column(
        "project_configuration_versions",
        sa.Column("created_by", postgresql.UUID(as_uuid=True)),
    )
    op.add_column(
        "project_configuration_versions",
        sa.Column("activated_by", postgresql.UUID(as_uuid=True)),
    )
    op.add_column(
        "project_configuration_versions",
        sa.Column("activated_at", sa.DateTime(timezone=True)),
    )

    op.create_foreign_key(
        "fk_projects_current_configuration_version",
        "projects",
        "project_configuration_versions",
        ["current_configuration_version_id"],
        ["id"],
        use_alter=True,
    )
    op.create_check_constraint(
        "ck_projects_status",
        "projects",
        "status IN ('draft', 'active', 'inactive', 'archived')",
    )
    op.create_check_constraint(
        "ck_project_configuration_state",
        "project_configuration_versions",
        "state IN ('draft', 'active', 'superseded')",
    )
    op.create_unique_constraint(
        "uq_project_configuration_snapshot_version",
        "project_configuration_snapshots",
        ["configuration_version_id"],
    )
    op.create_index(
        "one_active_configuration_per_project",
        "project_configuration_versions",
        ["project_id"],
        unique=True,
        postgresql_where=sa.text("state = 'active'"),
    )
    op.create_foreign_key(
        "fk_projects_current_configuration_snapshot",
        "projects",
        "project_configuration_snapshots",
        ["current_configuration_snapshot_id"],
        ["id"],
        use_alter=True,
    )
    op.execute(
        """
        UPDATE projects AS p
           SET current_configuration_version_id = s.configuration_version_id,
               status = 'active'
          FROM project_configuration_snapshots AS s
         WHERE s.id = p.current_configuration_snapshot_id
        """
    )

    op.execute("DROP POLICY project_memberships_project_scope ON project_memberships")
    op.execute(
        f"""
        CREATE POLICY project_memberships_project_scope
        ON project_memberships AS RESTRICTIVE FOR ALL
        USING (
          user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
          OR project_id::text = ANY(string_to_array(
            NULLIF(current_setting('app.current_project_ids', true), ''), ','
          ))
          OR {_elevated_organisation_role("project_memberships")}
        )
        WITH CHECK (
          user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
          OR project_id::text = ANY(string_to_array(
            NULLIF(current_setting('app.current_project_ids', true), ''), ','
          ))
          OR {_elevated_organisation_role("project_memberships")}
        )
        """
    )
    for table, project_column in PROJECT_TABLES.items():
        membership_scope = f"""
          {project_column}::text = ANY(string_to_array(
            NULLIF(current_setting('app.current_project_ids', true), ''), ','
          ))
          AND EXISTS (
            SELECT 1 FROM project_memberships project_access
            WHERE project_access.project_id = {table}.{project_column}
              AND project_access.user_id = NULLIF(
                current_setting('app.current_user_id', true), ''
              )::uuid
          )
        """
        predicate = f"({_elevated_organisation_role(table)}) OR ({membership_scope})"
        if table == "projects":
            for command in ("SELECT", "UPDATE", "DELETE"):
                op.execute(f"DROP POLICY projects_{command.lower()}_project_scope ON projects")
                op.execute(
                    f"""
                    CREATE POLICY projects_{command.lower()}_project_scope
                    ON projects AS RESTRICTIVE FOR {command}
                    USING ({predicate})
                    """
                )
        else:
            if table == "audit_events":
                predicate = f"project_id IS NULL OR ({predicate})"
            op.execute(f"DROP POLICY {table}_project_scope ON {table}")
            op.execute(
                f"""
                CREATE POLICY {table}_project_scope
                ON {table} AS RESTRICTIVE FOR ALL
                USING ({predicate})
                WITH CHECK ({predicate})
                """
            )
    op.alter_column("projects", "status", server_default=None)

    op.execute(
        """
        CREATE FUNCTION vantix_guard_configuration_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP = 'INSERT' AND NEW.state <> 'draft' THEN
            RAISE EXCEPTION 'project configuration must be created as draft';
          END IF;

          IF TG_OP = 'DELETE' AND OLD.state IN ('active', 'superseded') THEN
            RAISE EXCEPTION 'immutable project configuration cannot be deleted';
          END IF;

          IF TG_OP = 'UPDATE' THEN
            IF OLD.state = 'superseded' THEN
              RAISE EXCEPTION 'superseded project configuration cannot be changed';
            ELSIF OLD.state = 'active' THEN
              IF NEW.state <> 'superseded'
                 OR OLD.data IS DISTINCT FROM NEW.data
                 OR OLD.version_number IS DISTINCT FROM NEW.version_number
                 OR OLD.effective_from IS DISTINCT FROM NEW.effective_from
                 OR OLD.change_summary IS DISTINCT FROM NEW.change_summary
                 OR OLD.created_by IS DISTINCT FROM NEW.created_by
                 OR OLD.activated_by IS DISTINCT FROM NEW.activated_by
                 OR OLD.activated_at IS DISTINCT FROM NEW.activated_at
                 OR OLD.row_version IS DISTINCT FROM NEW.row_version THEN
                RAISE EXCEPTION 'active project configuration is immutable';
              END IF;
            ELSIF OLD.state = 'draft' AND NEW.state NOT IN ('draft', 'active') THEN
              RAISE EXCEPTION 'invalid project configuration transition';
            ELSIF OLD.state = 'draft' AND NEW.state = 'active'
               AND (NEW.activated_by IS NULL OR NEW.activated_at IS NULL) THEN
              RAISE EXCEPTION 'project configuration activation metadata is required';
            END IF;
          END IF;
          RETURN NEW;
        END;
        $$;

        CREATE TRIGGER project_configuration_versions_guard
        BEFORE INSERT OR UPDATE OR DELETE ON project_configuration_versions
        FOR EACH ROW EXECUTE FUNCTION vantix_guard_configuration_mutation();
        """
    )


def downgrade() -> None:
    for table, project_column in PROJECT_TABLES.items():
        if table == "projects":
            for command in ("SELECT", "UPDATE", "DELETE"):
                op.execute(f"DROP POLICY projects_{command.lower()}_project_scope ON projects")
                op.execute(
                    f"""
                    CREATE POLICY projects_{command.lower()}_project_scope
                    ON projects AS RESTRICTIVE FOR {command}
                    USING (
                      id::text = ANY(string_to_array(
                        NULLIF(current_setting('app.current_project_ids', true), ''), ','
                      ))
                      AND EXISTS (
                        SELECT 1 FROM project_memberships membership
                        WHERE membership.project_id = projects.id
                          AND membership.user_id = NULLIF(
                            current_setting('app.current_user_id', true), ''
                          )::uuid
                      )
                    )
                    """
                )
        else:
            nullable_audit = f"({project_column} IS NULL AND '{table}' = 'audit_events') OR "
            predicate = f"""
              {nullable_audit}(
                {project_column}::text = ANY(string_to_array(
                  NULLIF(current_setting('app.current_project_ids', true), ''), ','
                ))
                AND EXISTS (
                  SELECT 1 FROM project_memberships membership
                  WHERE membership.project_id = {table}.{project_column}
                    AND membership.user_id = NULLIF(
                      current_setting('app.current_user_id', true), ''
                    )::uuid
                )
              )
            """
            op.execute(f"DROP POLICY {table}_project_scope ON {table}")
            op.execute(
                f"""
                CREATE POLICY {table}_project_scope
                ON {table} AS RESTRICTIVE FOR ALL
                USING ({predicate})
                WITH CHECK ({predicate})
                """
            )
    op.execute("DROP POLICY project_memberships_project_scope ON project_memberships")
    op.execute(
        """
        CREATE POLICY project_memberships_project_scope
        ON project_memberships AS RESTRICTIVE FOR ALL
        USING (
          user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
          OR project_id::text = ANY(string_to_array(
            NULLIF(current_setting('app.current_project_ids', true), ''), ','
          ))
        )
        WITH CHECK (
          user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
          OR project_id::text = ANY(string_to_array(
            NULLIF(current_setting('app.current_project_ids', true), ''), ','
          ))
        )
        """
    )
    op.execute(
        "DROP TRIGGER IF EXISTS project_configuration_versions_guard "
        "ON project_configuration_versions"
    )
    op.execute("DROP FUNCTION IF EXISTS vantix_guard_configuration_mutation()")
    op.drop_index(
        "one_active_configuration_per_project", table_name="project_configuration_versions"
    )
    op.drop_constraint(
        "uq_project_configuration_snapshot_version",
        "project_configuration_snapshots",
        type_="unique",
    )
    op.drop_constraint(
        "ck_project_configuration_state",
        "project_configuration_versions",
        type_="check",
    )
    op.drop_constraint("ck_projects_status", "projects", type_="check")
    op.drop_constraint("fk_projects_current_configuration_snapshot", "projects", type_="foreignkey")
    op.drop_constraint("fk_projects_current_configuration_version", "projects", type_="foreignkey")
    for column in (
        "activated_at",
        "activated_by",
        "created_by",
        "change_summary",
        "effective_from",
    ):
        op.drop_column("project_configuration_versions", column)
    for column in (
        "current_configuration_version_id",
        "status",
        "reporting_start_date",
        "location_text",
        "rig_name",
        "client_name",
        "operator_name",
    ):
        op.drop_column("projects", column)
    for table, column in (
        ("audit_events", "occurred_at"),
        ("report_decisions", "acted_at"),
        ("project_configuration_snapshots", "created_at"),
        ("organisations", "created_at"),
    ):
        op.alter_column(table, column, nullable=True)
