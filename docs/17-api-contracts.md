# Vantix API Contracts — Foundation and MVP Core

## 1. General conventions

- Base path: `/api/v1`
- JSON request/response
- ISO 8601 timestamps
- decimal values encoded as strings
- mutations accept `Idempotency-Key` where stated
- mutable resources expose `version`
- updates require `If-Match: "<version>"` or body `expected_version`
- errors use stable code, message, field details, and correlation ID
- organisation/project scope comes from authorised context, not trusted body fields

## 2. Error shape

```json
{
  "code": "REPORT_VERSION_CONFLICT",
  "message": "The draft changed after it was loaded.",
  "correlation_id": "uuid",
  "details": {
    "expected_version": 4,
    "actual_version": 5,
    "conflicts": []
  }
}
```

## 3. Organisation and project

### `GET /organisations`

Returns organisations available to the authenticated user.

### `POST /organisations`

Capability: organisation creation policy.

Idempotent by request key.

### `GET /organisations/{organisation_id}/projects`

Tenant and membership scoped.

### `POST /organisations/{organisation_id}/projects`

Creates draft project.

Required MVP fields:

- project code/name
- well name
- operator/client optional
- rig/location optional
- time zone
- currency
- unit set

### `POST /projects/{project_id}/configuration-versions`

Creates mutable configuration version from current active version or blank defaults.

Optional body fields: `data`, `change_summary`, and `copy_active` (default true). When an active
version exists and `data` is omitted, the server copies the active structured configuration. The
response includes draft `row_version`.

### `GET /projects/{project_id}/configuration-versions`

Returns authorised version summaries and the active/superseded/draft state without exposing another
project's configuration.

### `GET /projects/{project_id}/configuration-versions/{version_id}`

Returns one authorised version and its structured data.

### `PATCH /projects/{project_id}/configuration-versions/{version_id}`

Updates a draft only. Requires `If-Match`/expected row version and returns the incremented version.
Active or superseded versions are locked.

### `POST /projects/{project_id}/configuration-versions/{version_id}/validate`

Returns activation readiness without changing state. Missing project identity/units, missing basic
interval/default interval/operation mode, invalid references, and invalid optional depth bounds are
reported explicitly.

### `POST /projects/{project_id}/configuration-versions/{version_id}/activate`

Validates readiness, freezes snapshot/checksum, and sets active version atomically.

Headers: `Idempotency-Key`.

Activation also supersedes the prior active version, records activation actor/time and audit events,
and updates the project's current configuration version/snapshot pointers in the same transaction.

## 4. Daily report aggregate and revisions

### `POST /projects/{project_id}/daily-reports`

Creates report aggregate and draft revision.

Required:

- report date
- optional shift code
- active configuration version ID
- creation mode: defaults/prior-approved

Online only. Idempotent.

### `GET /daily-reports/{report_id}`

Returns aggregate, active draft/submitted/approved revision references, state, and permissions.
Requires database-backed `view_draft_report` for non-approved revisions or `view_client_report` for
approved client content. Internal/restricted fields additionally require `view_internal_content`.

### `GET /daily-reports/{report_id}/revisions`

Returns revision history without restricted payload content unless authorised.

### `GET /daily-report-revisions/{revision_id}`

Returns one revision. Mutable only when `kind=draft` and active.

### `PATCH /daily-report-revisions/{revision_id}/sections/{section_key}`

Updates mutable draft section.

Requires optimistic concurrency. Returns new version and readiness delta.

### `POST /daily-report-revisions/{revision_id}/validate`

Returns full readiness, reconciliation, and warnings without state change.
Requires database-backed `view_draft_report`; client-only and capability-less memberships are denied.

### `POST /daily-report-revisions/{revision_id}/submit`

Online only. Headers: `Idempotency-Key`, `If-Match`.

Server:

1. locks draft revision
2. validates permissions/readiness
3. builds canonical payload
4. stores immutable submitted revision/payload/checksum
5. marks draft closed
6. records audit/approval event

Returns submitted revision ID and checksum.

### `POST /daily-report-revisions/{revision_id}/reject`

Acts only on current submitted revision. Required reason.

Server preserves submitted revision, records rejection, creates a new draft revision based on it, and returns the new draft ID.

### `POST /daily-report-revisions/{revision_id}/approve`

Acts only on current submitted revision and checksum. Enforces approval policy and self-approval rule. Creates approved state and export jobs.

### `POST /daily-report-revisions/{revision_id}/amend`

Acts on approved revision. Required amendment reason. Creates a mutable amendment draft.

## 5. Report exports

### `POST /daily-report-revisions/{revision_id}/exports`

Online only. Approved or submitted-preview policy.

Body:

- format: pdf/xlsx
- visibility: client/internal
- template version optional only for draft preview; approved regeneration uses original version

Internal visibility additionally requires `view_internal_content`; client visibility requires
`view_client_report`. Requested visibility can never elevate the caller's database-derived access.

Returns export job.

### `GET /report-exports/{export_id}`

Returns status, payload checksum, renderer/template version, binary checksum, and authorised download link when ready.

## 6. Products and prices

### `GET/POST /projects/{project_id}/products`

Configuration-version scoped.

### `POST /project-products/{product_id}/prices`

Validates non-overlapping effective range and unit basis.

### `GET /project-products/{product_id}/price-at?date=YYYY-MM-DD`

Returns selected price and basis for diagnostics.

## 7. Transfer and inventory transactions

### `POST /daily-report-revisions/{revision_id}/transfer-tickets`

Creates draft ticket; may be cached offline.

### `PATCH /transfer-tickets/{ticket_id}`

Draft only; optimistic concurrency.

### `POST /transfer-tickets/{ticket_id}/post`

Online only, idempotent. Posts ticket and inventory lines atomically.

### `POST /inventory-postings/{posting_id}/reverse`

Online only. Required reason and permission. Creates equal-and-opposite lines.

### `GET /projects/{project_id}/inventory-balances`

Supports report date/cut-off, product, batch, and status filters.

### `POST /daily-report-revisions/{revision_id}/inventory-counts`

Stores physical counts separately from ledger.

## 8. Pits and volume transactions

### `GET/POST /projects/{project_id}/pits`

Configuration-version scoped.

### `POST /daily-report-revisions/{revision_id}/pit-readings`

Draft reading; optimistic concurrency.

### `POST /daily-report-revisions/{revision_id}/volume-movements`

Creates draft movement.

### `POST /volume-movements/{movement_id}/post`

Online only, idempotent, atomic debit/credit lines.

### `POST /volume-postings/{posting_id}/reverse`

Required reason and permission.

### `GET /daily-report-revisions/{revision_id}/volume-reconciliation`

Returns expected/physical closing, variance, tolerance, and status.

## 9. Fluid checks

### `GET /projects/{project_id}/fluid-systems`

Returns property definitions and units.

### `POST /daily-report-revisions/{revision_id}/fluid-checks`

Creates draft check.

### `PATCH /fluid-checks/{check_id}`

Draft only; validates properties and units.

### `POST /fluid-checks/{check_id}/set-primary`

Maintains one primary check per fluid system/day.

## 10. Audit

### `GET /projects/{project_id}/audit-events`

Paginated, permission-scoped, filterable by entity/action/date/actor.

Audit events are read-only.

## 11. Status codes

- 200 read/update
- 201 create
- 202 export/import job accepted
- 204 successful no-content action
- 400 malformed request
- 401 unauthenticated
- 403 unauthorised
- 404 not found within authorised scope
- 409 state/version/idempotency conflict
- 412 `If-Match` failed
- 422 domain validation
- 423 immutable/locked resource

## 12. Acceptance criteria

- **VTX-API-001**: all mutable updates enforce expected version.
- **VTX-API-002**: posting/submission endpoints are idempotent.
- **VTX-API-003**: cross-tenant resource returns no data.
- **VTX-API-004**: submitted revision update returns locked response.
- **VTX-API-005**: rejection returns a new draft and retains submitted revision.
- **VTX-API-006**: approval is bound to submitted revision checksum.
- **VTX-API-007**: transfer posting and ledger commit atomically.
- **VTX-API-008**: volume transfer posts balanced lines atomically.
- **VTX-API-009**: errors use stable machine codes.
- **VTX-API-010**: export record exposes payload/template/renderer identifiers.
