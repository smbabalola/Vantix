# Inventory Ledger Supplier Receipts Contract V1

## Boundary

This slice adds immutable supplier receipts to the project inventory ledger. It excludes purchase
order workflow, accounts-payable matching, freight allocation, landed-cost apportionment, transfers,
consumption, returns, adjustments, physical counts, balances, reconciliation, inter-project
movements, and weighted-average/FIFO costing.

## Receipt identity and authority

- A receipt is an online project-level posting, independent of a daily-report revision.
- The authenticated posting actor is stored as both `received_by_user_id` and `posted_by`; V1 does
  not permit the client to nominate another receiving user.
- Required documentary identity is `supplier_name` and `delivery_note_number`. Optional references
  are purchase order and invoice numbers.
- Supplier and delivery-note values are trimmed for storage. A normalized case-insensitive key makes
  delivery note identity unique within project and supplier. Reversal does not free that identity
  for reuse.
- Preview and posting carry the reviewed `expected_configuration_snapshot_id` and explicit posting
  date. Posting locks the project and returns `412 INVENTORY_AUTHORITY_CHANGED` before any write if
  the current snapshot changed.
- A transaction-local `building` header, every line, the idempotency record, and audit event commit
  atomically as `posted`; no mutable server receipt draft persists.

## Lines and canonical quantity

Each line carries stable `product_definition_id`, entered positive quantity and controlled unit,
optional batch/lot number, optional manufacture date, and optional expiry date. Expiry must be later
than manufacture when both are supplied.

The server resolves the exact configuration product from the reviewed snapshot and freezes product
version, names, packaging, package size/content unit, inventory unit, and optional SG.

```text
canonical_quantity = entered_quantity * entered_unit_to_canonical_factor

or, for packages:

canonical_quantity = entered_packages
                   * frozen_package_size
                   * frozen_package_unit_to_canonical_factor
```

Canonical ledger quantity is rounded `ROUND_HALF_UP` to at most 12 decimal places before preview,
cost calculation, persistence, and database validation. Receipt quantity is positive; reversal
copies and negates it exactly.

## Cost source and precedence

Controlled `cost_source` values are:

```text
supplier_document
configured_effective_price
unavailable
```

- An entered supplier-document unit price requires explicit basis unit and currency. Currency must
  equal project currency because V1 performs no foreign-exchange conversion.
- Supplier-document price always wins when supplied; configured price must never override it.
- When supplier price is absent, the server may select the product's configured effective price for
  the posting date using `[effective_from, effective_to)` semantics.
- When neither price exists, quantity may post with `cost_source=unavailable`; all monetary fields
  remain null. Zero is never substituted.
- Supplier and configured basis units must be `package` or dimensionally compatible with frozen
  package content.
- Line amount is calculated from the rounded canonical quantity and frozen package conversion, then
  rounded `ROUND_HALF_UP` to the frozen currency minor-unit scale.
- The line freezes supplier or configured unit price, basis, currency, scale, configured price ID
  and effective period when applicable, calculated amount, and cost source. Later catalogue,
  supplier, configuration, package, or price changes cannot alter it.

## Preview, posting, and idempotency

- Server preview performs the exact resolution, conversion, pricing, and rounding used by posting
  without writing business, idempotency, or audit data.
- Preview returns source snapshot, entered/package/canonical quantities, cost-source classification,
  applied unit price/basis, effective configured-price period when applicable, line values,
  unavailable states, and totals by currency.
- Posting requires `post_inventory` and `Idempotency-Key`. Same organisation/operation/key and same
  request returns the original receipt. Reusing the key with different content returns 409.
- Clients preserve one key across uncertain retries and reset it only after confirmed success or a
  material payload change.
- The delivery-note uniqueness conflict is distinct from idempotent retry.

## Reversal

- Reversal requires an explicit date, non-empty reason, `post_inventory`, and idempotency key.
- It copies the original source snapshot and frozen line context without current product, package,
  supplier, or price lookup.
- Entered/canonical quantities and line amounts are exact opposites. Batch/lot and date provenance,
  cost source, supplier price, configured price identity, currency, and scale are retained.
- One original receipt may be reversed once. Original headers and lines remain unchanged.

## Database enforcement

PostgreSQL independently prevents raw SQL from:

- posting a receipt against a non-current or cross-project snapshot;
- attaching a product outside the source snapshot or a mismatched stable lineage;
- forging frozen product/package fields or canonical conversion;
- attaching an unrelated or ineffective configured price;
- changing supplier-price authority, cost source, currency, scale, or line amount;
- creating a duplicate normalized project/supplier/delivery-note identity;
- updating/deleting posted headers or lines;
- reversing a receipt twice or using a snapshot different from the original.

Tenant/project RLS and database-backed `view_inventory`/`post_inventory` capability checks apply to
all receipt authority, preview, posting, reversal, and history paths.

## Operational presentation

The online workspace stages receipt details, receipt lines, server preview, then immutable posting.
Dates begin blank. Units, supplier/configured/unavailable cost source, package conversion, canonical
quantity, line amount, totals, source snapshot, and online/pending/error states remain visible.

History shows supplier, delivery note, references, date, actor, snapshot, cost availability, totals,
reversal relationships, and expandable frozen line detail including batch and manufacture/expiry.

## Acceptance

- VTX-TRF-002, VTX-REC-002: receipt header, lines, idempotency, and audit are atomic.
- VTX-TRF-003: received quantity controls the positive ledger posting.
- VTX-TRF-004, VTX-TRF-007: normalized documentary identity is unique within project/supplier.
- VTX-TRF-005, VTX-REC-004, VTX-REC-015: reversal is exact and single-use.
- VTX-TRF-006, VTX-REC-003: uncertain retry does not double-post.
- VTX-TRF-008: supplier-document price takes precedence over configured price.
- VTX-TRF-009: missing cost remains unavailable, never zero.
- VTX-TRF-010: preview and posting bind to the same current reviewed snapshot and calculations.
- VTX-TRF-011: raw SQL cannot forge receipt product, conversion, cost, or snapshot authority.
- VTX-TRF-012, VTX-PRO-004, VTX-REC-014: frozen receipt history is immutable under later changes.
- VTX-CST-001 and VTX-CST-002: Decimal money and frozen currency scale are authoritative.
