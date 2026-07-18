# MVP Offline and Conflict Contract

## 1. MVP objective

MVP offline support prevents loss of draft work during intermittent wellsite connectivity. It is not a complete offline operational database.

## 2. Actions supported offline in MVP

When a project/day has previously been opened online, the client may:

- read the cached project/day context required for the draft
- edit scalar fields in a mutable daily draft revision
- add/edit/delete unposted draft rows for general data, time entries, problems, comments, fluid checks, inventory-usage drafts, and volume-movement drafts
- create local draft attachments metadata and queue the file only when browser storage policy allows
- view locally calculated presentation summaries clearly marked `Offline draft`

Local rows use client-generated UUIDs and retain the server `base_row_version` or draft revision version from the last successful sync.

## 3. Actions not supported offline in MVP

The client must be online to:

- create or activate project configuration versions
- create the first daily report for a date
- post inventory or volume transactions
- post transfer tickets
- submit, reject, approve, lock, or amend a report
- generate official PDF/Excel exports
- import files or synchronise external systems
- finalise attachment upload
- change organisation membership or permissions

An offline user can draft transaction details, but posting occurs only after server validation and permission checks.

## 4. Local storage

- Use IndexedDB through a versioned local data layer.
- Cache only projects/days the user has opened and is authorised to edit.
- Store minimal reference data and unsynchronised draft patches.
- Clear cached data on sign-out where browser capability permits.
- Expire stale cached reference data according to organisation policy.
- Never store access/refresh tokens in the draft database.
- Sensitive restricted comments may be excluded from offline caching by policy.

## 5. Sync protocol

Each queued mutation includes:

- local mutation ID
- organisation/project/report/draft revision IDs
- entity/field or row target
- operation
- base row/draft version
- payload
- client timestamp for diagnostics only
- idempotency key

Server response returns accepted mutation IDs and new versions.

## 6. Conflict rules

No last-write-wins.

### Scalar section fields

- If server version equals base version, apply patch.
- If changed fields do not overlap, server may merge and return a new version.
- If the same field changed, create a conflict requiring user selection.

### Line-item rows

- Different row IDs can merge.
- Same row changed on both sides creates row-level conflict.
- A locally edited row deleted on server creates conflict; it is not recreated automatically.
- Posted/locked server rows reject offline mutation and remain authoritative.

### Resolution UI

Show:

- local value
- server value
- last known base value
- actor/time where permitted
- options to keep server, apply local as new edit, or manually combine

Resolved changes create normal audit events. The original conflict record remains for diagnostics.

## 7. Read-only transition

If a draft is submitted or replaced by a newer revision while another device is offline:

- offline edits cannot mutate the submitted revision
- on reconnect, Vantix offers to copy compatible local changes into the active new draft revision when one exists
- the user must review the copy; nothing is silently applied

## 8. Presentation calculations offline

The client may calculate non-authoritative previews using shared generated formulas only when they are clearly marked. Server reconciliation after sync is authoritative. Official readiness, balances, costs, submission, and exports require online server evaluation.

## 9. Acceptance criteria

- **VTX-OFF-001**: cached draft opens without network.
- **VTX-OFF-002**: local edit survives refresh/browser interruption.
- **VTX-OFF-003**: unsupported offline action is disabled with explanation.
- **VTX-OFF-004**: local mutation has idempotency key and base version.
- **VTX-OFF-005**: non-overlapping scalar changes merge safely.
- **VTX-OFF-006**: overlapping field change creates conflict.
- **VTX-OFF-007**: same-row concurrent edit creates conflict.
- **VTX-OFF-008**: submitted/locked revision rejects offline mutation.
- **VTX-OFF-009**: no last-write-wins overwrite occurs.
- **VTX-OFF-010**: conflict resolution is audited.
- **VTX-OFF-011**: server reconciliation replaces offline preview authority.
- **VTX-OFF-012**: sign-out removes accessible local draft data according to policy.
