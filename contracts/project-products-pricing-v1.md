# Project Products and Pricing Contract V1

## Boundary

This contract defines configuration-owned project products and effective-dated price authority. It does not create inventory postings, receipts, transfers, consumption, adjustments, balances, opening stock, or cost reconciliation.

## Product

- Stable product identity is an immutable, project-scoped `product_definition_id`. Each
  configuration owns a distinct product-version `id` that references that stable identity; item
  code is editable display authority and never ledger lineage.
- Required fields are item code/name, controlled packaging type, positive package size, package-content unit, explicit inventory applicability, and active state.
- Package-content units are `kg`, `t`, `lb`, `L`, `m3`, `gal_us`, `bbl`, or `each`.
- Inventory units additionally allow `package`. An inventory unit is required only when inventory applies and must be dimensionally compatible with package content unless it is `package`.
- Specific gravity is optional. Missing SG remains absent/unavailable; it is never defaulted. When supplied it is a positive canonical decimal string.

## Price

- Price uses a non-negative canonical decimal string, project currency, explicit basis unit, inclusive `effective_from`, and optional exclusive `effective_to`.
- Price basis is `package` or dimensionally compatible with package content, including when stock
  is counted in packages (for example, a 25 kg sack priced per tonne or a 200 L drum per litre).
- `effective_from` is never inferred from browser, server, or entry date; the user must supply it.
- Periods for one product cannot overlap. Adjacent periods may share the prior exclusive end/new inclusive start date.
- Price lookup selects the one period containing the requested date or returns unavailable/not found.

## Lifecycle

- Products and prices may change only while their configuration version is draft.
- Every mutation locks and increments the parent configuration row version, enforces expected-version concurrency, and writes an audit event.
- Readiness requires at least one active product and at least one effective price for every active product.
- Validation checksum and activation use the composed interval/product/price payload.
- Activation freezes canonically ordered products and prices in the immutable project snapshot.
- Creating a revised draft creates new product-version and price-version IDs while preserving each
  stable `product_definition_id`; prior snapshot content remains unchanged.
- Snapshots contain both stable product identity and the applicable configuration product-version
  identity. Future ledger lines reference the stable identity and freeze product/price version context.
- Unsaved product rows, price drafts, and new-product drafts invalidate readiness and block
  validation/activation until explicitly saved or discarded.
- Draft product deletion explicitly deletes price children before the product version in one
  transaction; row-version, audit, and deletion either all commit or all roll back.

## Acceptance

- VTX-PRO-001: code, name, packaging, units, applicability, and optional SG are explicit and validated.
- VTX-PRO-002: effective periods cannot overlap at domain or PostgreSQL boundaries.
- VTX-PRO-003: lookup applies inclusive-start/exclusive-end selection.
- VTX-PRJ-002 to VTX-PRJ-005: product readiness and snapshot binding participate in the configuration lifecycle.
- VTX-PRO-004 remains open until the later posting slice proves catalogue edits cannot alter posted cost.
- VTX-PRO-005 remains open until starting stock can create an append-only opening posting.
