# Vantix QA and Acceptance Plan

## 1. Test layers

### Domain tests

Pure functions and services:

- units
- inventory balance
- volume balance
- price selection
- cost calculation
- report readiness
- status and caveat rules
- amendment comparison

### Database tests

- constraints
- migrations up/down where supported
- tenant scope
- transaction immutability
- effective-date overlap
- report lock
- reversal relationships

### API tests

- permissions
- optimistic concurrency
- idempotency
- validation error contract
- audit events
- frozen payload
- import errors
- export jobs

### Frontend tests

- section editing
- grid keyboard flow
- validation
- autosave state
- conflict handling
- units in headers
- unavailable states
- report preview

### End-to-end tests

1. create project and activate
2. create day from prior state
3. enter fluid check
4. post receipt and usage
5. reconcile inventory
6. reconcile pits/volume
7. submit and approve
8. download PDF/Excel
9. create amendment
10. verify audit and prior version

### Visual/report regression

- PDF page count and key text
- table headers and units
- no clipped columns
- draft/approved/amended watermark
- Excel sheet names and totals

## 2. Acceptance IDs

### Project and units

- **VTX-PRJ-001**: authorised user can create a project.
- **VTX-PRJ-002**: setup readiness identifies required missing sections.
- **VTX-PRJ-003**: activation creates immutable configuration version.
- **VTX-PRJ-004**: edits after activation create a new version.
- **VTX-PRJ-005**: report retains referenced configuration.
- **VTX-PRJ-006**: source-gap interval fields are not fabricated.
- **VTX-UNIT-001**: active unit set is stored and visible.
- **VTX-UNIT-002**: incompatible unit import is rejected.
- **VTX-UNIT-003**: column headers and exports show units.

### Daily lifecycle

- **VTX-DAY-001**: one report per project/date/shift rule.
- **VTX-DAY-002**: prior-day carry-forward includes opening state only.
- **VTX-DAY-003**: autosave preserves draft.
- **VTX-DAY-004**: stale version cannot overwrite newer edit.
- **VTX-DAY-005**: submission runs server validation.
- **VTX-DAY-006**: submitted revision cannot be edited.
- **VTX-DAY-007**: rejection creates a new draft and retains submitted revision.
- **VTX-DAY-008**: approved revision cannot be edited.
- **VTX-DAY-009**: amendment links to prior approved revision.
- **VTX-DAY-010**: section status reflects errors/warnings.

### Personnel/comments

- **VTX-PER-001**: project personnel can be configured with charge.
- **VTX-PER-002**: applied daily charge remains historical.
- **VTX-COM-001**: internal comment excluded from client export.
- **VTX-COM-002**: comments are not copied as new events.
- **VTX-COM-003**: submitted text is frozen.
- **VTX-COM-004**: unsafe markup is sanitised.

### Products, transfers, inventory, cost

- **VTX-PRO-001**: project product supports code/name/unit.
- **VTX-PRO-002**: effective prices cannot overlap.
- **VTX-PRO-003**: price lookup selects correct date.
- **VTX-PRO-004**: catalogue edit does not alter posted cost.
- **VTX-PRO-005**: starting stock creates opening ledger entry.
- **VTX-TRF-001**: draft ticket does not change stock.
- **VTX-TRF-002**: posted ticket changes stock atomically.
- **VTX-TRF-003**: actual quantity controls posting.
- **VTX-TRF-004**: duplicate ticket warning works.
- **VTX-TRF-005**: posted ticket correction reverses/replaces.
- **VTX-TRF-006**: idempotent retry does not double-post.
- **VTX-TRF-007**: delivery note identity is unique within normalized project/supplier scope.
- **VTX-TRF-008**: entered supplier-document price takes precedence over configured price.
- **VTX-TRF-009**: absent supplier and configured price posts explicit unavailable cost, not zero.
- **VTX-TRF-010**: receipt preview and posting use the same current snapshot and calculations.
- **VTX-TRF-011**: database guards reject forged receipt snapshot, product, conversion, and cost.
- **VTX-TRF-012**: receipt history retains immutable documentary, batch, date, and cost authority.
- **VTX-INV-001**: calculated closing follows ledger formula.
- **VTX-INV-002**: physical closing remains separate.
- **VTX-INV-003**: variance is visible.
- **VTX-INV-004**: negative inventory follows policy.
- **VTX-INV-005**: usage category creates transaction.
- **VTX-INV-006**: excluded-from-print item remains in ledger.
- **VTX-INV-007**: missing weight basis yields unavailable.
- **VTX-INV-008**: inventory export matches payload.
- **VTX-CST-001**: chemical cost uses frozen applied price.
- **VTX-CST-002**: money uses Decimal and currency.
- **VTX-CST-003**: cost category totals reconcile.
- **VTX-CST-004**: daily total equals enabled categories.

### Fluid checks and drilling data

- **VTX-FLD-001**: configurable property list renders.
- **VTX-FLD-002**: multiple checks can be entered.
- **VTX-FLD-003**: one primary check per fluid/day.
- **VTX-FLD-004**: out-of-spec status uses correct unit.
- **VTX-FLD-005**: required comment rule is enforced.
- **VTX-FLD-006**: measured/corrected values remain separate.
- **VTX-FLD-007**: missing property is not zero.
- **VTX-PMP-001**: units display on pump/drilling fields.
- **VTX-PMP-002**: non-applicable riser field is not zero.
- **VTX-PMP-003**: pump configuration is report-snapshotted.
- **VTX-PMP-004**: invalid negative hours/rates are rejected.

### Geometry and BHA

- **VTX-DIR-001**: survey MD is ordered.
- **VTX-DIR-002**: invalid import produces row errors.
- **VTX-DIR-003**: source metadata retained.
- **VTX-DIR-004**: missing TVD remains unavailable.
- **VTX-GEO-001**: geometry intervals validate.
- **VTX-GEO-002**: ID/OD rules validate.
- **VTX-GEO-003**: daily drilled volume exposes basis.
- **VTX-GEO-004**: washout preserves base/adjusted size.
- **VTX-GEO-005**: land/riser applicability works.
- **VTX-BHA-001**: components are ordered.
- **VTX-BHA-002**: OD/ID/length units validate.
- **VTX-BHA-003**: import source retained.
- **VTX-BHA-004**: report uses frozen snapshot.

### Pits, volume, and losses

- **VTX-PIT-001**: transactional flag controls movement eligibility.
- **VTX-PIT-002**: pit capacity warning works.
- **VTX-PIT-003**: archived pit remains in history.
- **VTX-PIT-004**: pit type and fluid system remain separate.
- **VTX-VOL-001**: opening and physical closing are recorded.
- **VTX-VOL-002**: expected closing is transaction-derived.
- **VTX-VOL-003**: variance is visible.
- **VTX-VOL-004**: non-transactional pit cannot be endpoint.
- **VTX-VOL-005**: loss event links to volume movement.
- **VTX-VOL-006**: surface/subsurface losses separate.
- **VTX-VOL-007**: adjustment requires reason/permission.
- **VTX-VOL-008**: fluids in hole include location/basis.
- **VTX-VOL-009**: report reconciliation matches ledger.
- **VTX-LOS-001**: project categories can be configured.
- **VTX-LOS-002**: daily loss event records category/type.
- **VTX-LOS-003**: posted loss correction reverses.
- **VTX-LOS-004**: report totals by surface/subsurface.
- **VTX-LOS-005**: units and depth/time applicability validate.

### Screens/equipment/other modules

- **VTX-SCR-001**: installation changes available quantity.
- **VTX-SCR-002**: uninstall requires destination.
- **VTX-SCR-003**: negative quantity blocked/warned.
- **VTX-SCR-004**: applied price frozen.
- **VTX-SCR-005**: installed screen report is accurate.
- **VTX-EQP-001**: project equipment can be configured.
- **VTX-EQP-002**: full/standby/no-charge is explicit.
- **VTX-EQP-003**: daily charge calculated correctly.
- **VTX-EQP-004**: custom property unit validates.
- **VTX-EQP-005**: historical charge remains frozen.
- **VTX-EQP-006**: equipment remarks appear in report.
- **VTX-DSP-001**: basic cycle can be created.
- **VTX-DSP-002**: planned and actual remain separate.
- **VTX-DSP-003**: unconfirmed advanced fields are absent.
- **VTX-FIL-001**: property set can be configured.
- **VTX-FIL-002**: cycle can continue prior cycle.
- **VTX-FIL-003**: measurements carry units.
- **VTX-FIL-004**: source-gap fields are not invented.
- **VTX-WST-001**: disposal site can be selected.
- **VTX-WST-002**: truck counts and volumes validate.
- **VTX-WST-003**: total/per-volume cost modes are exclusive.
- **VTX-WST-004**: cumulative values calculate.
- **VTX-WST-005**: waste report matches payload.

### Audit/security/offline/import

- **VTX-AUD-001**: every mutation records actor/action.
- **VTX-AUD-002**: audit record cannot be edited by project user.
- **VTX-AUD-003**: report state transition records revision, actor, before/after state, and correlation ID.
- **VTX-AUD-004**: rejection, reversal, adjustment, and amendment record the required reason and source reference.
- **VTX-SEC-001**: cross-tenant access is denied.
- **VTX-SEC-002**: project role permissions enforced.
- **VTX-SEC-003**: signed file URLs expire.
- **VTX-SEC-004**: client user cannot access internal comments.
- **VTX-SEC-005**: secrets are not exposed.
- **VTX-SEC-006**: security headers/session controls pass review.
- **VTX-OFF-001**: interrupted edit restores local draft.
- **VTX-OFF-002**: save state is visible.
- **VTX-OFF-003**: conflict does not auto-overwrite.
- **VTX-OFF-004**: queued mutation is idempotent.
- **VTX-OFF-005**: offline submission is blocked in MVP.
- **VTX-IMP-001**: import template version is checked.
- **VTX-IMP-002**: invalid rows are reported.
- **VTX-IMP-003**: successful rows are counted.
- **VTX-IMP-004**: import is idempotent.
- **VTX-IMP-005**: source file/checksum retained.
- **VTX-IMP-006**: units are not guessed.
- **VTX-IMP-007**: import can be rolled back before commit.

## 3. Required fixtures

- land drilling project
- offshore project with riser/water depth
- completion/brine project
- project with multiple fluid systems
- product with effective price change
- inventory variance
- pit capacity breach
- out-of-spec fluid check
- amended approved report
- client user without internal-comment permission


## 4. Cross-cutting acceptance groups

The following groups are mandatory for the implementation slice and are defined in their authoritative documents:

- VTX-MVP-001 to VTX-MVP-012 — `docs/12-mvp-baseline.md`
- VTX-AUTH-001 to VTX-AUTH-012 — `docs/13-auth-tenancy-permissions.md`
- VTX-REC-001 to VTX-REC-015 — `docs/14-reconciliation-contracts.md`
- VTX-DET-001 to VTX-DET-012 — `docs/15-report-determinism.md`
- VTX-OFF-001 to VTX-OFF-012 — `docs/16-offline-and-conflict-contract.md`
- VTX-API-001 to VTX-API-010 — `docs/17-api-contracts.md`
- VTX-RPT-001 to VTX-RPT-016 — `docs/08-reporting-contract.md`

Every production-MVP requirement must cite at least one acceptance ID. Test names or metadata must include the relevant ID.

## 5. MVP traceability

`docs/18-mvp-requirement-traceability.md` maps every production-MVP requirement to acceptance IDs. CI must verify that each matrix row has a corresponding test reference.
