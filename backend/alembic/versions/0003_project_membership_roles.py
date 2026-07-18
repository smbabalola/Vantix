"""Add explicit project role used by client visibility policy.

Revision ID: 0003_project_membership_roles
Revises: 0002_membership_bound_rls
"""

from alembic import op

revision = "0003_project_membership_roles"
down_revision = "0002_membership_bound_rls"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # IF NOT EXISTS preserves upgrade compatibility for databases created while
    # the former 0001 migration was still coupled to then-current ORM metadata.
    op.execute(
        "ALTER TABLE project_memberships "
        "ADD COLUMN IF NOT EXISTS role VARCHAR(50) "
        "NOT NULL DEFAULT 'report_editor'"
    )
    op.alter_column("project_memberships", "role", server_default=None)


def downgrade() -> None:
    op.drop_column("project_memberships", "role")
