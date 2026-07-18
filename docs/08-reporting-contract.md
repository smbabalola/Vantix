# Vantix Reporting Contract

## 1. Authority

`docs/15-report-determinism.md` defines canonical serialization, precision, checksums, template/renderer versions, and regeneration. This document defines report content and lifecycle integration.

## 2. Revision stages

### Draft preview

Mutable, not authoritative, visibly watermarked. It may be built from current draft data.

### Submitted revision

Submission validates the expected draft version, creates an immutable revision and canonical payload/checksum, and records a decision event. The mutable draft closes.

### Rejection

The submitted revision remains immutable and is marked rejected. A new draft revision is created from it. Reviewer reason and lineage are retained.

### Approval

Approval acts on a specific submitted revision ID and checksum. The revision becomes approved/locked. PDF and Excel jobs use its frozen payload.

### Amendment

An approved revision is never edited. An amendment draft creates a new lineage revision; approval supersedes the prior current approved revision without deleting it.

## 3. Envelope metadata

- schema/template/renderer versions
- payload/revision number
- report ID/number/date/time zone
- state and revision kind
- parent/based-on/amendment references
- project configuration snapshot/checksum
- unit set and currency
- submit/reject/approve metadata
- visibility policy version
- canonical payload checksum

## 4. Standard MVP sections

1. Project/report header
2. Operations/general
3. Time distribution
4. Problems
5. Comments/remarks
6. Fluid checks
7. Material transfers
8. Inventory/chemical usage
9. Pits/volume movements
10. Losses
11. Cost summary
12. Readiness/reconciliation/caveats
13. Approval and revision history

Later-module sections are added only when the module is implemented.

## 5. Field contract

```json
{
  "value": "10.20",
  "unit": "ppg",
  "status": "ready",
  "source": {"type": "fluid_check_value", "id": "uuid"},
  "basis": "primary_check",
  "caveats": []
}
```

## 6. Submission validation

Blocking:

- missing identity/configuration snapshot
- invalid or missing units on required values
- invalid time total when required
- unposted draft transaction claimed in balance
- unresolved optimistic-concurrency conflict
- canonical serialization failure
- payload/schema/template incompatibility

Policy warning/block:

- negative inventory
- inventory variance
- volume variance
- pit capacity breach
- out-of-spec fluid property without comment
- unresolved operational problem

## 7. PDF

- generated only from frozen payload for official exports
- repeating report/revision header
- units in tables
- no clipped columns
- state/revision watermark
- caveats near affected content
- approval block and payload checksum fragment
- internal/client visibility enforced server-side

## 8. Excel

MVP sheets:

- Summary
- Operations
- Fluid Checks
- Transfers
- Inventory
- Pits & Volumes
- Losses
- Costs
- Audit Metadata

Values and totals must match payload; numeric cells remain numeric where practical while authoritative decimals are preserved in the technical metadata sheet.

## 9. Acceptance criteria

- **VTX-RPT-001**: preview matches current draft data.
- **VTX-RPT-002**: submission creates immutable revision/payload/checksum.
- **VTX-RPT-003**: live-data changes do not alter submitted payload.
- **VTX-RPT-004**: rejection retains submitted revision.
- **VTX-RPT-005**: rejection creates new draft revision.
- **VTX-RPT-006**: approval is bound to revision/checksum.
- **VTX-RPT-007**: approved revision cannot be mutated.
- **VTX-RPT-008**: amendment preserves prior version.
- **VTX-RPT-009**: PDF and Excel totals match payload.
- **VTX-RPT-010**: unit-bearing values include units.
- **VTX-RPT-011**: unavailable values render honestly.
- **VTX-RPT-012**: client export excludes internal/restricted content.
- **VTX-RPT-013**: export history is audited.
- **VTX-RPT-014**: original export object is not overwritten.
- **VTX-RPT-015**: regeneration records template/renderer/payload versions.
- **VTX-RPT-016**: stored payload can be semantically reproduced.
