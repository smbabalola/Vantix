# Inventory Ledger and Opening Stock Contract V1

## Boundary

This slice establishes the append-only inventory ledger through project opening-stock postings and
their reversals. It excludes receipts, transfers, consumption, adjustments, physical counts,
balances, reconciliation, cost variance, and inter-project movement.

## Authority and identity

- Opening stock is an online project-level business posting, not an editable product field and not
  owned by a daily-report revision.
- Preview and posting require the caller's reviewed `expected_configuration_snapshot_id` and an
  explicit posting date. The repository locks the project and rejects a changed active snapshot
  with `412 INVENTORY_AUTHORITY_CHANGED` before writing a posting, idempotency record, or audit.
- Each line references stable `product_definition_id`, freezes the active
  `project_product_version_id`, and freezes the selected `product_price_version_id` when available.
- Only active, inventory-applicable product versions from the active configuration may be posted.
- One unreversed opening-stock line may exist per project/product definition. A replacement opening
  may be posted only after the prior opening is reversed.

## Quantity conversion

All entered quantities are positive for opening stock. Canonical units are `kg` for mass, `L` for
volume, and `each` for count.

```text
canonical_quantity = entered_quantity * entered_unit_to_canonical_factor
```

For packages:

```text
canonical_quantity = entered_packages
                   * package_size
                   * package_content_unit_to_canonical_factor
```

Supported exact conversion factors are versioned domain constants. Unit dimension must match
package content unless the entered unit is `package`. Decimal arithmetic is authoritative.

## Price and cost freezing

- Price selection uses the configuration product version and explicit posting date with
  `[effective_from, effective_to)` semantics.
- A price per package uses canonical package content to derive package count. A content-unit price
  converts canonical quantity into the price-basis unit.
- Posted line amount uses `ROUND_HALF_UP` at the currency minor-unit scale.
- Monetary storage uses `NUMERIC(30,12)` and each priced line freezes its currency minor-unit
  scale. API money strings retain that exact scale, including four-decimal currencies.
- The line freezes selected price ID, unit price, basis, currency, amount, product/package context,
  and price availability.
- If no price is effective, quantity may still post, but price status is `unavailable` and all price
  and monetary fields remain null. Zero is never substituted.
- Later product, package, configuration, or price revisions cannot change a posted line.

## Posting transaction and idempotency

- Header, all ledger lines, idempotency record, and audit event commit in one transaction.
- A multi-line request is all-or-nothing.
- The repository locks stable product definitions in deterministic order and rejects an existing
  unreversed opening for the same lineage.
- Different product lineages may receive disjoint opening postings. Concurrent attempts for the
  same lineage serialize and exactly one may create an unreversed opening.
- A repeated organisation/operation/idempotency key with the same request returns the original
  posting; the same key with different content is rejected.
- A client preserves one idempotency key across uncertain retries and replaces it only after
  success or a material request change.
- V1 posts directly from a client-side draft grid; no mutable server posting draft exists. If a
  later slice introduces server drafts, it must use optimistic concurrency before posting.

## Reversal

- Reversal requires an explicit reversal date, non-empty reason, posting capability, and
  idempotency key.
- It appends a new posting linked to the original and exact opposite ledger lines.
- Canonical quantity and posted line amount are negated exactly. Entered quantity is negated in its
  original unit. Frozen product and price context is copied; no current lookup or recalculation occurs.
- Original headers and lines remain unchanged. A posting can be reversed once.

## Database validation

The line guard independently derives and validates the snapshot configuration, product lineage,
frozen product/package fields, unit conversion, canonical quantity, effective price and period,
currency scale, and rounded line amount. Raw SQL cannot substitute another project's snapshot,
attach a product or price outside the snapshot authority, alter conversion/cost context, reverse
twice, or update/delete a posted header or line.

## Operational presentation

- Posting and reversal dates start blank and require deliberate operator entry.
- Server preview is authoritative and shows entered and canonical quantities, frozen package
  conversion, package count when relevant, effective price period/basis, line amount, total, and
  unavailable-price state before posting.
- History exposes the source snapshot, frozen line authority and cost, posting status, and reversal
  relationship. Only product lineages with an unreversed opening are locked in the grid.

## Security and visibility

- `post_inventory` authorises opening and reversal mutations.
- `view_inventory` or `post_inventory` authorises inventory authority/posting reads.
- API scope, database membership capability, and PostgreSQL RLS all enforce organisation/project
  isolation. Client-only report access does not disclose internal stock cost.

## Acceptance

- VTX-PRO-004: later catalogue/price changes do not alter frozen posted cost.
- VTX-PRO-005: starting stock exists only as an immutable opening posting.
- VTX-REC-002: header, lines, idempotency, and audit are atomic.
- VTX-REC-003: idempotent retry does not duplicate stock.
- VTX-REC-004 and VTX-REC-015: reversal is exact opposite quantity and money.
- VTX-REC-005: posted header and lines cannot be edited or deleted.
- VTX-REC-007: opening quantities use the positive signed-ledger convention.
- VTX-REC-014: applied price and line amount remain historical.
- VTX-CST-001 and VTX-CST-002: frozen price and Decimal money rules are authoritative.
