# Daily Report Envelope — Canonical Outline

```json
{
  "schema_version": "1.0",
  "template": {"key": "daily-fluids-report", "version": "1.0"},
  "payload_version": 1,
  "revision": {"number": 1, "kind": "original", "state": "submitted", "parent_revision_id": null},
  "report": {
    "id": "uuid",
    "number": "string",
    "date": "YYYY-MM-DD",
    "time_zone": "Area/City",
    "state": "submitted",
    "operation": "completion",
    "interval": {"id": "uuid", "label": "Interval 1"},
    "fluid_system": {"id": "uuid", "name": "Sea Water"},
    "unit_set": {"id": "uuid", "name": "Field"},
    "currency": "GBP"
  },
  "project_snapshot": {},
  "operations": {
    "general": {},
    "time_distribution": [],
    "personnel": [],
    "problems": [],
    "comments": []
  },
  "technical": {
    "pumps_and_drilling": {},
    "fluid_checks": [],
    "geometry": {},
    "drillstring_bha": {},
    "displacements": [],
    "filtration": {}
  },
  "materials_and_fluids": {
    "transfers": [],
    "inventory": [],
    "screens": [],
    "equipment": [],
    "pits": [],
    "volume_transactions": [],
    "fluids_in_hole": [],
    "losses": [],
    "waste": []
  },
  "costs": {
    "chemicals": {},
    "personnel": {},
    "screens": {},
    "equipment": {},
    "waste": {},
    "other": {},
    "total": {}
  },
  "reconciliation": {
    "inventory": {},
    "volume": {},
    "time_distribution": {},
    "readiness": {}
  },
  "approval": {
    "submitted_by": {},
    "submitted_at": "ISO-8601",
    "approved_by": null,
    "approved_at": null,
    "amendment_of": null
  },
  "caveats": [],
  "checksum": "sha256"
}
```

## Rules

- The payload is self-contained enough to render without querying mutable business tables.
- Every unit-bearing calculated value uses the canonical value contract.
- IDs remain for traceability; human-readable labels are included.
- Internal content carries visibility metadata and is filtered by export policy.
- The final checksum is calculated on canonical serialised JSON excluding the checksum field itself.
- Canonical rules are defined in `docs/15-report-determinism.md`.
- The envelope belongs to one immutable submitted or approved revision.
