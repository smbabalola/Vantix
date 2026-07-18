# Project Products and Pricing Contract V1

## Boundary

This contract defines configuration-owned project products and effective-dated price authority. It does not create inventory postings, receipts, transfers, consumption, adjustments, balances, opening stock, or cost reconciliation.

## Product

- Product identity is a UUID plus a case-insensitively unique item code within one configuration version.
- Required fields are item code/name, controlled packaging type, positive package size, package-content unit, explicit inventory applicability, and active state.
- Package-content units are `kg`, `t`, `lb`, `L`, `m3`, `gal_us`, `bbl`, or `each`.
- Inventory units additionally allow `package`. An inventory unit is required only when inventory applies and must be dimensionally compatible with package content unless it is `package`.
- Specific gravity is optional. Missing SG remains absent/unavailable; it is never defaulted. When supplied it is a positive canonical decimal string.

## Price

- Price uses a non-negative canonical decimal string, project currency, explicit basis unit, inclusive `effective_from`, and optional exclusive `effective_to`.
- Price basis is `package` or dimensionally compatible with the product authority.
- Periods for one product cannot overlap. Adjacent periods may share the prior exclusive end/new inclusive start date.
- Price lookup selects the one period containing the requested date or returns unavailable/not found.

## Lifecycle

- Products and prices may change only while their configuration version is draft.
- Every mutation locks and increments the parent configuration row version, enforces expected-version concurrency, and writes an audit event.
- Readiness requires at least one active product and at least one effective price for every active product.
- Validation checksum and activation use the composed interval/product/price payload.
- Activation freezes canonically ordered products and prices in the immutable project snapshot.
- Creating a revised draft copies active products and prices with new identities; prior snapshot content remains unchanged.

## Acceptance

- VTX-PRO-001: code, name, packaging, units, applicability, and optional SG are explicit and validated.
- VTX-PRO-002: effective periods cannot overlap at domain or PostgreSQL boundaries.
- VTX-PRO-003: lookup applies inclusive-start/exclusive-end selection.
- VTX-PRJ-002 to VTX-PRJ-005: product readiness and snapshot binding participate in the configuration lifecycle.
- VTX-PRO-004 remains open until the later posting slice proves catalogue edits cannot alter posted cost.
- VTX-PRO-005 remains open until starting stock can create an append-only opening posting.
