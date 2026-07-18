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
        "ck_projects_unit_set",
        "projects",
        "unit_set IN ('Metric', 'Field')",
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
    op.create_index(
        "one_draft_configuration_per_project",
        "project_configuration_versions",
        ["project_id"],
        unique=True,
        postgresql_where=sa.text("state = 'draft'"),
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
        CREATE POLICY project_memberships_select_scope
        ON project_memberships AS RESTRICTIVE FOR SELECT
        USING (
          user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
          OR {_elevated_organisation_role("project_memberships")}
        );

        CREATE POLICY project_memberships_insert_scope
        ON project_memberships AS RESTRICTIVE FOR INSERT
        WITH CHECK ({_elevated_organisation_role("project_memberships")});

        CREATE POLICY project_memberships_update_scope
        ON project_memberships AS RESTRICTIVE FOR UPDATE
        USING ({_elevated_organisation_role("project_memberships")})
        WITH CHECK ({_elevated_organisation_role("project_memberships")});

        CREATE POLICY project_memberships_delete_scope
        ON project_memberships AS RESTRICTIVE FOR DELETE
        USING ({_elevated_organisation_role("project_memberships")});
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
            IF OLD.id IS DISTINCT FROM NEW.id
               OR OLD.organisation_id IS DISTINCT FROM NEW.organisation_id
               OR OLD.project_id IS DISTINCT FROM NEW.project_id
               OR OLD.version_number IS DISTINCT FROM NEW.version_number THEN
              RAISE EXCEPTION 'project configuration identity is immutable';
            END IF;
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

    op.execute(
        """
        CREATE FUNCTION vantix_enforce_same_project_ownership()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_TABLE_NAME = 'project_configuration_snapshots' THEN
            PERFORM 1 FROM project_configuration_versions version
             WHERE version.id = NEW.configuration_version_id
               AND version.organisation_id = NEW.organisation_id
               AND version.project_id = NEW.project_id;
            IF NOT FOUND THEN
              RAISE EXCEPTION 'configuration snapshot ownership mismatch';
            END IF;
          ELSIF TG_TABLE_NAME = 'projects' THEN
            IF (NEW.current_configuration_version_id IS NULL)
               <> (NEW.current_configuration_snapshot_id IS NULL) THEN
              RAISE EXCEPTION 'project configuration pointers must be set together';
            END IF;
            IF NEW.current_configuration_version_id IS NOT NULL THEN
              PERFORM 1
                FROM project_configuration_versions version
                JOIN project_configuration_snapshots snapshot
                  ON snapshot.configuration_version_id = version.id
               WHERE version.id = NEW.current_configuration_version_id
                 AND snapshot.id = NEW.current_configuration_snapshot_id
                 AND version.organisation_id = NEW.organisation_id
                 AND snapshot.organisation_id = NEW.organisation_id
                 AND version.project_id = NEW.id
                 AND snapshot.project_id = NEW.id
                 AND version.state = 'active';
              IF NOT FOUND THEN
                RAISE EXCEPTION 'project configuration pointers do not describe one activation';
              END IF;
            END IF;
          ELSIF TG_TABLE_NAME = 'daily_reports' THEN
            PERFORM 1 FROM project_configuration_snapshots snapshot
             WHERE snapshot.id = NEW.active_configuration_snapshot_id
               AND snapshot.organisation_id = NEW.organisation_id
               AND snapshot.project_id = NEW.project_id;
            IF NOT FOUND THEN
              RAISE EXCEPTION 'daily report snapshot ownership mismatch';
            END IF;
          ELSIF TG_TABLE_NAME = 'daily_report_revisions' THEN
            PERFORM 1
              FROM daily_reports report
              JOIN project_configuration_snapshots snapshot
                ON snapshot.id = NEW.configuration_snapshot_id
             WHERE report.id = NEW.daily_report_id
               AND report.organisation_id = NEW.organisation_id
               AND report.project_id = NEW.project_id
               AND snapshot.organisation_id = NEW.organisation_id
               AND snapshot.project_id = NEW.project_id
               AND report.active_configuration_snapshot_id = NEW.configuration_snapshot_id;
            IF NOT FOUND THEN
              RAISE EXCEPTION 'daily report revision ownership mismatch';
            END IF;
          END IF;
          RETURN NEW;
        END;
        $$;

        CREATE CONSTRAINT TRIGGER configuration_snapshots_same_project
        AFTER INSERT OR UPDATE ON project_configuration_snapshots
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION vantix_enforce_same_project_ownership();

        CREATE CONSTRAINT TRIGGER projects_configuration_same_project
        AFTER INSERT OR UPDATE ON projects
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION vantix_enforce_same_project_ownership();

        CREATE CONSTRAINT TRIGGER daily_reports_snapshot_same_project
        AFTER INSERT OR UPDATE ON daily_reports
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION vantix_enforce_same_project_ownership();

        CREATE CONSTRAINT TRIGGER daily_report_revisions_snapshot_same_project
        AFTER INSERT OR UPDATE ON daily_report_revisions
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION vantix_enforce_same_project_ownership();

        CREATE FUNCTION vantix_guard_snapshot_binding()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF OLD.id IS DISTINCT FROM NEW.id
             OR OLD.organisation_id IS DISTINCT FROM NEW.organisation_id THEN
            RAISE EXCEPTION 'record identity and ownership are immutable';
          END IF;
          IF TG_TABLE_NAME <> 'projects' THEN
            IF OLD.project_id IS DISTINCT FROM NEW.project_id THEN
              RAISE EXCEPTION 'record project ownership is immutable';
            END IF;
          END IF;
          IF TG_TABLE_NAME = 'daily_reports' THEN
            IF OLD.active_configuration_snapshot_id IS DISTINCT FROM
               NEW.active_configuration_snapshot_id THEN
              RAISE EXCEPTION 'daily report configuration binding is immutable';
            END IF;
          ELSIF TG_TABLE_NAME = 'daily_report_revisions' THEN
            IF OLD.daily_report_id IS DISTINCT FROM NEW.daily_report_id
               OR OLD.configuration_snapshot_id IS DISTINCT FROM
                  NEW.configuration_snapshot_id THEN
              RAISE EXCEPTION 'daily report revision configuration binding is immutable';
            END IF;
          END IF;
          RETURN NEW;
        END;
        $$;

        CREATE TRIGGER projects_identity_immutable
        BEFORE UPDATE ON projects
        FOR EACH ROW EXECUTE FUNCTION vantix_guard_snapshot_binding();

        CREATE TRIGGER daily_reports_configuration_binding_immutable
        BEFORE UPDATE ON daily_reports
        FOR EACH ROW EXECUTE FUNCTION vantix_guard_snapshot_binding();

        CREATE TRIGGER daily_report_revisions_configuration_binding_immutable
        BEFORE UPDATE ON daily_report_revisions
        FOR EACH ROW EXECUTE FUNCTION vantix_guard_snapshot_binding();
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
    for command in ("select", "insert", "update", "delete"):
        op.execute(f"DROP POLICY project_memberships_{command}_scope ON project_memberships")
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
    for trigger, table in (
        ("projects_identity_immutable", "projects"),
        ("daily_reports_configuration_binding_immutable", "daily_reports"),
        (
            "daily_report_revisions_configuration_binding_immutable",
            "daily_report_revisions",
        ),
        ("configuration_snapshots_same_project", "project_configuration_snapshots"),
        ("projects_configuration_same_project", "projects"),
        ("daily_reports_snapshot_same_project", "daily_reports"),
        ("daily_report_revisions_snapshot_same_project", "daily_report_revisions"),
    ):
        op.execute(f"DROP TRIGGER IF EXISTS {trigger} ON {table}")
    op.execute("DROP FUNCTION IF EXISTS vantix_guard_snapshot_binding()")
    op.execute("DROP FUNCTION IF EXISTS vantix_enforce_same_project_ownership()")
    op.execute("DROP FUNCTION IF EXISTS vantix_guard_configuration_mutation()")
    op.drop_index(
        "one_draft_configuration_per_project",
        table_name="project_configuration_versions",
    )
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
    op.drop_constraint("ck_projects_unit_set", "projects", type_="check")
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
