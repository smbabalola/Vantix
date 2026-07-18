"""Bind organisation and project RLS to active membership rows.

Revision ID: 0002_membership_bound_rls
Revises: 0001_foundation
"""

from alembic import op

revision = "0002_membership_bound_rls"
down_revision = "0001_foundation"
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

ORIGINAL_PROJECT_TABLES = {
    "projects": "id",
    "project_memberships": "project_id",
    **{table: column for table, column in PROJECT_TABLES.items() if table != "projects"},
}


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE users ENABLE ROW LEVEL SECURITY;
        ALTER TABLE users FORCE ROW LEVEL SECURITY;
        CREATE POLICY users_self_policy ON users
        USING (id = NULLIF(current_setting('app.current_user_id', true), '')::uuid)
        WITH CHECK (id = NULLIF(current_setting('app.current_user_id', true), '')::uuid);

        ALTER TABLE organisation_memberships ENABLE ROW LEVEL SECURITY;
        ALTER TABLE organisation_memberships FORCE ROW LEVEL SECURITY;
        CREATE POLICY organisation_memberships_self_policy ON organisation_memberships
        USING (
          user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
          AND organisation_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid
        )
        WITH CHECK (
          user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
          AND organisation_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid
        );

        ALTER TABLE organisations ENABLE ROW LEVEL SECURITY;
        ALTER TABLE organisations FORCE ROW LEVEL SECURITY;
        CREATE POLICY organisations_membership_policy ON organisations
        USING (
          id = NULLIF(current_setting('app.current_org_id', true), '')::uuid
          AND EXISTS (
            SELECT 1 FROM organisation_memberships membership
            WHERE membership.organisation_id = organisations.id
              AND membership.user_id = NULLIF(
                current_setting('app.current_user_id', true), ''
              )::uuid
              AND membership.status = 'active'
            )
        )
        WITH CHECK (
          id = NULLIF(current_setting('app.current_org_id', true), '')::uuid
        );
        """
    )

    for table in TENANT_TABLES:
        op.execute(
            f"""
            CREATE POLICY {table}_active_membership
            ON "{table}" AS RESTRICTIVE FOR ALL
            USING (
              EXISTS (
                SELECT 1 FROM organisation_memberships membership
                WHERE membership.organisation_id = "{table}".organisation_id
                  AND membership.user_id = NULLIF(
                    current_setting('app.current_user_id', true), ''
                  )::uuid
                  AND membership.status = 'active'
              )
            )
            WITH CHECK (
              EXISTS (
                SELECT 1 FROM organisation_memberships membership
                WHERE membership.organisation_id = "{table}".organisation_id
                  AND membership.user_id = NULLIF(
                    current_setting('app.current_user_id', true), ''
                  )::uuid
                  AND membership.status = 'active'
              )
            )
            """
        )

    op.execute("DROP POLICY project_memberships_project_scope ON project_memberships")
    op.execute(
        """
        CREATE POLICY project_memberships_project_scope
        ON project_memberships AS RESTRICTIVE FOR ALL
        USING (
          user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
          OR project_id::text = ANY(
            string_to_array(
              NULLIF(current_setting('app.current_project_ids', true), ''), ','
            )
          )
        )
        WITH CHECK (
          user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
          OR project_id::text = ANY(
            string_to_array(
              NULLIF(current_setting('app.current_project_ids', true), ''), ','
            )
          )
        );
        """
    )

    for table, project_column in PROJECT_TABLES.items():
        if table == "projects":
            for command in ("SELECT", "UPDATE", "DELETE"):
                op.execute(f"DROP POLICY {table}_{command.lower()}_project_scope ON {table}")
                op.execute(
                    f"""
                    CREATE POLICY {table}_{command.lower()}_project_scope
                    ON {table} AS RESTRICTIVE FOR {command}
                    USING (
                      id::text = ANY(
                        string_to_array(
                          NULLIF(current_setting('app.current_project_ids', true), ''), ','
                        )
                      )
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
            continue
        op.execute(f"DROP POLICY {table}_project_scope ON {table}")
        nullable_audit = f"({project_column} IS NULL AND '{table}' = 'audit_events') OR "
        predicate = f"""
          {nullable_audit}(
            {project_column}::text = ANY(
              string_to_array(
                NULLIF(current_setting('app.current_project_ids', true), ''), ','
              )
            )
            AND EXISTS (
              SELECT 1 FROM project_memberships membership
              WHERE membership.project_id = {table}.{project_column}
                AND membership.user_id = NULLIF(
                  current_setting('app.current_user_id', true), ''
                )::uuid
            )
          )
        """
        op.execute(
            f"""
            CREATE POLICY {table}_project_scope
            ON {table} AS RESTRICTIVE FOR ALL
            USING ({predicate})
            WITH CHECK ({predicate})
            """
        )


def downgrade() -> None:
    for table in PROJECT_TABLES:
        if table == "projects":
            for command in ("SELECT", "UPDATE", "DELETE"):
                op.execute(f"DROP POLICY {table}_{command.lower()}_project_scope ON {table}")
            continue
        op.execute(f"DROP POLICY {table}_project_scope ON {table}")
    op.execute("DROP POLICY project_memberships_project_scope ON project_memberships")
    for table in TENANT_TABLES:
        op.execute(f"DROP POLICY {table}_active_membership ON {table}")

    project_list = (
        "string_to_array(NULLIF(current_setting('app.current_project_ids', true), ''), ',')"
    )
    for table, project_column in ORIGINAL_PROJECT_TABLES.items():
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
    op.execute("DROP POLICY organisations_membership_policy ON organisations")
    op.execute("DROP POLICY organisation_memberships_self_policy ON organisation_memberships")
    op.execute("DROP POLICY users_self_policy ON users")
    op.execute("ALTER TABLE organisations DISABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE organisation_memberships DISABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE users DISABLE ROW LEVEL SECURITY")
