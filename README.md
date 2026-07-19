# Vantix

Vantix is an auditable drilling-fluids operations and reporting platform. The V2 files under
`docs/`, `contracts/`, `.qodo/agents/`, and `scripts/` are the authoritative specification.

## Implemented vertical slices

The foundation lifecycle is complete and hardened:

- organisation membership, project, and active configuration snapshot
- business day and optimistic-concurrency draft revision
- readiness validation and transactional submission
- immutable frozen payload and canonical checksum
- approval, rejection with a new draft revision, and audit history
- deterministic PDF and Excel rendering from the stored payload only
- membership-bound PostgreSQL RLS and database immutability triggers
- client-view filtering for internal comments
- IndexedDB caching for mutable draft patches only

The project-configuration snapshot slice adds:

- organisation-scoped project creation and authorised project reads
- versioned foundation configuration drafts with optimistic concurrency
- server-evaluated activation readiness for project identity and basic intervals
- optional measured-depth values with explicit units and entered provenance
- immutable canonical snapshots with checksums, actor, and activation time
- superseded configuration history and copied revision drafts
- immutable configuration-snapshot binding on every new report revision
- a responsive configuration workspace with honest unavailable-value states

The project-products/pricing slice adds:

- stable project product lineage with configuration-version-owned product authority
- explicit packaging and inventory units, including package-content-compatible pricing
- optional specific gravity with unavailable state preserved
- effective-dated project-currency prices using non-overlapping half-open periods
- optimistic concurrency, audit, RLS, and database immutability for product authority
- configuration readiness/checksum and immutable snapshot inclusion
- a responsive product/pricing grid with deliberate effective dates, field errors, and unsaved-work gating

The inventory-ledger/opening-stock slice adds:

- atomic append-only opening postings with stable product lineage and frozen product versions
- explicit entered and canonical quantities with package-to-content conversion
- effective-date price lookup with frozen price, currency, basis, and rounded line amount
- honest unavailable-price postings whose monetary fields remain null rather than zero
- idempotent posting, exact immutable reversals, audit events, and tenant/project RLS
- a practical opening-stock workspace with explicit units and immutable posting history

The supplier-receipts slice adds:

- immutable receipt headers with normalized supplier and delivery-note identity
- stable product lineage, frozen configuration-product/package context, and optional batch dates
- supplier-document price precedence with configured-price fallback and explicit unavailable cost
- server-authoritative canonical conversion, currency rounding, preview, and posting
- project/supplier delivery-note uniqueness, idempotency, audit, RLS, and exact line-linked reversals
- migration `0009_inventory_receipts`, preserving every previously merged migration unchanged
- a four-stage receipt workspace with frozen preview, cost-source visibility, and receipt history

Transfers, consumption, adjustments, physical counts, reconciliation, purchase-order workflow,
accounts-payable matching, inter-project movement, and inventory valuation remain outside this slice.

PostgreSQL is the default runtime repository. The in-memory adapter remains only as an explicit
test dependency override. Submission readiness, version checking, state transition, frozen
payload, checksum, idempotency record, and audit events are committed in one database transaction.

## Run locally

```bash
python -m pip install -e ".[dev]"
npm --prefix frontend install
python scripts/validate_documentation.py
python -m alembic upgrade head
python -m uvicorn app.main:app --app-dir backend --reload
npm --prefix frontend run dev
```

Set `VANTIX_DATABASE_URL` to the application-role PostgreSQL connection. Migration commands should
use a schema-owner connection.

## Quality gates

```bash
python -m ruff format --check backend
python -m ruff check backend
python -m mypy backend/app backend/vantix_core
python -m pytest backend/tests
python scripts/validate_documentation.py
npm --prefix frontend test -- --run
npm --prefix frontend run lint
npm --prefix frontend run build
```

Live PostgreSQL tests are intentionally separate from the default unit suite:

```bash
VANTIX_DATABASE_URL=postgresql+psycopg://vantix_test_app@localhost/vantix_test \
VANTIX_ADMIN_DATABASE_URL=postgresql+psycopg://postgres@localhost/vantix_test \
python -m pytest backend/tests_live
```

The live suite requires an empty disposable database at migration head. Its application role must
be `NOSUPERUSER NOBYPASSRLS` and have normal schema, table, sequence, and function privileges.

## Remaining limitations

- Authentication currently accepts signed Vantix development claims; production identity-provider
  integration and managed signing-key rotation are not configured.
- Export bytes are generated deterministically and recorded as export metadata, but production
  object-storage upload and authorised download-link delivery are not implemented.
- Draft caching is local-only; background synchronisation and broader offline operation remain out
  of MVP scope.
- Opening-stock postings are implemented. Receipts, transfers, consumption, adjustments, physical
  counts, balances, cost reconciliation, pits/volumes, and fluid checks remain deferred.
