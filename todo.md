# Vantix TODO

## Completed

### 2026-07-19 — Inventory receipts v1 (merged to main, `c83b639`)
- [x] Define supplier receipt ledger contract (`contracts/inventory-ledger-receipts-v1.md`)
- [x] Implement immutable supplier receipt ledger (migration `0009_inventory_receipts`, API, repository)
- [x] Add supplier receipt workspace (frontend `ReceiptWorkspace`)
- [x] Move host-side Postgres port to 5435 (native PostgreSQL 17/18 occupy 5432/5433)
- [x] Verify local dev stack end to end: migrations at head, API on 8010, seeded dev org/user, project creation flow, full test suite green (56 passed, 2 Windows-only skips)

## In progress / known issues

- [ ] Docker build of `api` service fails on this network (pip `CERTIFICATE_VERIFY_FAILED` for pypi.org — TLS-intercepting proxy); needs CA cert in image or pip `trusted-host`
- [ ] WeasyPrint renderer tests skip on Windows host (native libs only in backend container)

## Next

- [ ] (add upcoming tasks here)
