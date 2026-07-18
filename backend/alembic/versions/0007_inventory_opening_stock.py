# ruff: noqa: E501
"""Add immutable opening-stock postings and inventory ledger lines.

Revision ID: 0007_inventory_opening_stock
Revises: 0006_project_products_pricing
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0007_inventory_opening_stock"
down_revision = "0006_project_products_pricing"
branch_labels = None
depends_on = None


def _elevated(table: str) -> str:
    return f"""EXISTS (SELECT 1 FROM organisation_memberships access
      WHERE access.organisation_id = {table}.organisation_id
        AND access.user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
        AND access.status = 'active'
        AND access.role IN ('organisation_admin', 'operations_manager'))"""


def _member(table: str, capability: str) -> str:
    return f"""EXISTS (SELECT 1 FROM project_memberships access
      WHERE access.project_id = {table}.project_id
        AND access.user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
        AND access.capabilities ? '{capability}')"""


def upgrade() -> None:
    op.create_table(
        "inventory_postings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organisation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "source_configuration_snapshot_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("posting_type", sa.String(30), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("posting_date", sa.Date(), nullable=False),
        sa.Column("reversal_of_posting_id", postgresql.UUID(as_uuid=True)),
        sa.Column("reason", sa.Text()),
        sa.Column("posted_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "posted_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(
            ["source_configuration_snapshot_id"], ["project_configuration_snapshots.id"]
        ),
        sa.ForeignKeyConstraint(["reversal_of_posting_id"], ["inventory_postings.id"]),
        sa.UniqueConstraint("reversal_of_posting_id", name="uq_inventory_postings_reversal"),
        sa.CheckConstraint(
            "posting_type IN ('opening_stock','reversal')", name="ck_inventory_postings_type"
        ),
        sa.CheckConstraint("status IN ('building','posted')", name="ck_inventory_postings_status"),
        sa.CheckConstraint(
            "(posting_type = 'opening_stock' AND reversal_of_posting_id IS NULL) OR "
            "(posting_type = 'reversal' AND reversal_of_posting_id IS NOT NULL "
            "AND reason IS NOT NULL AND btrim(reason) <> '')",
            name="ck_inventory_postings_reversal_context",
        ),
    )
    op.create_index(
        "ix_inventory_postings_project_date", "inventory_postings", ["project_id", "posting_date"]
    )
    op.create_index(
        "ix_inventory_postings_organisation_id", "inventory_postings", ["organisation_id"]
    )

    op.create_table(
        "inventory_ledger_lines",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organisation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("posting_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_definition_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "configuration_product_version_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("product_price_version_id", postgresql.UUID(as_uuid=True)),
        sa.Column("entered_quantity", sa.Numeric(24, 12), nullable=False),
        sa.Column("entered_unit_code", sa.String(20), nullable=False),
        sa.Column("canonical_signed_quantity", sa.Numeric(30, 12), nullable=False),
        sa.Column("canonical_unit_code", sa.String(20), nullable=False),
        sa.Column("price_status", sa.String(20), nullable=False),
        sa.Column("applied_unit_price", sa.Numeric(24, 12)),
        sa.Column("price_basis_unit_code", sa.String(20)),
        sa.Column("price_effective_from", sa.Date()),
        sa.Column("price_effective_to", sa.Date()),
        sa.Column("currency", sa.String(3)),
        sa.Column("currency_minor_unit_scale", sa.Integer()),
        sa.Column("posted_line_amount", sa.Numeric(30, 12)),
        sa.Column("frozen_product_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["posting_id"], ["inventory_postings.id"]),
        sa.ForeignKeyConstraint(["product_definition_id"], ["project_product_definitions.id"]),
        sa.ForeignKeyConstraint(["configuration_product_version_id"], ["project_products.id"]),
        sa.ForeignKeyConstraint(["product_price_version_id"], ["product_price_history.id"]),
        sa.UniqueConstraint(
            "posting_id", "product_definition_id", name="uq_inventory_line_product"
        ),
        sa.CheckConstraint(
            "price_status IN ('ready','unavailable')", name="ck_inventory_lines_price_status"
        ),
        sa.CheckConstraint(
            "(price_status = 'ready' AND product_price_version_id IS NOT NULL AND "
            "applied_unit_price IS NOT NULL AND price_basis_unit_code IS NOT NULL AND "
            "price_effective_from IS NOT NULL AND currency IS NOT NULL AND "
            "currency_minor_unit_scale IS NOT NULL AND posted_line_amount IS NOT NULL) OR "
            "(price_status = 'unavailable' AND product_price_version_id IS NULL AND "
            "applied_unit_price IS NULL AND price_basis_unit_code IS NULL AND "
            "price_effective_from IS NULL AND price_effective_to IS NULL AND currency IS NULL "
            "AND currency_minor_unit_scale IS NULL AND posted_line_amount IS NULL)",
            name="ck_inventory_lines_price_completeness",
        ),
        sa.CheckConstraint(
            "entered_unit_code IN ('kg','t','lb','L','m3','gal_us','bbl','each','package')",
            name="ck_inventory_lines_entered_unit",
        ),
        sa.CheckConstraint(
            "canonical_unit_code IN ('kg','L','each')", name="ck_inventory_lines_canonical_unit"
        ),
    )
    op.create_index(
        "ix_inventory_ledger_lines_organisation_id", "inventory_ledger_lines", ["organisation_id"]
    )
    op.create_index(
        "ix_inventory_ledger_lines_product", "inventory_ledger_lines", ["product_definition_id"]
    )

    for table in ("inventory_postings", "inventory_ledger_lines"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY {table}_tenant_policy ON {table}
            USING (organisation_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid
              OR current_setting('app.is_system_service', true) = 'true')
            WITH CHECK (organisation_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid
              OR current_setting('app.is_system_service', true) = 'true');
            CREATE POLICY {table}_select_scope ON {table} AS RESTRICTIVE FOR SELECT USING (
              {_elevated(table)} OR {_member(table, "view_inventory")}
              OR {_member(table, "post_inventory")}
              OR current_setting('app.is_system_service', true) = 'true');
            CREATE POLICY {table}_insert_scope ON {table} AS RESTRICTIVE FOR INSERT WITH CHECK (
              {_elevated(table)} OR {_member(table, "post_inventory")}
              OR current_setting('app.is_system_service', true) = 'true');
            CREATE POLICY {table}_update_scope ON {table} AS RESTRICTIVE FOR UPDATE
            USING ({_elevated(table)} OR {_member(table, "post_inventory")}
              OR current_setting('app.is_system_service', true) = 'true')
            WITH CHECK ({_elevated(table)} OR {_member(table, "post_inventory")}
              OR current_setting('app.is_system_service', true) = 'true');
            CREATE POLICY {table}_delete_scope ON {table} AS RESTRICTIVE FOR DELETE USING (
              {_elevated(table)} OR {_member(table, "post_inventory")}
              OR current_setting('app.is_system_service', true) = 'true');
            """
        )

    op.execute(
        """
        CREATE FUNCTION vantix_guard_inventory_posting() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE source_project uuid; source_org uuid; current_snapshot uuid;
          original inventory_postings%ROWTYPE;
        BEGIN
          IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'posted inventory is append-only'; END IF;
          IF TG_OP = 'UPDATE' THEN
            IF OLD.status = 'building' AND NEW.status = 'posted'
               AND OLD.id = NEW.id AND OLD.organisation_id = NEW.organisation_id
               AND OLD.project_id = NEW.project_id
               AND OLD.source_configuration_snapshot_id = NEW.source_configuration_snapshot_id
               AND OLD.posting_type = NEW.posting_type AND OLD.posting_date = NEW.posting_date
               AND OLD.reversal_of_posting_id IS NOT DISTINCT FROM NEW.reversal_of_posting_id
               AND OLD.reason IS NOT DISTINCT FROM NEW.reason AND OLD.posted_by = NEW.posted_by THEN
              NULL;
            ELSE
              RAISE EXCEPTION 'posted inventory is append-only';
            END IF;
          END IF;
          SELECT project_id, organisation_id INTO source_project, source_org
            FROM project_configuration_snapshots WHERE id = NEW.source_configuration_snapshot_id;
          IF source_project IS DISTINCT FROM NEW.project_id OR source_org IS DISTINCT FROM NEW.organisation_id THEN
            RAISE EXCEPTION 'inventory snapshot ownership mismatch';
          END IF;
          SELECT current_configuration_snapshot_id INTO current_snapshot
            FROM projects WHERE id = NEW.project_id AND organisation_id = NEW.organisation_id
            FOR UPDATE;
          PERFORM pg_advisory_xact_lock(hashtextextended(NEW.project_id::text, 0));
          IF NEW.posting_type = 'opening_stock' THEN
            IF NEW.source_configuration_snapshot_id IS DISTINCT FROM current_snapshot THEN
              RAISE EXCEPTION 'opening stock requires the current configuration snapshot';
            END IF;
          ELSE
            SELECT * INTO original FROM inventory_postings WHERE id = NEW.reversal_of_posting_id;
            IF NOT FOUND OR original.project_id <> NEW.project_id OR original.organisation_id <> NEW.organisation_id
               OR original.posting_type <> 'opening_stock' OR original.status <> 'posted'
               OR NEW.posting_date < original.posting_date
               OR NEW.source_configuration_snapshot_id <> original.source_configuration_snapshot_id THEN
              RAISE EXCEPTION 'invalid inventory reversal target';
            END IF;
          END IF;
          RETURN NEW;
        END; $$;

        CREATE TRIGGER inventory_postings_guard BEFORE INSERT OR UPDATE OR DELETE ON inventory_postings
          FOR EACH ROW EXECUTE FUNCTION vantix_guard_inventory_posting();

        CREATE FUNCTION vantix_guard_inventory_line() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
          parent inventory_postings%ROWTYPE;
          product project_products%ROWTYPE;
          definition project_product_definitions%ROWTYPE;
          price product_price_history%ROWTYPE;
          original_line inventory_ledger_lines%ROWTYPE;
          snapshot_configuration_id uuid;
          entered_factor numeric;
          package_factor numeric;
          basis_factor numeric;
          expected_canonical numeric;
          expected_amount numeric;
          expected_scale integer;
          package_dimension text;
          entered_dimension text;
        BEGIN
          IF TG_OP <> 'INSERT' THEN RAISE EXCEPTION 'inventory ledger lines are immutable'; END IF;
          SELECT * INTO parent FROM inventory_postings WHERE id = NEW.posting_id;
          IF NOT FOUND OR parent.status <> 'building' OR parent.project_id <> NEW.project_id
             OR parent.organisation_id <> NEW.organisation_id THEN
            RAISE EXCEPTION 'ledger lines require a matching building posting';
          END IF;
          SELECT configuration_version_id INTO snapshot_configuration_id
            FROM project_configuration_snapshots
           WHERE id = parent.source_configuration_snapshot_id;
          SELECT * INTO product FROM project_products WHERE id = NEW.configuration_product_version_id;
          SELECT * INTO definition FROM project_product_definitions WHERE id = NEW.product_definition_id;
          IF product.id IS NULL OR definition.id IS NULL
             OR product.configuration_version_id <> snapshot_configuration_id
             OR product.product_definition_id <> NEW.product_definition_id
             OR product.project_id <> NEW.project_id OR definition.project_id <> NEW.project_id
             OR product.organisation_id <> NEW.organisation_id
             OR definition.organisation_id <> NEW.organisation_id
             OR NOT product.inventory_applicable OR NOT product.active THEN
            RAISE EXCEPTION 'inventory product or snapshot authority mismatch';
          END IF;

          IF NEW.frozen_product_json ->> 'item_code' IS DISTINCT FROM product.item_code
             OR NEW.frozen_product_json ->> 'item_name' IS DISTINCT FROM product.item_name
             OR NEW.frozen_product_json ->> 'alternate_name' IS DISTINCT FROM product.alternate_name
             OR NEW.frozen_product_json ->> 'packaging' IS DISTINCT FROM product.packaging
             OR (NEW.frozen_product_json ->> 'package_size')::numeric <> product.package_size
             OR NEW.frozen_product_json ->> 'package_unit_code' <> product.package_unit_code
             OR NEW.frozen_product_json ->> 'inventory_unit_code' IS DISTINCT FROM product.inventory_unit_code
             OR NULLIF(NEW.frozen_product_json ->> 'specific_gravity', '')::numeric
                IS DISTINCT FROM product.specific_gravity THEN
            RAISE EXCEPTION 'frozen product authority mismatch';
          END IF;

          package_factor := CASE product.package_unit_code
            WHEN 'kg' THEN 1 WHEN 't' THEN 1000 WHEN 'lb' THEN 0.45359237
            WHEN 'L' THEN 1 WHEN 'm3' THEN 1000 WHEN 'gal_us' THEN 3.785411784
            WHEN 'bbl' THEN 158.987294928 WHEN 'each' THEN 1 END;
          package_dimension := CASE
            WHEN product.package_unit_code IN ('kg','t','lb') THEN 'mass'
            WHEN product.package_unit_code IN ('L','m3','gal_us','bbl') THEN 'volume'
            ELSE 'count' END;
          entered_factor := CASE NEW.entered_unit_code
            WHEN 'kg' THEN 1 WHEN 't' THEN 1000 WHEN 'lb' THEN 0.45359237
            WHEN 'L' THEN 1 WHEN 'm3' THEN 1000 WHEN 'gal_us' THEN 3.785411784
            WHEN 'bbl' THEN 158.987294928 WHEN 'each' THEN 1 END;
          entered_dimension := CASE
            WHEN NEW.entered_unit_code IN ('kg','t','lb') THEN 'mass'
            WHEN NEW.entered_unit_code IN ('L','m3','gal_us','bbl') THEN 'volume'
            WHEN NEW.entered_unit_code = 'each' THEN 'count' ELSE 'package' END;
          IF NEW.entered_unit_code <> 'package' AND entered_dimension <> package_dimension THEN
            RAISE EXCEPTION 'entered inventory unit dimension mismatch';
          END IF;
          expected_canonical := CASE WHEN NEW.entered_unit_code = 'package'
            THEN NEW.entered_quantity * product.package_size * package_factor
            ELSE NEW.entered_quantity * entered_factor END;
          expected_canonical := round(expected_canonical, 12);
          IF NEW.canonical_signed_quantity <> expected_canonical
             OR NEW.canonical_unit_code <> (CASE package_dimension
               WHEN 'mass' THEN 'kg' WHEN 'volume' THEN 'L' ELSE 'each' END) THEN
            RAISE EXCEPTION 'canonical inventory quantity mismatch';
          END IF;

          IF parent.posting_type = 'opening_stock' THEN
            IF NEW.entered_quantity <= 0 OR NEW.canonical_signed_quantity <= 0 THEN
              RAISE EXCEPTION 'opening quantity must be positive';
            END IF;
            PERFORM pg_advisory_xact_lock(hashtextextended(NEW.product_definition_id::text, 0));
            IF EXISTS (
              SELECT 1 FROM inventory_ledger_lines existing_line
              JOIN inventory_postings opening ON opening.id = existing_line.posting_id
              WHERE existing_line.product_definition_id = NEW.product_definition_id
                AND opening.project_id = NEW.project_id
                AND opening.posting_type = 'opening_stock' AND opening.status = 'posted'
                AND NOT EXISTS (SELECT 1 FROM inventory_postings reversal
                  WHERE reversal.reversal_of_posting_id = opening.id
                    AND reversal.status = 'posted')) THEN
              RAISE EXCEPTION 'product already has unreversed opening stock';
            END IF;

            IF NEW.price_status = 'ready' THEN
              SELECT * INTO price FROM product_price_history WHERE id = NEW.product_price_version_id;
              IF NOT FOUND OR price.project_product_id <> product.id
                 OR price.project_id <> NEW.project_id OR price.organisation_id <> NEW.organisation_id
                 OR price.effective_from > parent.posting_date
                 OR (price.effective_to IS NOT NULL AND price.effective_to <= parent.posting_date)
                 OR NEW.applied_unit_price <> price.unit_price
                 OR NEW.price_basis_unit_code <> price.price_basis_unit_code
                 OR NEW.price_effective_from <> price.effective_from
                 OR NEW.price_effective_to IS DISTINCT FROM price.effective_to
                 OR NEW.currency <> price.currency THEN
                RAISE EXCEPTION 'frozen price authority mismatch';
              END IF;
              expected_scale := CASE price.currency
                WHEN 'BIF' THEN 0 WHEN 'CLF' THEN 4 WHEN 'CLP' THEN 0
                WHEN 'DJF' THEN 0 WHEN 'GNF' THEN 0 WHEN 'ISK' THEN 0
                WHEN 'JPY' THEN 0 WHEN 'KMF' THEN 0 WHEN 'KRW' THEN 0
                WHEN 'PYG' THEN 0 WHEN 'RWF' THEN 0 WHEN 'UGX' THEN 0
                WHEN 'UYI' THEN 0 WHEN 'UYW' THEN 4 WHEN 'VND' THEN 0
                WHEN 'VUV' THEN 0 WHEN 'XAF' THEN 0 WHEN 'XOF' THEN 0
                WHEN 'XPF' THEN 0 WHEN 'BHD' THEN 3 WHEN 'IQD' THEN 3
                WHEN 'JOD' THEN 3 WHEN 'KWD' THEN 3 WHEN 'LYD' THEN 3
                WHEN 'OMR' THEN 3 WHEN 'TND' THEN 3 ELSE 2 END;
              IF NEW.currency_minor_unit_scale <> expected_scale THEN
                RAISE EXCEPTION 'currency minor-unit scale mismatch';
              END IF;
              basis_factor := CASE price.price_basis_unit_code
                WHEN 'kg' THEN 1 WHEN 't' THEN 1000 WHEN 'lb' THEN 0.45359237
                WHEN 'L' THEN 1 WHEN 'm3' THEN 1000 WHEN 'gal_us' THEN 3.785411784
                WHEN 'bbl' THEN 158.987294928 WHEN 'each' THEN 1 END;
              expected_amount := CASE WHEN price.price_basis_unit_code = 'package'
                THEN expected_canonical / (product.package_size * package_factor) * price.unit_price
                ELSE expected_canonical / basis_factor * price.unit_price END;
              IF NEW.posted_line_amount <> round(expected_amount, expected_scale) THEN
                RAISE EXCEPTION 'posted inventory amount mismatch';
              END IF;
            ELSIF EXISTS (
              SELECT 1 FROM product_price_history effective_price
               WHERE effective_price.project_product_id = product.id
                 AND effective_price.effective_from <= parent.posting_date
                 AND (effective_price.effective_to IS NULL
                   OR effective_price.effective_to > parent.posting_date)) THEN
              RAISE EXCEPTION 'effective price cannot be recorded as unavailable';
            END IF;
          ELSE
            SELECT * INTO original_line FROM inventory_ledger_lines
             WHERE posting_id = parent.reversal_of_posting_id
               AND product_definition_id = NEW.product_definition_id;
            IF NOT FOUND OR NEW.configuration_product_version_id <> original_line.configuration_product_version_id
               OR NEW.product_price_version_id IS DISTINCT FROM original_line.product_price_version_id
               OR NEW.entered_quantity <> -original_line.entered_quantity
               OR NEW.entered_unit_code <> original_line.entered_unit_code
               OR NEW.canonical_signed_quantity <> -original_line.canonical_signed_quantity
               OR NEW.canonical_unit_code <> original_line.canonical_unit_code
               OR NEW.price_status <> original_line.price_status
               OR NEW.applied_unit_price IS DISTINCT FROM original_line.applied_unit_price
               OR NEW.price_basis_unit_code IS DISTINCT FROM original_line.price_basis_unit_code
               OR NEW.price_effective_from IS DISTINCT FROM original_line.price_effective_from
               OR NEW.price_effective_to IS DISTINCT FROM original_line.price_effective_to
               OR NEW.currency IS DISTINCT FROM original_line.currency
               OR NEW.currency_minor_unit_scale IS DISTINCT FROM original_line.currency_minor_unit_scale
               OR NEW.posted_line_amount IS DISTINCT FROM -original_line.posted_line_amount
               OR NEW.frozen_product_json <> original_line.frozen_product_json THEN
              RAISE EXCEPTION 'reversal line must exactly negate frozen original';
            END IF;
          END IF;
          RETURN NEW;
        END; $$;

        CREATE TRIGGER inventory_ledger_lines_guard BEFORE INSERT OR UPDATE OR DELETE ON inventory_ledger_lines
          FOR EACH ROW EXECUTE FUNCTION vantix_guard_inventory_line();

        CREATE FUNCTION vantix_check_inventory_posting_complete() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE current_posting inventory_postings%ROWTYPE;
        BEGIN
          SELECT * INTO current_posting FROM inventory_postings WHERE id = NEW.id;
          IF NOT FOUND OR current_posting.status <> 'posted' OR NOT EXISTS (
            SELECT 1 FROM inventory_ledger_lines WHERE posting_id = NEW.id) THEN
            RAISE EXCEPTION 'inventory posting must commit posted with at least one line';
          END IF;
          IF current_posting.posting_type = 'reversal' AND (
            SELECT count(*) FROM inventory_ledger_lines WHERE posting_id = NEW.id) <> (
            SELECT count(*) FROM inventory_ledger_lines
              WHERE posting_id = current_posting.reversal_of_posting_id) THEN
            RAISE EXCEPTION 'reversal must contain every original line';
          END IF;
          RETURN NULL;
        END; $$;

        CREATE CONSTRAINT TRIGGER inventory_postings_complete
          AFTER INSERT OR UPDATE ON inventory_postings DEFERRABLE INITIALLY DEFERRED
          FOR EACH ROW EXECUTE FUNCTION vantix_check_inventory_posting_complete();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS inventory_postings_complete ON inventory_postings")
    op.execute("DROP TRIGGER IF EXISTS inventory_ledger_lines_guard ON inventory_ledger_lines")
    op.execute("DROP TRIGGER IF EXISTS inventory_postings_guard ON inventory_postings")
    op.execute("DROP FUNCTION IF EXISTS vantix_check_inventory_posting_complete()")
    op.execute("DROP FUNCTION IF EXISTS vantix_guard_inventory_line()")
    op.execute("DROP FUNCTION IF EXISTS vantix_guard_inventory_posting()")
    for table in ("inventory_ledger_lines", "inventory_postings"):
        for command in ("select", "insert", "update", "delete"):
            op.execute(f"DROP POLICY IF EXISTS {table}_{command}_scope ON {table}")
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant_policy ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.drop_table("inventory_ledger_lines")
    op.drop_table("inventory_postings")
