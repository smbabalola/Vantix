"""Harden immutable report revision state transitions.

Revision ID: 0004_harden_revision_transitions
Revises: 0003_project_membership_roles
"""

from alembic import op

revision = "0004_harden_revision_transitions"
down_revision = "0003_project_membership_roles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
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


def downgrade() -> None:
    op.execute(
        """
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
