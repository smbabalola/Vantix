# Production MVP Requirement Traceability Matrix

## Purpose

Every production-MVP requirement must map to acceptance IDs before implementation. This matrix is the implementation checklist; module breadth outside this table remains later scope.

| Requirement ID | MVP requirement | Acceptance IDs | Primary specification |
|---|---|---|---|
| MVP-FND-01 | Required documents exist at repository paths | VTX-MVP-001, VTX-MVP-002 | 12 MVP Baseline |
| MVP-FND-02 | OIDC identity maps to active organisation/project membership | VTX-AUTH-001, VTX-AUTH-002, VTX-AUTH-007 | 13 Auth/Tenancy |
| MVP-FND-03 | API, repository, and PostgreSQL RLS enforce tenant isolation | VTX-AUTH-003 to VTX-AUTH-006 | 13 Auth/Tenancy |
| MVP-FND-04 | Submit, review, and approve are separate capabilities | VTX-AUTH-008, VTX-AUTH-009, VTX-AUTH-012 | 13 Auth/Tenancy |
| MVP-FND-05 | Project configuration activates as immutable snapshot | VTX-MVP-004, VTX-PRJ-003 to VTX-PRJ-005 | 00 Master / 05 Schema |
| MVP-FND-06 | Draft revision uses optimistic concurrency | VTX-MVP-005, VTX-API-001 | 16 Offline / 17 API |
| MVP-FND-07 | Submission creates immutable revision and payload | VTX-MVP-006, VTX-RPT-002, VTX-DET-011 | 08 Reporting / 15 Determinism |
| MVP-FND-08 | Rejection retains submitted revision and opens new draft | VTX-MVP-007, VTX-MVP-008, VTX-API-005, VTX-RPT-004, VTX-RPT-005 | 00 Master / 17 API |
| MVP-FND-09 | Approval locks exact revision/checksum | VTX-MVP-009, VTX-AUTH-012, VTX-API-006, VTX-RPT-006, VTX-RPT-007 | 13 Auth / 08 Reporting |
| MVP-FND-10 | Every mutation and state transition is audited | VTX-MVP-010, VTX-AUD-001 to VTX-AUD-004 | 05 Schema / 10 QA |
| MVP-FND-11 | Canonical payload is stable and checksummed | VTX-MVP-011, VTX-MVP-012, VTX-DET-001 to VTX-DET-006 | 15 Determinism |
| MVP-FND-12 | PDF/Excel render from same frozen payload | VTX-RPT-009, VTX-DET-005, VTX-DET-006 | 08 Reporting / 15 Determinism |
| MVP-OPS-01 | Report stores date, operation, basic interval, fluid system, units | VTX-DAY-001, VTX-UNIT-001, VTX-UNIT-003 | 01 PRD / 07 Modules |
| MVP-OPS-02 | Time distribution is recorded and validated | VTX-DAY-010 | 05 Schema / 07 Modules |
| MVP-OPS-03 | Problems are recorded without copied defaults | VTX-DAY-002, VTX-DAY-010 | 03 App Flow / 07 Modules |
| MVP-OPS-04 | Comments support client/internal visibility | VTX-COM-001 to VTX-COM-004, VTX-AUTH-010 | 07 Modules / 13 Auth |
| MVP-PRO-01 | Stable project product lineage has configuration-owned product versions, explicit packaging/inventory units, applicability, optional SG, deliberate non-overlapping effective prices, and immutable snapshot authority | VTX-PRO-001 to VTX-PRO-004, VTX-PRJ-002 to VTX-PRJ-005 | 07 Modules / 05 Schema / project-products-pricing-v1 contract |
| MVP-PRO-02 | Starting stock creates an idempotent immutable opening posting with explicit units, active snapshot context, frozen price/cost or unavailable status, and reversal-only correction | VTX-PRO-004, VTX-PRO-005, VTX-REC-002 to VTX-REC-005, VTX-REC-007, VTX-REC-014, VTX-REC-015, VTX-CST-001, VTX-CST-002 | 14 Reconciliation / inventory-ledger-opening-stock-v1 contract |
| MVP-TRF-01 | Draft ticket has no balance effect | VTX-TRF-001, VTX-REC-001 | 14 Reconciliation |
| MVP-TRF-02 | Ticket posting is atomic and idempotent | VTX-TRF-002, VTX-TRF-003, VTX-TRF-006, VTX-REC-002, VTX-REC-003 | 14 Reconciliation / 17 API |
| MVP-TRF-03 | Posted correction reverses/replaces | VTX-TRF-005, VTX-REC-004, VTX-REC-005 | 14 Reconciliation |
| MVP-INV-01 | Closing stock follows signed ledger equation | VTX-INV-001, VTX-REC-007 | 14 Reconciliation |
| MVP-INV-02 | Physical count and variance remain separate | VTX-INV-002, VTX-INV-003, VTX-REC-008 | 14 Reconciliation |
| MVP-INV-03 | Applied price and chemical cost remain historical | VTX-CST-001 to VTX-CST-004, VTX-REC-014, VTX-REC-015 | 14 Reconciliation |
| MVP-PIT-01 | Transactional pits and capacity are configured | VTX-PIT-001, VTX-PIT-002, VTX-PIT-004 | 07 Modules |
| MVP-VOL-01 | Pit movement posting uses balanced signed lines | VTX-VOL-002, VTX-VOL-004, VTX-REC-009, VTX-REC-012 | 14 Reconciliation |
| MVP-VOL-02 | Physical closing and variance remain separate | VTX-VOL-001, VTX-VOL-003, VTX-VOL-009 | 14 Reconciliation |
| MVP-VOL-03 | Loss event and ledger deduction commit together | VTX-VOL-005, VTX-LOS-002, VTX-REC-010 | 14 Reconciliation |
| MVP-VOL-04 | Surface and subsurface losses remain distinct | VTX-VOL-006, VTX-LOS-004 | 07 Modules |
| MVP-VOL-05 | Adjustments require reason and authority | VTX-VOL-007, VTX-REC-013 | 13 Auth / 14 Reconciliation |
| MVP-FLD-01 | Fluid properties are configuration-driven with units | VTX-FLD-001, VTX-UNIT-002, VTX-UNIT-003 | 07 Modules |
| MVP-FLD-02 | Multiple checks and one primary check are supported | VTX-FLD-002, VTX-FLD-003 | 07 Modules |
| MVP-FLD-03 | Specification/out-of-spec and missing states are explicit | VTX-FLD-004 to VTX-FLD-007 | 07 Modules |
| MVP-OFF-01 | Previously opened mutable draft is available offline | VTX-OFF-001, VTX-OFF-002 | 16 Offline |
| MVP-OFF-02 | Posting/submission/approval/export require online server | VTX-OFF-003, VTX-OFF-008 | 16 Offline |
| MVP-OFF-03 | Sync has base version and no last-write-wins | VTX-OFF-004 to VTX-OFF-010 | 16 Offline |
| MVP-RPT-01 | Client export excludes internal/restricted content | VTX-RPT-012, VTX-AUTH-010 | 08 Reporting / 13 Auth |
| MVP-RPT-02 | Original export is retained; regeneration is versioned | VTX-RPT-013 to VTX-RPT-016, VTX-DET-007 to VTX-DET-010 | 08 Reporting / 15 Determinism |

## Test mapping rule

Each automated test for MVP behaviour includes at least one acceptance ID in its name, marker, or metadata. A CI traceability job must fail when an MVP requirement row has no matching test reference.
