# Authentication, Tenancy, and Permissions Contract

## 1. Authentication

- Use OIDC-compatible authentication.
- The access token identifies the external subject; it does not grant project access by itself.
- The API maps the subject to a Vantix user and active memberships.
- Organisation or project IDs supplied by the client are never trusted as authority.
- Service/integration identities use separate credentials and explicit scopes.

## 2. Tenant model

Tenant-owned records carry `organisation_id`. Project-owned records additionally carry `project_id`.

Defence in depth is mandatory:

1. API dependency resolves the active organisation and membership.
2. Service/repository methods require organisation/project scope.
3. PostgreSQL row-level security filters tenant-owned tables.
4. Object-storage keys and signed downloads are checked against the same scope.
5. Tests attempt cross-tenant reads and writes for every aggregate class.

### PostgreSQL session context

At the start of each transaction, the API sets transaction-local values:

```sql
SET LOCAL app.current_user_id = '<uuid>';
SET LOCAL app.current_org_id = '<uuid>';
SET LOCAL app.current_project_ids = '<comma-separated authorised UUIDs>';
SET LOCAL app.is_system_service = 'false';
```

RLS policies compare row ownership to these values. Database migrations and controlled background workers use a separate role; ordinary application connections cannot bypass RLS.

## 3. Roles

### Organisation roles

- `organisation_admin`: organisation settings, memberships, all projects
- `operations_manager`: create/manage projects, assign project roles
- `auditor`: read records, revisions, exports, and audit; no operational mutation

### Project roles

- `project_admin`: project configuration and membership within delegated scope
- `report_editor`: edit draft operational sections
- `logistics`: draft/post authorised material and volume transactions
- `reviewer`: review submitted revisions and reject
- `approver`: approve revisions within approval policy
- `cost_reviewer`: view/validate pricing and costs
- `client_viewer`: approved client-visible content only

A user may have multiple roles. Permissions are evaluated as explicit capabilities, not role-name checks scattered through code.

## 4. Capability matrix

| Capability | Admin | Editor | Logistics | Reviewer | Approver | Client | Auditor |
|---|---:|---:|---:|---:|---:|---:|---:|
| View draft | Yes | Yes | Relevant | Yes | Yes | No | Yes |
| Edit draft sections | Yes | Yes | Relevant | No | No | No | No |
| Post ledger transaction | Yes | Optional | Yes | No | No | No | No |
| Submit revision | Yes | Yes if granted | No | No | No | No | No |
| Reject submitted revision | Optional | No | No | Yes | Yes | No | No |
| Approve submitted revision | By policy | No | No | Optional | Yes | No | No |
| View internal comments | Yes | Yes | Relevant | Yes | Yes | No | Yes |
| View approved client report | Yes | Yes | Yes | Yes | Yes | Yes | Yes |
| Create amendment | By policy | Optional | No | Reviewer | Approver | No | No |

## 5. Approval authority

- Submit and approve are separate capabilities.
- Default policy prevents a person from approving their own submission.
- Organisation policy may require one or two approval stages.
- Approval capability may be restricted by project, report type, or cost threshold.
- Rejection records a reason.
- Approval and rejection act on a specific immutable revision ID and checksum.
- A decision fails when the revision is no longer the active submitted revision.

## 6. Comment and export visibility

Content visibility:

- `client`
- `internal`
- `restricted`

Client viewers receive server-filtered approved payloads. The frontend is not responsible for hiding restricted data. Generated client exports are produced from a visibility-filtered canonical payload derivative whose parent checksum is recorded.

## 7. Object storage

- Object key begins with organisation/project scope.
- Metadata record stores ownership and classification.
- Download URL is short-lived and generated only after permission check.
- Upload finalisation verifies checksum and expected project scope.
- Approved report artefacts are immutable objects; replacement creates a new export row.

## 8. Acceptance criteria

- **VTX-AUTH-001**: token subject maps to an active Vantix user.
- **VTX-AUTH-002**: inactive membership is denied.
- **VTX-AUTH-003**: client-supplied organisation ID cannot bypass membership.
- **VTX-AUTH-004**: RLS blocks cross-tenant read.
- **VTX-AUTH-005**: RLS blocks cross-tenant write.
- **VTX-AUTH-006**: repository methods require scope.
- **VTX-AUTH-007**: project role restricts draft mutation.
- **VTX-AUTH-008**: submit and approve capabilities are distinct.
- **VTX-AUTH-009**: self-approval is denied by default.
- **VTX-AUTH-010**: client payload excludes internal/restricted content.
- **VTX-AUTH-011**: signed object URL requires permission and expires.
- **VTX-AUTH-012**: approval decision is bound to revision ID and checksum.
