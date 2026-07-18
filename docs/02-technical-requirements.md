# Document 02 — Vantix Technical Requirements Document

## 1. Architecture

Vantix uses a modular web architecture with a pure domain layer.

```text
React/TypeScript client
        ↓ REST + optional WebSocket events
FastAPI application services
        ↓
vantix_core pure-Python domain services
        ↓
PostgreSQL + object storage
        ↓
Frozen report renderer → PDF / Excel
```

### Core principle

Calculations, reconciliation, unit conversion, status evaluation, and report contract building belong in `vantix_core`. The frontend renders and validates interaction, but it does not own business totals.

## 2. Proposed stack

### Frontend

- React
- TypeScript
- Vite
- TanStack Query
- React Hook Form
- Zod
- TanStack Table or AG Grid Community for dense editable grids
- Tailwind CSS and a consistent component layer
- PWA service worker
- IndexedDB for local draft cache
- Vitest and Testing Library
- Playwright for critical end-to-end flows

### Backend

- Python
- FastAPI
- Pydantic
- SQLAlchemy 2
- Alembic
- PostgreSQL
- psycopg
- structured JSON logging
- pytest
- optional task queue for heavy exports/imports after MVP

### Domain package

`vantix_core/` must have no FastAPI, SQLAlchemy, object-storage, or browser dependencies.

Suggested modules:

```text
vantix_core/
  units.py
  availability.py
  money.py
  inventory/
  volume/
  fluids/
  geometry/
  losses/
  equipment/
  reporting/
  validation/
```

### Reporting

- Jinja2 HTML templates
- WeasyPrint PDF generation
- openpyxl Excel generation
- frozen payload input
- report template version embedded in export metadata

### Storage

- PostgreSQL for transactional records
- S3-compatible object storage for attachments, source imports, PDFs, and Excel files
- SHA-256 checksum stored for generated and uploaded files

### Authentication

- OIDC/JWT authentication
- token subject mapped to Vantix membership
- explicit organisation/project capabilities
- separate submit/review/approve capabilities
- self-approval denied by default
- PostgreSQL RLS plus scoped repositories
- full contract in `docs/13-auth-tenancy-permissions.md`

### Deployment

- Docker images
- Docker Compose for development
- reverse proxy with TLS
- managed PostgreSQL preferred for production
- separate dev, staging, and production environments
- database backup, object-storage retention, and restore test

## 3. Frontend folder structure

```text
frontend/src/
  app/
    router/
    providers/
    layouts/
  components/
    data-grid/
    forms/
    status/
    reporting/
  features/
    auth/
    organisations/
    projects/
    project-setup/
    daily-reports/
    personnel/
    products/
    inventory/
    transfers/
    fluids/
    geometry/
    pits/
    volume-accounting/
    equipment/
    screens/
    losses/
    waste/
    reporting/
    audit/
  lib/
    api/
    units/
    validation/
    offline/
  screens/
  tests/
```

## 4. Backend folder structure

```text
backend/
  app/
    api/
      routers/
      dependencies/
    db/
      models/
      migrations/
      repositories/
    schemas/
    services/
    reporting/
    integrations/
    storage/
    security/
    main.py
  vantix_core/
  tests/
```

## 5. API principles

- resource-oriented endpoints
- organisation and project scope checked on every request
- server-generated IDs
- ISO 8601 timestamps
- decimal strings for money and precision-sensitive quantities
- explicit unit metadata
- optimistic concurrency using `version` or ETag
- idempotency keys for imports, report submission, and transfer creation
- pagination for catalogue, audit, and report lists
- filter and sort contracts documented
- errors use stable machine codes plus user-readable messages

Example error:

```json
{
  "code": "VOLUME_OUT_OF_BALANCE",
  "message": "Final fluid volume differs from the transaction balance.",
  "details": {
    "variance": {"value": "12.50", "unit": "bbl"},
    "section": "volume_accounting"
  }
}
```

## 6. Canonical value contract

```json
{
  "value": "10.20",
  "unit": "ppg",
  "status": "ready",
  "source": "fluid_check",
  "basis": "check_2",
  "caveats": []
}
```

For non-applicable values:

```json
{
  "value": null,
  "unit": "psi",
  "status": "not_applicable",
  "source": null,
  "basis": null,
  "caveats": ["No riser is configured for this project."]
}
```

## 7. Data and calculation rules

Authoritative equations, signs, atomicity, reversals, adjustments, pricing, and tolerances are defined in `docs/14-reconciliation-contracts.md`.

### Precision

- Python `Decimal` in `vantix_core`
- decimal strings in APIs/canonical payloads
- currency line amounts rounded `ROUND_HALF_UP` at posting
- display rounding separated from authoritative value
- no frontend-owned business totals

### Transaction boundaries

- posting header, lines, price application, source state, and audit commit atomically
- two-sided transfers commit both sides or neither
- submitted report payload/state/audit commit atomically
- idempotency record is part of the same transaction

## 8. Offline and resilience

The exact MVP boundary, sync envelope, and conflict rules are defined in `docs/16-offline-and-conflict-contract.md`.

MVP permits cached editing of mutable draft data only. Posting, project configuration, submission, review, approval, official export, import, and attachment finalisation require online server validation. No last-write-wins.

## 9. Security and compliance

- tenant isolation in API dependencies, repositories, and PostgreSQL RLS
- cross-tenant tests for reads and writes
- least-privilege project roles
- no secrets in frontend bundle
- encrypted transport
- encrypted managed storage where available
- signed download URLs
- virus/malware scan for uploads where required
- audit trail not editable by ordinary users
- report retention policy configurable
- PII minimisation
- export access logged
- security headers and CSRF/session protections appropriate to auth design

## 10. Observability

- structured logs with correlation ID
- audit events separate from technical logs
- metrics for API latency, errors, export queue, save failures, and report generation
- health and readiness endpoints
- alerting for failed backups and repeated export failure
- import job records with row counts and error files

## 11. Environment variables

```text
APP_ENV
APP_BASE_URL
API_BASE_URL
DATABASE_URL
JWT_ISSUER
JWT_AUDIENCE
JWT_JWKS_URL
OBJECT_STORAGE_ENDPOINT
OBJECT_STORAGE_BUCKET
OBJECT_STORAGE_ACCESS_KEY
OBJECT_STORAGE_SECRET_KEY
OBJECT_STORAGE_REGION
REPORT_SIGNING_SECRET
CORS_ALLOWED_ORIGINS
SENTRY_DSN
EMAIL_PROVIDER_API_KEY
```

Values must not be committed.

## 12. External integration boundary

Create adapters behind interfaces for:

- WITSML directional survey import
- DrillOps report exchange
- OpenWells export
- ERP/product catalogue import
- email/distribution
- laboratory instrument import

No external vendor contract should leak into core tables without a mapping layer.

## 13. Non-functional requirements

- common pages usable at 1366×768
- keyboard-first data entry
- autosave response normally below one second on a healthy connection
- PDF generation target below 30 seconds
- page lists paginated
- report data reproducible from snapshot
- accessibility target WCAG 2.1 AA for core flows
- time zone stored with project and report; timestamps stored in UTC
- support field and metric units
- compatible with current evergreen desktop browsers

## 14. Canonical reporting

Canonical serialization, decimal representation, checksums, template/renderer versioning, and regeneration are defined in `docs/15-report-determinism.md`.

## 15. API authority

Foundation and production-MVP endpoints are defined in `docs/17-api-contracts.md`.
