"""Deliver inventory snapshot authority and canonical precision guards.

Revision ID: 0008_inventory_authority_precision
Revises: 0007_inventory_opening_stock
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0008_inventory_authority_precision"
down_revision: str | None = "0007_inventory_opening_stock"
branch_labels: str | None = None
depends_on: str | None = None


def _posting_guard(*, hardened: bool) -> str:
    if hardened:
        return """
        CREATE OR REPLACE FUNCTION vantix_guard_inventory_posting() RETURNS trigger
        LANGUAGE plpgsql AS $$
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
          IF source_project IS DISTINCT FROM NEW.project_id
             OR source_org IS DISTINCT FROM NEW.organisation_id THEN
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
            IF NOT FOUND OR original.project_id <> NEW.project_id
               OR original.organisation_id <> NEW.organisation_id
               OR original.posting_type <> 'opening_stock' OR original.status <> 'posted'
               OR NEW.posting_date < original.posting_date
               OR NEW.source_configuration_snapshot_id <>
                  original.source_configuration_snapshot_id THEN
              RAISE EXCEPTION 'invalid inventory reversal target';
            END IF;
          END IF;
          RETURN NEW;
        END; $$;
        """
    return """
    CREATE OR REPLACE FUNCTION vantix_guard_inventory_posting() RETURNS trigger
    LANGUAGE plpgsql AS $$
    DECLARE source_project uuid; source_org uuid; original inventory_postings%ROWTYPE;
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
          RETURN NEW;
        END IF;
        RAISE EXCEPTION 'posted inventory is append-only';
      END IF;
      SELECT project_id, organisation_id INTO source_project, source_org
        FROM project_configuration_snapshots WHERE id = NEW.source_configuration_snapshot_id;
      IF source_project IS DISTINCT FROM NEW.project_id
         OR source_org IS DISTINCT FROM NEW.organisation_id THEN
        RAISE EXCEPTION 'inventory snapshot ownership mismatch';
      END IF;
      PERFORM pg_advisory_xact_lock(hashtextextended(NEW.project_id::text, 0));
      IF NEW.posting_type = 'reversal' THEN
        SELECT * INTO original FROM inventory_postings WHERE id = NEW.reversal_of_posting_id;
        IF NOT FOUND OR original.project_id <> NEW.project_id
           OR original.organisation_id <> NEW.organisation_id
           OR original.posting_type <> 'opening_stock' OR original.status <> 'posted'
           OR NEW.posting_date < original.posting_date THEN
          RAISE EXCEPTION 'invalid inventory reversal target';
        END IF;
      END IF;
      RETURN NEW;
    END; $$;
    """


def _line_guard(*, rounded: bool) -> str:
    precision_rule = "expected_canonical := round(expected_canonical, 12);" if rounded else ""
    return f"""
    CREATE OR REPLACE FUNCTION vantix_guard_inventory_line() RETURNS trigger
    LANGUAGE plpgsql AS $$
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
      {precision_rule}
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
        IF NOT FOUND OR NEW.configuration_product_version_id <>
           original_line.configuration_product_version_id
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
    """


def upgrade() -> None:
    op.alter_column(
        "alembic_version",
        "version_num",
        existing_type=sa.String(length=32),
        type_=sa.String(length=64),
        existing_nullable=False,
    )
    op.execute(_posting_guard(hardened=True))
    op.execute(_line_guard(rounded=True))


def downgrade() -> None:
    op.execute(_posting_guard(hardened=False))
    op.execute(_line_guard(rounded=False))
