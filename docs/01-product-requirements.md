# Vantix Product Requirements Document

## Product

**Vantix** — project setup, daily drilling-fluids operations, reconciliation, and auditable reporting.

## Problem

Legacy reporting and spreadsheets create repeated entry, inconsistent units, unexplained balances, weak version control, and uncertainty about which report was submitted. Vantix provides one structured record from project configuration to approved PDF/Excel.

## Users

- report editor / mud engineer
- fluids supervisor / reviewer
- project or operations administrator
- logistics user
- cost reviewer
- approver
- client viewer
- auditor

## Core workflow

```text
Project configuration
-> Daily draft revision
-> Posted operational transactions
-> Readiness and reconciliation
-> Immutable submitted revision
-> Approval or rejected revision
-> Frozen PDF/Excel
-> Amendment lineage
```

## Foundation slice requirements

- organisation and project tenancy
- authentication and membership
- active project configuration snapshot
- units
- draft report revision
- optimistic concurrency
- readiness validation framework
- immutable submission
- rejection preserving submitted revision and creating a new draft
- approval and lock
- audit history
- canonical payload and deterministic report contract

Acceptance: VTX-MVP-001 to VTX-MVP-012.

## Production MVP requirements

### Daily operational record

- report identity/date/operation/basic interval/fluid system
- general information
- time distribution
- operational and fluid problems
- internal and client-visible comments

### Products and inventory

- product master and effective-dated price
- receipt, return, transfer, usage, reversal, and adjustment
- opening/calculated/physical closing
- variance and status
- chemical cost

### Pits and volume

- pit setup and capacity
- opening/closing readings
- fluid build, receipt, transfer, dump/backload, loss, reversal, and adjustment
- fluids-in-hole snapshot kept separate
- surface/subsurface loss summary
- variance and status

### Fluid checks

- configurable properties and units
- multiple samples
- sample time/source
- specification range and out-of-spec status
- primary check
- missing-value status

### Review and reporting

- section readiness
- inventory/volume/time reconciliation
- submit/reject/revise/approve/amend
- PDF and Excel from frozen payload
- internal/client visibility
- report/export history

## Later modules

Personnel charging, screens, equipment, detailed formation/temperature, directional, geometry, BHA, pumps/drilling parameters, displacements, filtration, waste, external integrations, advanced offline queue, and analytics.

## Product rules

1. Missing is not zero.
2. Units are explicit.
3. Authoritative totals live in `vantix_core`.
4. Drafts are mutable; submitted revisions are immutable.
5. Rejection creates a new draft revision.
6. Approval is bound to exact revision/checksum.
7. Ledger balances are calculated from posted signed lines.
8. Physical counts/readings remain separate.
9. Posted transactions reverse; they are not edited.
10. Historical applied price remains frozen.
11. Client output is server-filtered.
12. Offline MVP supports draft editing only; official actions require online server.
13. Every mutation creates an audit event.
14. Cross-tenant access is denied by API and RLS.

## Out of scope for MVP

- rig/equipment control
- autonomous engineering decisions
- WellOptix-class simulation
- hidden balance correction
- unreviewed AI-authored final comments
- direct ERP posting
- advanced fields whose source workflow is unknown

## Success metrics

- draft creation from prior state below two minutes
- 100% of submitted revisions have immutable payload/checksum
- 100% of unit-bearing fields carry a unit
- PDF/Excel totals match payload
- cross-tenant isolation tests pass
- no duplicate posting under idempotent retry
- inventory and volume variance shown for every applicable report
- rejected and amended reports preserve full lineage
