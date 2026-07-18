# Vantix Implementation Plan

## Delivery rule

Build one vertical slice at a time. A slice includes domain logic, schema/migration, API, permissions/RLS, UI, audit, tests, and report contract where applicable.

## Phase 0 — Documentation restoration and validation

- place all baseline documents under `docs/`
- place coding-agent rules at `.qodo/agents/agents.md`
- run `python scripts/validate_documentation.py`
- resolve all missing acceptance references
- correct corrupted encodings

Gate: VTX-MVP-001 and VTX-MVP-002.

## Phase 1 — Repository and platform scaffold

- frontend, backend, and `vantix_core`
- PostgreSQL/Alembic
- Docker Compose
- CI, typing, linting, unit tests
- OIDC skeleton
- structured logging/correlation IDs
- object-storage abstraction

## Phase 2 — Tenancy, permissions, and audit

- organisations/users/memberships/projects
- capability policy
- PostgreSQL RLS
- project membership
- audit append-only model
- cross-tenant tests

Acceptance: VTX-AUTH-001 to VTX-AUTH-012; VTX-AUD-001 to VTX-AUD-004.

## Phase 3 — Configuration snapshot

- project identity/basic interval/units
- draft configuration version
- readiness validation
- activation
- immutable configuration snapshot/checksum

Acceptance: VTX-PRJ-001 to VTX-PRJ-006; VTX-UNIT-001 to VTX-UNIT-003.

## Phase 4 — First end-to-end report lifecycle slice

- daily report aggregate
- mutable draft revision and section store
- optimistic concurrency
- readiness endpoint
- canonical payload builder
- immutable submission
- review decision bound to revision/checksum
- rejection -> new draft revision
- approval/lock
- audit history
- basic PDF and Excel

Acceptance: VTX-MVP-004 to VTX-MVP-012; VTX-API-001 to VTX-API-006; VTX-DET-001 to VTX-DET-012; VTX-RPT-001 to VTX-RPT-016.

## Phase 5 — Daily general and comments

- report context
- time distribution
- problems
- comments and visibility
- offline draft caching for supported fields
- conflict UI

Acceptance: VTX-DAY-001 to VTX-DAY-010; VTX-COM-001 to VTX-COM-004; VTX-OFF-001 to VTX-OFF-012.

## Phase 6 — Products, prices, transfers, and inventory

- product setup
- effective price history
- draft transfer tickets
- atomic posting and idempotency
- signed inventory ledger
- reversals/adjustments
- physical counts/variance
- chemical cost
- report section

Acceptance: VTX-PRO-001 to VTX-PRO-005; VTX-TRF-001 to VTX-TRF-006; VTX-INV-001 to VTX-INV-008; VTX-CST-001 to VTX-CST-004; VTX-REC-001 to VTX-REC-008 and VTX-REC-014 to VTX-REC-015.

## Phase 7 — Pits, volume movements, and losses

- pit setup/readings
- signed volume ledger
- atomic pit-to-pit transfer
- build/receive/backload/dump/loss
- surface/subsurface loss event
- fluids in hole snapshot
- physical vs expected closing and tolerance
- report section

Acceptance: VTX-PIT-001 to VTX-PIT-004; VTX-VOL-001 to VTX-VOL-009; VTX-LOS-001 to VTX-LOS-005; VTX-REC-009 to VTX-REC-013.

## Phase 8 — Fluid systems and checks

- configurable properties/units
- samples and primary check
- specifications/out-of-spec status
- missing value handling
- report section

Acceptance: VTX-FSY-001 to VTX-FSY-005; VTX-FLD-001 to VTX-FLD-007.

## Phase 9 — Production-MVP hardening

- complete report template
- PDF/Excel regression suite
- accessibility
- performance
- backup/restore
- security review
- production deployment/runbook

## Phase 10 — Later modules

Promote modules only through the scope-change rule in `docs/12-mvp-baseline.md`:

- personnel charging
- screens/equipment
- pumps/drilling parameters
- directional/geometry/BHA
- displacement/filtration/waste
- external integrations
- advanced offline
- analytics

## Branch and commit pattern

For every slice:

1. update dated specification and acceptance IDs
2. domain implementation/tests
3. migration and RLS tests
4. API/contract tests
5. UI/interaction tests
6. report fixture tests
7. audit/idempotency tests
8. documentation and handover

Do not combine unrelated modules in one commit.

## Release gates

- documentation validator passes
- all MVP acceptance IDs mapped to tests
- cross-tenant suite passes
- immutable revision tests pass
- ledger/reversal/idempotency tests pass
- PDF/Excel payload checks pass
- migrations tested on realistic data
- backup/restore verified
- no unresolved critical security finding
