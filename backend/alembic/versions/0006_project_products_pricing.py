"""Add configuration-owned project products and effective prices.

Revision ID: 0006_project_products_pricing
Revises: 0005_project_config_lifecycle
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006_project_products_pricing"
down_revision = "0005_project_config_lifecycle"
branch_labels = None
depends_on = None


def _elevated(table: str) -> str:
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


def _project_member(table: str, configure: bool) -> str:
    capability = "AND project_access.capabilities ? 'configure_project'" if configure else ""
    return f"""
      EXISTS (
        SELECT 1 FROM project_memberships project_access
        WHERE project_access.project_id = {table}.project_id
          AND project_access.user_id = NULLIF(
            current_setting('app.current_user_id', true), ''
          )::uuid
          {capability}
      )
    """


def upgrade() -> None:
    op.create_table(
        "project_products",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organisation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("configuration_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("item_code", sa.String(100), nullable=False),
        sa.Column("item_name", sa.String(200), nullable=False),
        sa.Column("alternate_name", sa.String(200)),
        sa.Column("packaging", sa.String(30), nullable=False),
        sa.Column("package_size", sa.Numeric(24, 12), nullable=False),
        sa.Column("package_unit_code", sa.String(20), nullable=False),
        sa.Column("inventory_applicable", sa.Boolean(), nullable=False),
        sa.Column("inventory_unit_code", sa.String(20)),
        sa.Column("specific_gravity", sa.Numeric(18, 12)),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(
            ["configuration_version_id"], ["project_configuration_versions.id"]
        ),
        sa.CheckConstraint("package_size > 0", name="ck_project_products_package_size"),
        sa.CheckConstraint(
            "specific_gravity IS NULL OR specific_gravity > 0",
            name="ck_project_products_specific_gravity",
        ),
        sa.CheckConstraint(
            "(inventory_applicable AND inventory_unit_code IS NOT NULL) OR "
            "(NOT inventory_applicable AND inventory_unit_code IS NULL)",
            name="ck_project_products_inventory_applicability",
        ),
        sa.CheckConstraint(
            "packaging IN ('sack','pail','drum','tote','bulk','case','each','other')",
            name="ck_project_products_packaging",
        ),
        sa.CheckConstraint(
            "package_unit_code IN ('kg','t','lb','L','m3','gal_us','bbl','each')",
            name="ck_project_products_package_unit",
        ),
        sa.CheckConstraint(
            "inventory_unit_code IS NULL OR inventory_unit_code IN "
            "('kg','t','lb','L','m3','gal_us','bbl','each','package')",
            name="ck_project_products_inventory_unit",
        ),
        sa.CheckConstraint(
            "inventory_unit_code IS NULL OR inventory_unit_code = 'package' OR "
            "(inventory_unit_code IN ('kg','t','lb') AND package_unit_code IN ('kg','t','lb')) OR "
            "(inventory_unit_code IN ('L','m3','gal_us','bbl') AND "
            " package_unit_code IN ('L','m3','gal_us','bbl')) OR "
            "(inventory_unit_code = 'each' AND package_unit_code = 'each')",
            name="ck_project_products_unit_dimension",
        ),
    )
    op.create_index(
        "uq_project_products_configuration_code",
        "project_products",
        ["configuration_version_id", sa.text("lower(item_code)")],
        unique=True,
    )
    op.create_index("ix_project_products_organisation_id", "project_products", ["organisation_id"])

    op.create_table(
        "product_price_history",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organisation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date()),
        sa.Column("unit_price", sa.Numeric(24, 12), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("price_basis_unit_code", sa.String(20), nullable=False),
        sa.Column("source", sa.String(200)),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(
            ["project_product_id"], ["project_products.id"], ondelete="CASCADE"
        ),
        sa.CheckConstraint("unit_price >= 0", name="ck_product_prices_amount"),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from",
            name="ck_product_prices_range",
        ),
        sa.CheckConstraint(
            "price_basis_unit_code IN ('kg','t','lb','L','m3','gal_us','bbl','each','package')",
            name="ck_product_prices_basis_unit",
        ),
    )
    op.create_index(
        "ix_product_prices_product_start",
        "product_price_history",
        ["project_product_id", "effective_from"],
    )
    op.create_index(
        "ix_product_price_history_organisation_id",
        "product_price_history",
        ["organisation_id"],
    )

    for table in ("project_products", "product_price_history"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY {table}_tenant_policy ON {table}
            USING (
              organisation_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid
              OR current_setting('app.is_system_service', true) = 'true'
            )
            WITH CHECK (
              organisation_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid
              OR current_setting('app.is_system_service', true) = 'true'
            );

            CREATE POLICY {table}_select_scope ON {table} AS RESTRICTIVE FOR SELECT
            USING (
              {_elevated(table)} OR {_project_member(table, False)}
              OR current_setting('app.is_system_service', true) = 'true'
            );

            CREATE POLICY {table}_insert_scope ON {table} AS RESTRICTIVE FOR INSERT
            WITH CHECK (
              {_elevated(table)} OR {_project_member(table, True)}
              OR current_setting('app.is_system_service', true) = 'true'
            );

            CREATE POLICY {table}_update_scope ON {table} AS RESTRICTIVE FOR UPDATE
            USING (
              {_elevated(table)} OR {_project_member(table, True)}
              OR current_setting('app.is_system_service', true) = 'true'
            )
            WITH CHECK (
              {_elevated(table)} OR {_project_member(table, True)}
              OR current_setting('app.is_system_service', true) = 'true'
            );

            CREATE POLICY {table}_delete_scope ON {table} AS RESTRICTIVE FOR DELETE
            USING (
              {_elevated(table)} OR {_project_member(table, True)}
              OR current_setting('app.is_system_service', true) = 'true'
            );
            """
        )

    op.execute(
        """
        CREATE FUNCTION vantix_guard_product_configuration()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
          row_record record;
          parent_product project_products%ROWTYPE;
          configuration_state text;
        BEGIN
          IF TG_OP = 'DELETE' THEN row_record := OLD; ELSE row_record := NEW; END IF;

          IF TG_TABLE_NAME = 'project_products' THEN
            SELECT state INTO configuration_state
              FROM project_configuration_versions
             WHERE id = row_record.configuration_version_id
               AND organisation_id = row_record.organisation_id
               AND project_id = row_record.project_id;
          ELSE
            SELECT * INTO parent_product FROM project_products
             WHERE id = row_record.project_product_id;
            IF NOT FOUND
               OR parent_product.organisation_id <> row_record.organisation_id
               OR parent_product.project_id <> row_record.project_id THEN
              RAISE EXCEPTION 'product price ownership mismatch';
            END IF;
            SELECT state INTO configuration_state
              FROM project_configuration_versions
             WHERE id = parent_product.configuration_version_id;
          END IF;

          IF configuration_state IS DISTINCT FROM 'draft' THEN
            RAISE EXCEPTION 'product configuration is immutable';
          END IF;
          IF TG_OP = 'UPDATE' THEN
            IF OLD.id IS DISTINCT FROM NEW.id
               OR OLD.organisation_id IS DISTINCT FROM NEW.organisation_id
               OR OLD.project_id IS DISTINCT FROM NEW.project_id THEN
              RAISE EXCEPTION 'product configuration identity is immutable';
            END IF;
            IF TG_TABLE_NAME = 'project_products' THEN
              IF OLD.configuration_version_id IS DISTINCT FROM NEW.configuration_version_id THEN
                RAISE EXCEPTION 'product configuration identity is immutable';
              END IF;
            ELSE
              IF OLD.project_product_id IS DISTINCT FROM NEW.project_product_id THEN
                RAISE EXCEPTION 'product configuration identity is immutable';
              END IF;
            END IF;
          END IF;
          RETURN row_record;
        END;
        $$;

        CREATE TRIGGER project_products_configuration_guard
        BEFORE INSERT OR UPDATE OR DELETE ON project_products
        FOR EACH ROW EXECUTE FUNCTION vantix_guard_product_configuration();

        CREATE TRIGGER product_prices_configuration_guard
        BEFORE INSERT OR UPDATE OR DELETE ON product_price_history
        FOR EACH ROW EXECUTE FUNCTION vantix_guard_product_configuration();

        CREATE FUNCTION vantix_guard_product_price()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
          product project_products%ROWTYPE;
          project_currency text;
          package_dimension text;
          inventory_dimension text;
          basis_dimension text;
          target_dimension text;
        BEGIN
          PERFORM pg_advisory_xact_lock(hashtextextended(NEW.project_product_id::text, 0));
          SELECT * INTO product FROM project_products WHERE id = NEW.project_product_id;
          SELECT currency INTO project_currency FROM projects WHERE id = product.project_id;
          IF NEW.currency <> project_currency THEN
            RAISE EXCEPTION 'price currency must match project currency';
          END IF;

          package_dimension := CASE
            WHEN product.package_unit_code IN ('kg','t','lb') THEN 'mass'
            WHEN product.package_unit_code IN ('L','m3','gal_us','bbl') THEN 'volume'
            ELSE 'count' END;
          inventory_dimension := CASE
            WHEN product.inventory_unit_code IN ('kg','t','lb') THEN 'mass'
            WHEN product.inventory_unit_code IN ('L','m3','gal_us','bbl') THEN 'volume'
            WHEN product.inventory_unit_code = 'each' THEN 'count'
            ELSE 'package' END;
          basis_dimension := CASE
            WHEN NEW.price_basis_unit_code IN ('kg','t','lb') THEN 'mass'
            WHEN NEW.price_basis_unit_code IN ('L','m3','gal_us','bbl') THEN 'volume'
            WHEN NEW.price_basis_unit_code = 'each' THEN 'count'
            ELSE 'package' END;
          target_dimension := package_dimension;
          IF product.inventory_applicable THEN
            target_dimension := inventory_dimension;
          END IF;
          IF basis_dimension <> 'package' AND basis_dimension <> target_dimension THEN
            RAISE EXCEPTION 'price basis is dimensionally incompatible';
          END IF;

          IF EXISTS (
            SELECT 1 FROM product_price_history existing
             WHERE existing.project_product_id = NEW.project_product_id
               AND existing.id <> NEW.id
               AND daterange(existing.effective_from, existing.effective_to, '[)') &&
                   daterange(NEW.effective_from, NEW.effective_to, '[)')
          ) THEN
            RAISE EXCEPTION 'effective product price periods cannot overlap';
          END IF;
          RETURN NEW;
        END;
        $$;

        CREATE TRIGGER product_prices_range_guard
        BEFORE INSERT OR UPDATE ON product_price_history
        FOR EACH ROW EXECUTE FUNCTION vantix_guard_product_price();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS product_prices_range_guard ON product_price_history")
    op.execute("DROP TRIGGER IF EXISTS product_prices_configuration_guard ON product_price_history")
    op.execute("DROP TRIGGER IF EXISTS project_products_configuration_guard ON project_products")
    op.execute("DROP FUNCTION IF EXISTS vantix_guard_product_price()")
    op.execute("DROP FUNCTION IF EXISTS vantix_guard_product_configuration()")
    for table in ("product_price_history", "project_products"):
        for command in ("select", "insert", "update", "delete"):
            op.execute(f"DROP POLICY IF EXISTS {table}_{command}_scope ON {table}")
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant_policy ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.drop_table("product_price_history")
    op.drop_table("project_products")
