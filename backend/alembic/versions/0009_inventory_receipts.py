"""Add immutable supplier receipts to the inventory ledger.

Revision ID: 0009_inventory_receipts
Revises: 0008_inventory_authority_precision
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009_inventory_receipts"
down_revision: str | None = "0008_inventory_authority_precision"
branch_labels: str | None = None
depends_on: str | None = None


POSTING_GUARD = """
CREATE FUNCTION vantix_guard_inventory_posting() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE source_project uuid; source_org uuid; current_snapshot uuid;
  original inventory_postings%ROWTYPE;
  expected_supplier text; expected_delivery text;
BEGIN
  IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'posted inventory is append-only'; END IF;
  IF TG_OP = 'INSERT' AND NEW.status <> 'building' THEN
    RAISE EXCEPTION 'inventory posting must begin in building state';
  END IF;
  IF TG_OP = 'UPDATE' THEN
    IF OLD.status = 'building' AND NEW.status = 'posted'
       AND OLD.id = NEW.id AND OLD.organisation_id = NEW.organisation_id
       AND OLD.project_id = NEW.project_id
       AND OLD.source_configuration_snapshot_id = NEW.source_configuration_snapshot_id
       AND OLD.posting_type = NEW.posting_type AND OLD.posting_date = NEW.posting_date
       AND OLD.reversal_of_posting_id IS NOT DISTINCT FROM NEW.reversal_of_posting_id
       AND OLD.reason IS NOT DISTINCT FROM NEW.reason
       AND OLD.supplier_name IS NOT DISTINCT FROM NEW.supplier_name
       AND OLD.supplier_name_normalized IS NOT DISTINCT FROM NEW.supplier_name_normalized
       AND OLD.delivery_note_number IS NOT DISTINCT FROM NEW.delivery_note_number
       AND OLD.delivery_note_normalized IS NOT DISTINCT FROM NEW.delivery_note_normalized
       AND OLD.purchase_order_reference IS NOT DISTINCT FROM NEW.purchase_order_reference
       AND OLD.invoice_reference IS NOT DISTINCT FROM NEW.invoice_reference
       AND OLD.received_by_user_id IS NOT DISTINCT FROM NEW.received_by_user_id
       AND OLD.posted_by = NEW.posted_by THEN
      NULL;
    ELSE
      RAISE EXCEPTION 'posted inventory is append-only';
    END IF;
    IF NOT EXISTS (
      SELECT 1 FROM inventory_ledger_lines WHERE posting_id = NEW.id
    ) THEN
      RAISE EXCEPTION 'inventory posting requires at least one ledger line';
    END IF;
  END IF;
  SELECT project_id, organisation_id INTO source_project, source_org
    FROM project_configuration_snapshots WHERE id = NEW.source_configuration_snapshot_id;
  IF source_project IS DISTINCT FROM NEW.project_id
     OR source_org IS DISTINCT FROM NEW.organisation_id THEN
    RAISE EXCEPTION 'inventory snapshot ownership mismatch';
  END IF;
  SELECT current_configuration_snapshot_id INTO current_snapshot
    FROM projects WHERE id = NEW.project_id AND organisation_id = NEW.organisation_id
    FOR UPDATE;
  PERFORM pg_advisory_xact_lock(hashtextextended(NEW.project_id::text, 0));
  IF NEW.posting_type IN ('opening_stock', 'receipt') THEN
    IF NEW.source_configuration_snapshot_id IS DISTINCT FROM current_snapshot THEN
      RAISE EXCEPTION 'inventory posting requires the current configuration snapshot';
    END IF;
    IF NEW.posting_type = 'receipt' THEN
      expected_supplier := lower(regexp_replace(btrim(NEW.supplier_name), '\\s+', ' ', 'g'));
      expected_delivery := lower(regexp_replace(btrim(NEW.delivery_note_number), '\\s+', ' ', 'g'));
      IF expected_supplier = '' OR expected_delivery = ''
         OR NEW.supplier_name_normalized <> expected_supplier
         OR NEW.delivery_note_normalized <> expected_delivery
         OR NEW.received_by_user_id <> NEW.posted_by THEN
        RAISE EXCEPTION 'receipt documentary authority mismatch';
      END IF;
    END IF;
  ELSE
    SELECT * INTO original FROM inventory_postings WHERE id = NEW.reversal_of_posting_id;
    IF NOT FOUND OR original.project_id <> NEW.project_id
       OR original.organisation_id <> NEW.organisation_id
       OR original.posting_type NOT IN ('opening_stock', 'receipt')
       OR original.status <> 'posted' OR NEW.posting_date < original.posting_date
       OR NEW.source_configuration_snapshot_id <>
          original.source_configuration_snapshot_id THEN
      RAISE EXCEPTION 'invalid inventory reversal target';
    END IF;
  END IF;
  RETURN NEW;
END; $$;
"""


LINE_GUARD = """
CREATE FUNCTION vantix_guard_inventory_line() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  parent inventory_postings%ROWTYPE;
  product project_products%ROWTYPE;
  definition project_product_definitions%ROWTYPE;
  price product_price_history%ROWTYPE;
  original_line inventory_ledger_lines%ROWTYPE;
  snapshot_configuration_id uuid;
  entered_factor numeric; package_factor numeric; basis_factor numeric;
  expected_canonical numeric; expected_amount numeric; expected_scale integer;
  package_dimension text; entered_dimension text; project_currency text;
BEGIN
  IF TG_OP <> 'INSERT' THEN RAISE EXCEPTION 'inventory ledger lines are immutable'; END IF;
  SELECT * INTO parent FROM inventory_postings WHERE id = NEW.posting_id;
  IF NOT FOUND OR parent.status <> 'building' OR parent.project_id <> NEW.project_id
     OR parent.organisation_id <> NEW.organisation_id THEN
    RAISE EXCEPTION 'ledger lines require a matching building posting';
  END IF;
  SELECT configuration_version_id INTO snapshot_configuration_id
    FROM project_configuration_snapshots WHERE id = parent.source_configuration_snapshot_id;
  SELECT currency INTO project_currency FROM projects WHERE id = NEW.project_id;
  SELECT * INTO product FROM project_products WHERE id = NEW.configuration_product_version_id;
  SELECT * INTO definition FROM project_product_definitions
   WHERE id = NEW.product_definition_id;
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
     OR NEW.frozen_product_json ->> 'inventory_unit_code'
        IS DISTINCT FROM product.inventory_unit_code
     OR NULLIF(NEW.frozen_product_json ->> 'specific_gravity', '')::numeric
        IS DISTINCT FROM product.specific_gravity THEN
    RAISE EXCEPTION 'frozen product authority mismatch';
  END IF;
  IF NEW.expiry_date IS NOT NULL AND NEW.manufacture_date IS NOT NULL
     AND NEW.expiry_date <= NEW.manufacture_date THEN
    RAISE EXCEPTION 'inventory line expiry must follow manufacture date';
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

  IF parent.posting_type IN ('opening_stock', 'receipt') THEN
    IF NEW.reversal_of_line_id IS NOT NULL OR NEW.entered_quantity <= 0
       OR NEW.canonical_signed_quantity <= 0 THEN
      RAISE EXCEPTION 'positive inventory posting line authority mismatch';
    END IF;
    IF parent.posting_type = 'opening_stock' THEN
      IF NEW.cost_source = 'supplier_document' OR NEW.batch_number IS NOT NULL
         OR NEW.manufacture_date IS NOT NULL OR NEW.expiry_date IS NOT NULL THEN
        RAISE EXCEPTION 'opening stock line context mismatch';
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
    END IF;

    IF NEW.cost_source = 'configured_effective_price' THEN
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
    ELSIF NEW.cost_source = 'supplier_document' THEN
      IF parent.posting_type <> 'receipt' OR NEW.product_price_version_id IS NOT NULL
         OR NEW.currency <> project_currency OR NEW.applied_unit_price < 0
         OR NEW.price_effective_from IS NOT NULL OR NEW.price_effective_to IS NOT NULL THEN
        RAISE EXCEPTION 'supplier receipt price authority mismatch';
      END IF;
    ELSIF EXISTS (
      SELECT 1 FROM product_price_history effective_price
       WHERE effective_price.project_product_id = product.id
         AND effective_price.effective_from <= parent.posting_date
         AND (effective_price.effective_to IS NULL
           OR effective_price.effective_to > parent.posting_date)) THEN
      RAISE EXCEPTION 'effective price cannot be recorded as unavailable';
    END IF;

    IF NEW.price_status = 'ready' THEN
      expected_scale := CASE NEW.currency
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
      basis_factor := CASE NEW.price_basis_unit_code
        WHEN 'kg' THEN 1 WHEN 't' THEN 1000 WHEN 'lb' THEN 0.45359237
        WHEN 'L' THEN 1 WHEN 'm3' THEN 1000 WHEN 'gal_us' THEN 3.785411784
        WHEN 'bbl' THEN 158.987294928 WHEN 'each' THEN 1 END;
      IF NEW.price_basis_unit_code <> 'package'
         AND (basis_factor IS NULL OR (CASE
           WHEN NEW.price_basis_unit_code IN ('kg','t','lb') THEN 'mass'
           WHEN NEW.price_basis_unit_code IN ('L','m3','gal_us','bbl') THEN 'volume'
           ELSE 'count' END) <> package_dimension) THEN
        RAISE EXCEPTION 'inventory price basis dimension mismatch';
      END IF;
      expected_amount := CASE WHEN NEW.price_basis_unit_code = 'package'
        THEN expected_canonical / (product.package_size * package_factor) * NEW.applied_unit_price
        ELSE expected_canonical / basis_factor * NEW.applied_unit_price END;
      IF NEW.posted_line_amount <> round(expected_amount, expected_scale) THEN
        RAISE EXCEPTION 'posted inventory amount mismatch';
      END IF;
    END IF;
  ELSE
    SELECT * INTO original_line FROM inventory_ledger_lines
     WHERE id = NEW.reversal_of_line_id AND posting_id = parent.reversal_of_posting_id;
    IF NOT FOUND OR NEW.product_definition_id <> original_line.product_definition_id
       OR NEW.configuration_product_version_id <> original_line.configuration_product_version_id
       OR NEW.product_price_version_id IS DISTINCT FROM original_line.product_price_version_id
       OR NEW.batch_number IS DISTINCT FROM original_line.batch_number
       OR NEW.manufacture_date IS DISTINCT FROM original_line.manufacture_date
       OR NEW.expiry_date IS DISTINCT FROM original_line.expiry_date
       OR NEW.entered_quantity <> -original_line.entered_quantity
       OR NEW.entered_unit_code <> original_line.entered_unit_code
       OR NEW.canonical_signed_quantity <> -original_line.canonical_signed_quantity
       OR NEW.canonical_unit_code <> original_line.canonical_unit_code
       OR NEW.price_status <> original_line.price_status
       OR NEW.cost_source <> original_line.cost_source
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
"""


def upgrade() -> None:
    op.alter_column(
        "inventory_postings",
        "posting_type",
        existing_type=sa.String(length=30),
        existing_nullable=False,
    )
    for column in (
        sa.Column("supplier_name", sa.String(200)),
        sa.Column("supplier_name_normalized", sa.String(200)),
        sa.Column("delivery_note_number", sa.String(100)),
        sa.Column("delivery_note_normalized", sa.String(100)),
        sa.Column("purchase_order_reference", sa.String(100)),
        sa.Column("invoice_reference", sa.String(100)),
        sa.Column("received_by_user_id", postgresql.UUID(as_uuid=True)),
    ):
        op.add_column("inventory_postings", column)
    op.create_foreign_key(
        "fk_inventory_postings_received_by_user",
        "inventory_postings",
        "users",
        ["received_by_user_id"],
        ["id"],
    )
    op.drop_constraint("ck_inventory_postings_type", "inventory_postings", type_="check")
    op.drop_constraint(
        "ck_inventory_postings_reversal_context", "inventory_postings", type_="check"
    )
    op.create_check_constraint(
        "ck_inventory_postings_type",
        "inventory_postings",
        "posting_type IN ('opening_stock','receipt','reversal')",
    )
    op.create_check_constraint(
        "ck_inventory_postings_reversal_context",
        "inventory_postings",
        "(posting_type IN ('opening_stock','receipt') AND reversal_of_posting_id IS NULL) OR "
        "(posting_type = 'reversal' AND reversal_of_posting_id IS NOT NULL AND reason IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_inventory_postings_receipt_context",
        "inventory_postings",
        "(posting_type = 'receipt' AND supplier_name IS NOT NULL "
        "AND supplier_name_normalized IS NOT NULL AND delivery_note_number IS NOT NULL "
        "AND delivery_note_normalized IS NOT NULL AND received_by_user_id IS NOT NULL) OR "
        "(posting_type <> 'receipt' AND supplier_name IS NULL "
        "AND supplier_name_normalized IS NULL AND delivery_note_number IS NULL "
        "AND delivery_note_normalized IS NULL AND purchase_order_reference IS NULL "
        "AND invoice_reference IS NULL AND received_by_user_id IS NULL)",
    )
    op.create_index(
        "uq_inventory_receipt_delivery_note",
        "inventory_postings",
        ["project_id", "supplier_name_normalized", "delivery_note_normalized"],
        unique=True,
        postgresql_where=sa.text("posting_type = 'receipt'"),
    )

    op.add_column(
        "inventory_ledger_lines",
        sa.Column("reversal_of_line_id", postgresql.UUID(as_uuid=True)),
    )
    op.add_column("inventory_ledger_lines", sa.Column("batch_number", sa.String(100)))
    op.add_column("inventory_ledger_lines", sa.Column("manufacture_date", sa.Date()))
    op.add_column("inventory_ledger_lines", sa.Column("expiry_date", sa.Date()))
    op.add_column("inventory_ledger_lines", sa.Column("cost_source", sa.String(40)))
    op.execute(
        "UPDATE inventory_ledger_lines SET cost_source = CASE "
        "WHEN price_status = 'ready' THEN 'configured_effective_price' ELSE 'unavailable' END"
    )
    op.alter_column(
        "inventory_ledger_lines",
        "cost_source",
        existing_type=sa.String(40),
        nullable=False,
    )
    op.execute(
        "UPDATE inventory_ledger_lines reversal_line SET reversal_of_line_id = original_line.id "
        "FROM inventory_postings reversal, inventory_ledger_lines original_line "
        "WHERE reversal.id = reversal_line.posting_id "
        "AND original_line.posting_id = reversal.reversal_of_posting_id "
        "AND original_line.product_definition_id = reversal_line.product_definition_id"
    )
    op.create_foreign_key(
        "fk_inventory_lines_reversal_line",
        "inventory_ledger_lines",
        "inventory_ledger_lines",
        ["reversal_of_line_id"],
        ["id"],
    )
    op.create_unique_constraint(
        "uq_inventory_lines_reversal_line",
        "inventory_ledger_lines",
        ["reversal_of_line_id"],
    )
    op.drop_constraint("uq_inventory_line_product", "inventory_ledger_lines", type_="unique")
    op.execute(
        "CREATE UNIQUE INDEX uq_inventory_line_product_batch ON inventory_ledger_lines "
        "(posting_id, product_definition_id, COALESCE(batch_number, ''))"
    )
    op.drop_constraint(
        "ck_inventory_lines_price_completeness", "inventory_ledger_lines", type_="check"
    )
    op.create_check_constraint(
        "ck_inventory_lines_cost_source",
        "inventory_ledger_lines",
        "cost_source IN ('supplier_document','configured_effective_price','unavailable')",
    )
    op.create_check_constraint(
        "ck_inventory_lines_dates",
        "inventory_ledger_lines",
        "expiry_date IS NULL OR manufacture_date IS NULL OR expiry_date > manufacture_date",
    )
    op.create_check_constraint(
        "ck_inventory_lines_price_completeness",
        "inventory_ledger_lines",
        "(cost_source = 'configured_effective_price' AND price_status = 'ready' "
        "AND product_price_version_id IS NOT NULL AND applied_unit_price IS NOT NULL "
        "AND price_basis_unit_code IS NOT NULL AND price_effective_from IS NOT NULL "
        "AND currency IS NOT NULL AND currency_minor_unit_scale IS NOT NULL "
        "AND posted_line_amount IS NOT NULL) OR "
        "(cost_source = 'supplier_document' AND price_status = 'ready' "
        "AND product_price_version_id IS NULL AND applied_unit_price IS NOT NULL "
        "AND price_basis_unit_code IS NOT NULL AND price_effective_from IS NULL "
        "AND price_effective_to IS NULL AND currency IS NOT NULL "
        "AND currency_minor_unit_scale IS NOT NULL AND posted_line_amount IS NOT NULL) OR "
        "(cost_source = 'unavailable' AND price_status = 'unavailable' "
        "AND product_price_version_id IS NULL AND applied_unit_price IS NULL "
        "AND price_basis_unit_code IS NULL AND price_effective_from IS NULL "
        "AND price_effective_to IS NULL AND currency IS NULL "
        "AND currency_minor_unit_scale IS NULL AND posted_line_amount IS NULL)",
    )

    op.execute(
        "ALTER FUNCTION vantix_guard_inventory_posting() "
        "RENAME TO vantix_guard_inventory_posting_v8"
    )
    op.execute(
        "ALTER FUNCTION vantix_guard_inventory_line() RENAME TO vantix_guard_inventory_line_v8"
    )
    op.execute(POSTING_GUARD)
    op.execute(LINE_GUARD)
    op.execute("DROP TRIGGER inventory_postings_guard ON inventory_postings")
    op.execute("DROP TRIGGER inventory_ledger_lines_guard ON inventory_ledger_lines")
    op.execute(
        "CREATE TRIGGER inventory_postings_guard BEFORE INSERT OR UPDATE OR DELETE "
        "ON inventory_postings FOR EACH ROW EXECUTE FUNCTION vantix_guard_inventory_posting()"
    )
    op.execute(
        "CREATE TRIGGER inventory_ledger_lines_guard BEFORE INSERT OR UPDATE OR DELETE "
        "ON inventory_ledger_lines FOR EACH ROW EXECUTE FUNCTION vantix_guard_inventory_line()"
    )


def downgrade() -> None:
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM inventory_postings WHERE posting_type = 'receipt') "
        "THEN RAISE EXCEPTION 'cannot downgrade inventory receipts while receipt history exists'; "
        "END IF; END $$"
    )
    op.execute("DROP TRIGGER inventory_postings_guard ON inventory_postings")
    op.execute("DROP TRIGGER inventory_ledger_lines_guard ON inventory_ledger_lines")
    op.execute("DROP FUNCTION vantix_guard_inventory_posting()")
    op.execute("DROP FUNCTION vantix_guard_inventory_line()")
    op.execute(
        "ALTER FUNCTION vantix_guard_inventory_posting_v8() "
        "RENAME TO vantix_guard_inventory_posting"
    )
    op.execute(
        "ALTER FUNCTION vantix_guard_inventory_line_v8() RENAME TO vantix_guard_inventory_line"
    )
    op.execute(
        "CREATE TRIGGER inventory_postings_guard BEFORE INSERT OR UPDATE OR DELETE "
        "ON inventory_postings FOR EACH ROW EXECUTE FUNCTION vantix_guard_inventory_posting()"
    )
    op.execute(
        "CREATE TRIGGER inventory_ledger_lines_guard BEFORE INSERT OR UPDATE OR DELETE "
        "ON inventory_ledger_lines FOR EACH ROW EXECUTE FUNCTION vantix_guard_inventory_line()"
    )

    op.drop_constraint(
        "ck_inventory_lines_price_completeness", "inventory_ledger_lines", type_="check"
    )
    op.drop_constraint("ck_inventory_lines_dates", "inventory_ledger_lines", type_="check")
    op.drop_constraint("ck_inventory_lines_cost_source", "inventory_ledger_lines", type_="check")
    op.drop_index("uq_inventory_line_product_batch", table_name="inventory_ledger_lines")
    op.create_unique_constraint(
        "uq_inventory_line_product",
        "inventory_ledger_lines",
        ["posting_id", "product_definition_id"],
    )
    op.drop_constraint("uq_inventory_lines_reversal_line", "inventory_ledger_lines", type_="unique")
    op.drop_constraint(
        "fk_inventory_lines_reversal_line", "inventory_ledger_lines", type_="foreignkey"
    )
    op.create_check_constraint(
        "ck_inventory_lines_price_completeness",
        "inventory_ledger_lines",
        "(price_status = 'ready' AND product_price_version_id IS NOT NULL "
        "AND applied_unit_price IS NOT NULL AND price_basis_unit_code IS NOT NULL "
        "AND price_effective_from IS NOT NULL AND currency IS NOT NULL "
        "AND currency_minor_unit_scale IS NOT NULL AND posted_line_amount IS NOT NULL) OR "
        "(price_status = 'unavailable' AND product_price_version_id IS NULL "
        "AND applied_unit_price IS NULL AND price_basis_unit_code IS NULL "
        "AND price_effective_from IS NULL AND price_effective_to IS NULL AND currency IS NULL "
        "AND currency_minor_unit_scale IS NULL AND posted_line_amount IS NULL)",
    )
    for column in (
        "cost_source",
        "expiry_date",
        "manufacture_date",
        "batch_number",
        "reversal_of_line_id",
    ):
        op.drop_column("inventory_ledger_lines", column)

    op.drop_index("uq_inventory_receipt_delivery_note", table_name="inventory_postings")
    op.drop_constraint(
        "fk_inventory_postings_received_by_user",
        "inventory_postings",
        type_="foreignkey",
    )
    op.drop_constraint("ck_inventory_postings_receipt_context", "inventory_postings", type_="check")
    op.drop_constraint(
        "ck_inventory_postings_reversal_context", "inventory_postings", type_="check"
    )
    op.drop_constraint("ck_inventory_postings_type", "inventory_postings", type_="check")
    op.create_check_constraint(
        "ck_inventory_postings_type",
        "inventory_postings",
        "posting_type IN ('opening_stock','reversal')",
    )
    op.create_check_constraint(
        "ck_inventory_postings_reversal_context",
        "inventory_postings",
        "(posting_type = 'opening_stock' AND reversal_of_posting_id IS NULL) OR "
        "(posting_type = 'reversal' AND reversal_of_posting_id IS NOT NULL AND reason IS NOT NULL)",
    )
    for column in (
        "received_by_user_id",
        "invoice_reference",
        "purchase_order_reference",
        "delivery_note_normalized",
        "delivery_note_number",
        "supplier_name_normalized",
        "supplier_name",
    ):
        op.drop_column("inventory_postings", column)
