# Vantix Coding-Agent Rules

## Mandatory read order

Before changing application code, read these documents in order:

1. `docs/00-vantix-master-app-document.md`
2. `docs/12-mvp-baseline.md`
3. `docs/13-auth-tenancy-permissions.md`
4. `docs/14-reconciliation-contracts.md`
5. `docs/15-report-determinism.md`
6. `docs/16-offline-and-conflict-contract.md`
7. `docs/17-api-contracts.md`
8. `docs/18-mvp-requirement-traceability.md`
9. the relevant module in `docs/07-module-specifications.md`
10. `docs/05-backend-schema.md`
11. the relevant acceptance IDs in `docs/10-qa-and-acceptance.md`

If a required document or acceptance ID is missing, stop implementation of that feature and update the documentation first.

## Source-of-truth order

1. Approved product decision recorded in the repository.
2. The cross-cutting contracts listed above.
3. Module specification.
4. Backend schema and API contract.
5. Source screenshots and migration evidence.
6. A proposed default explicitly marked as proposed.

Never turn a proposal, inference, or source gap into an observed requirement.

## Product invariants

1. Vantix is reporting and operational decision support. It does not control rig equipment.
2. Unit-bearing values always carry a dimensionally valid unit.
3. Missing data stays missing. Never replace it with zero, copied data, or a hidden default.
4. Derived values expose status, basis, provenance, and caveats.
5. A submitted report revision is immutable.
6. Rejection preserves the submitted revision and creates a new draft revision.
7. An approved report is changed only through an amendment revision.
8. Inventory and volume balances are ledger-derived.
9. Posted transactions are append-only; corrections use reversal and replacement.
10. Effective-dated prices are frozen on posted lines.
11. Project configuration used by a report is frozen in its configuration snapshot.
12. Every mutation produces an audit event.
13. Client-visible exports cannot contain internal-only content.
14. Tenant and project permissions are enforced server-side and at the database boundary.
15. Frontend calculations are presentational only; authoritative calculations live in `vantix_core`.

## Architecture rules

- React, TypeScript, and Vite frontend.
- FastAPI application services.
- Pure-Python `vantix_core` with no HTTP, ORM, object-storage, or browser dependencies.
- PostgreSQL and Alembic.
- PostgreSQL row-level security plus repository/service scoping for tenant defence in depth.
- Object storage for attachments and generated artefacts.
- WeasyPrint and openpyxl from a frozen canonical report payload.
- Optimistic concurrency on mutable drafts.
- Idempotency keys on posting, submission, import, and export requests.
- PWA local draft cache only within the MVP boundary defined in `docs/16-offline-and-conflict-contract.md`.

## Transaction rules

- A business posting and its ledger lines commit in one database transaction.
- A transfer with two sides must commit both sides or neither side.
- Reversal lines reference the original posting and have equal-and-opposite canonical quantities.
- Adjustments require reason, permission, and audit metadata.
- Physical counts/readings remain distinct from calculated ledger balances.
- No endpoint may edit a posted quantity, applied price, approved report payload, or audit event.

## Frontend rules

- Desktop-first and tablet-usable.
- Data-entry grids are keyboard navigable.
- Units appear in labels and column headers.
- Save state is always visible: `Saved`, `Saving`, `Offline draft`, `Sync pending`, `Conflict`, or `Failed`.
- Do not rely on colour alone.
- Use explicit states: `Ready`, `Incomplete`, `Estimated`, `Unavailable`, `Not applicable`, `Reconciled`, `Out of balance`.
- Validation remains visible next to the affected section or field; a toast is not sufficient.
- Submitted, rejected, approved, superseded, and amendment revisions are read-only views.

## Testing rules

Every vertical slice requires:

- domain tests
- API contract tests
- database constraint, RLS, and migration tests
- frontend interaction tests
- at least one unavailable or missing-basis test
- at least one idempotency test for posting endpoints
- at least one audit-history test for write operations
- report snapshot tests when the feature appears in PDF or Excel
- acceptance IDs referenced in test names or metadata

## Definition of done

A feature is complete only when:

- its MVP classification is explicit
- its acceptance IDs pass
- units and availability states are visible
- permissions and tenant isolation are enforced
- audit events are recorded
- transaction and reversal behaviour is defined where applicable
- report/export behaviour is defined
- empty, loading, error, offline, and conflict states are handled
- documentation and API contracts are updated
