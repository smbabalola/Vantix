# Vantix Master App Document

## 1. Product definition

Vantix is a multi-organisation drilling-fluids operations, reconciliation, and reporting platform.

```text
Project configuration
-> Daily operational data
-> Inventory and volume reconciliation
-> Review and approval
-> Frozen PDF/Excel report
-> Auditable revisions and amendments
```

It is reporting and decision-support software, not rig-control software.

### Prescribed architecture

- React, TypeScript, and Vite
- FastAPI
- pure-Python `vantix_core`
- PostgreSQL and Alembic
- object storage
- WeasyPrint and openpyxl
- Docker deployment
- PWA draft caching within the defined offline boundary

### Product invariants

- explicit units and dimensional validation
- explicit missing, unavailable, estimated, and not-applicable states
- immutable submitted and approved report revisions
- rejected submissions retained in history
- append-only inventory and volume ledgers
- reversal/replacement corrections
- effective-dated prices frozen at posting
- optimistic concurrency for drafts
- idempotent posting and submission
- tenant-aware permissions with database RLS
- complete audit history
- deterministic canonical report payload

## 2. Source-derived information architecture

### Project setup areas

General, Intervals, Personnel, Products, Screens, Equipment, Formation/Fluid Systems, Directional, Pits, Losses, Plan Data, Utility/Integrations, and Filtration.

### Daily operation areas

General, Comments, Pumps/Drilling Parameters, Fluid Checks, Geometry, Drillstring/BHA, Transfers, Inventory, Screens, Equipment, Volume Accounting, Displacements, Filtration, Waste, Losses, Daily Reports, and Excel Reports.

The source screenshots establish the broader roadmap. They do not make every module part of MVP. `docs/12-mvp-baseline.md` is authoritative for scope.

## 3. Platform contracts

### Organisation and access

- OIDC authentication
- organisation and project membership
- explicit capability checks
- separate submit/review/approve authority
- no self-approval by default
- server-side visibility filtering
- PostgreSQL RLS and scoped repositories

See `docs/13-auth-tenancy-permissions.md`.

### Configuration versions

Project setup is mutable only in a draft configuration version. Activation validates and freezes a configuration snapshot. Daily report revisions reference an immutable configuration snapshot.

### Report revision lifecycle

```text
Draft revision (mutable)
-> Ready for review
-> Submitted revision (immutable)
-> Approved revision (immutable and locked)

Submitted revision
-> Rejected decision (submitted revision retained)
-> New draft revision based on rejected revision

Approved revision
-> Amendment draft
-> Submitted amendment revision
-> Approved amendment revision
-> Prior approved revision becomes superseded
```

A rejected submission never returns the same submitted record to draft.

### Availability

Values use: `ready`, `incomplete`, `estimated`, `unavailable`, `not_applicable`, or `out_of_balance`. Zero is valid only when entered or calculated.

### Units

Canonical units are handled in `vantix_core`; APIs and UI carry unit metadata. Imports never guess units.

### Transactions

Inventory and volume use append-only posting groups and signed ledger lines. Physical counts/readings remain separate. See `docs/14-reconciliation-contracts.md`.

### Reporting

Submission creates a canonical frozen payload. PDF and Excel render only from that payload. See `docs/15-report-determinism.md`.

### Offline

MVP supports cached draft editing. Posting, submission, approval, official export, project configuration, and imports require an online server. See `docs/16-offline-and-conflict-contract.md`.

## 4. MVP boundary

### Foundation slice

- authentication, organisation, membership, and RLS
- project and configuration snapshot
- daily report draft revision
- readiness validation
- submission, rejection/revision, approval, and audit
- canonical payload and PDF/Excel contract

### Production MVP operational core

- daily general, time, problems, comments
- products, prices, transfers, inventory, physical count, variance, and chemical cost
- pits, volume movements, losses, physical readings, and reconciliation
- fluid systems and fluid checks
- client/internal report visibility

### Later

Personnel charging, screens, equipment, directional, geometry, BHA, pumps/drilling parameters, displacements, filtration, waste, integrations, advanced offline synchronisation, and analytics.

See `docs/12-mvp-baseline.md` for the authoritative module table.

## 5. Core workflows

### Project mobilisation

1. Create project.
2. Prepare configuration version.
3. Define identity, units, basic interval, fluid systems, products, prices, and pits required by MVP.
4. Run readiness validation.
5. Activate immutable configuration snapshot.

### Create day

1. Create report aggregate and draft revision online.
2. Choose project defaults or prior approved closing state.
3. Edit mutable sections with autosave and optimistic concurrency.
4. Draft unposted transactions as needed.
5. Post inventory/volume transactions online.
6. Review readiness and reconciliation.

### Submit, reject, approve

1. Submit current draft version online.
2. Server validates, canonicalises, checksums, and stores immutable submitted revision.
3. Reviewer approves or rejects that exact revision/checksum.
4. Rejection creates a new draft; approval locks the revision and starts export jobs.

### Amend

1. Create amendment draft from approved revision.
2. Record reason and changes.
3. Submit and approve as a new immutable revision.
4. Preserve prior approved version as superseded.

## 6. Module status

The detailed specifications remain in `docs/07-module-specifications.md`. MVP classification is controlled by `docs/12-mvp-baseline.md`, not by the presence of a source screen.

## 7. Implementation order

1. Restore and validate documentation.
2. Scaffold frontend, API, domain package, database, RLS, migrations, and tests.
3. Build foundation lifecycle slice end to end.
4. Add product/inventory/transfer ledger.
5. Add pits/volume/loss ledger.
6. Add fluid systems/checks.
7. complete production-MVP report sections and hardening.
8. Add later modules incrementally.

## 8. Success criteria

- no approved or submitted revision can be silently changed
- rejection and amendment history is complete
- cross-tenant access is blocked at API and database levels
- balances follow documented ledger equations
- physical and calculated balances remain separate
- units and missing states are explicit
- PDF and Excel use the same payload checksum
- offline edits never overwrite newer server work silently
- every mutation is auditable
