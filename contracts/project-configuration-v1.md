# Project Configuration V1 Contract

This contract defines the foundation configuration revision activated into an immutable project
snapshot. Later MVP modules extend it through explicit schema versions.

## Draft data

```json
{
  "default_interval_id": "uuid",
  "intervals": [
    {
      "id": "uuid",
      "name": "12 1/4 in hole section",
      "operation_mode": "drilling",
      "top_md": {"value": "1000", "unit": "m", "provenance": "entered"},
      "bottom_md": {"value": "1800", "unit": "m", "provenance": "entered"}
    }
  ]
}
```

`top_md` and `bottom_md` are optional. No other interval or later-module values are inferred.

## Activation readiness

- project code, project name, well name, time zone, currency, and unit set exist
- at least one interval has UUID, name, and operation mode
- `default_interval_id` references exactly one configured interval
- interval IDs are unique
- optional depth values are finite non-negative decimal strings using controlled `m` or `ft` units
- depth units match the authoritative project profile (`Metric -> m`, `Field -> ft`)
- operation mode is `drilling`, `completion`, or `workover`
- when both depth bounds exist, bottom MD is greater than top MD

## Lifecycle

```text
Mutable draft version
-> readiness validation
-> atomic activation
-> immutable active version and snapshot
-> superseded only by activation of a later version
```

Draft updates require optimistic concurrency. Active/superseded data never changes. A new daily
report revision stores the active snapshot ID at creation and retains it for its full lineage unless
an explicit draft-only refresh operation is introduced by a later contract.

Each project has at most one mutable draft and one active version. Draft creation is idempotent.
Validation returns the draft row version and canonical checksum; activation requires both and
fails if the draft changed. Only the latest version, newer than the active version, may activate.
All configuration, snapshot, project pointer, report, and revision relationships are constrained to
the same organisation and project.
