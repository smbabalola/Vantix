# Vantix Module Specifications

> MVP classification is authoritative only in `docs/12-mvp-baseline.md`. A detailed module specification does not make that module part of MVP. Cross-cutting authentication, reconciliation, determinism, offline, and API rules override module-local wording where they conflict.

## Specification pattern

Each module defines:

- purpose
- evidence
- inputs
- outputs
- validation
- unavailable/source-gap behaviour
- report contribution
- acceptance IDs

## Module VTX-PRJ — Project identity and intervals

### Purpose

Create the stable identity and operational context for daily reporting.

### Evidence

- Project Information workspace is observed.
- General and Intervals tabs are visible.
- Detailed interval screen was not supplied.

### Inputs

- project/well/operator/rig/location
- time zone, currency, units
- report numbering
- intervals and operation modes
- planned dates
- default fluid system

### Rules

- project setup is versioned
- activated configuration cannot be edited in place
- a new version is created for changes
- report references the version active when the day was created or explicitly refreshed
- interval detail fields beyond the observed context require product confirmation
- foundation activation requires project identity, time zone, currency, unit set, one basic interval,
  a default interval, and an operation mode
- a basic interval contains only ID, name, operation mode, and optional measured-depth bounds
- optional depth bounds use non-negative canonical decimal strings, controlled `m`/`ft` length
  units, and entered provenance; their units must match the authoritative Metric/Field project
  profile and bottom MD is greater than top MD when both are present
- operation mode is controlled as `drilling`, `completion`, or `workover`
- omitted source-gap interval fields remain absent and are never defaulted to zero
- activation atomically freezes the structured configuration, checksum, activation actor/time, and
  current project pointers; the previously active version becomes superseded
- changing active setup begins by copying it into a new mutable draft version
- configuration draft updates use optimistic concurrency and produce audit events
- one project has at most one draft; creation is idempotent and activation cannot regress to an
  older version
- validation returns the reviewed row version and draft checksum; activation requires both
- database constraints reject cross-project configuration and report snapshot bindings

### Report contribution

Project header, operation, interval, units, and configuration version.

### Acceptance IDs

VTX-PRJ-001 to VTX-PRJ-006.

---

## Module VTX-PER — Personnel

### Purpose

Configure project personnel and record daily utilisation/cost.

### Evidence

Observed fields include name, reference IDs, email, description, service line, charge item, and daily charge. Daily general screen shows representative, charge quantity, report priority, and personnel cost.

### Inputs

- project person
- role/description
- service line
- daily charge and currency
- daily used quantity
- charge basis/status
- report order

### Rules

- historical charge is frozen on daily line
- personal identifiers not needed for reporting should be optional
- deactivated people remain on historical reports
- project member identity and billable personnel record may be linked but are not the same entity

### Outputs

Daily personnel table, total personnel cost.

### Acceptance IDs

VTX-PER-001, VTX-PER-002.

---

## Module VTX-PRO — Products and pricing

### Purpose

Maintain project product master data used by transfers, usage, inventory, and cost.

### Evidence

Observed: item code/name, alternate name, batch, unit size, unit, packaging, price, discount, SG, product group, locator, starting quantity, status, cost code, effective date ranges, price history, approved/customer-owned product paths.

### Rules

- price ranges cannot overlap
- effective ranges are inclusive at `effective_from` and exclusive at `effective_to`; an absent end is open-ended
- batch may be product-specific or transaction-specific
- units must be dimensionally compatible
- specific gravity is not mandatory for every product
- package content uses a positive canonical decimal plus a controlled mass, volume, or count unit
- inventory applicability is explicit; applicable products require a controlled inventory unit
- price uses project currency and an explicit `package` or dimensionally compatible basis unit
- at least one active product and one effective price per active product are required for activation
- products and prices are owned by the mutable configuration version and frozen into its snapshot
- an immutable project-scoped product definition provides ledger lineage; configuration product
  versions preserve that identity across revised-draft copying while retaining distinct version IDs
- snapshots include stable definition and applicable product-version identities
- product and price mutations increment the parent configuration row version and use optimistic concurrency
- package-counted stock may be priced per package or any unit dimensionally compatible with package
  content; an effective-from date requires explicit user entry
- any unsaved product or price draft invalidates readiness and blocks validation/activation
- starting quantity is never an editable product field; the inventory-ledger opening-stock slice
  creates an immutable, idempotent project posting bound to active configuration authority
- catalogue changes do not alter historical transactions

### Outputs

Product catalogue, price history, opening inventory.

### Acceptance IDs

VTX-PRO-001 to VTX-PRO-005.

---

## Module VTX-SCR — Screens

### Purpose

Configure screens and track install, reuse, trash, transfer, quantity, and cost.

### Evidence

Observed project screen catalogue and daily screen/equipment tree, install date, mesh size, action, inventory summary, transfer tickets, add screen, uninstall transactions.

### Rules

- screen state transitions are transactional
- install requires equipment/shaker context
- uninstall requires destination: reuse, trash, or transfer
- quantity cannot become negative without authorised adjustment
- applied price is frozen on chargeable transaction

### Outputs

Installed screen table, screen usage, inventory, daily screen cost.

### Acceptance IDs

VTX-SCR-001 to VTX-SCR-005.

---

## Module VTX-EQP — Equipment

### Purpose

Configure project equipment and record daily utilisation, checks, and charges.

### Evidence

Observed equipment code, serial, service product, alternate name, rental/standby price, discount, taxable flag, hazardous area classification, price category, general information, custom properties, full/standby/no-charge daily states.

### Rules

- daily charge basis is explicit
- check values use configured property definitions and units
- historical charges remain frozen
- equipment can be active but no-charge
- serial numbers need not be globally unique across organisations, but project conflicts are warned

### Outputs

Equipment utilisation, property checks, remarks, cumulative and daily cost.

### Acceptance IDs

VTX-EQP-001 to VTX-EQP-006.

---

## Module VTX-FSY — Formation and fluid systems

### Purpose

Define fluid systems, lithology, and temperature context.

### Evidence

Observed lithology intervals, sand percentage, comments, ambient temperature, gradient, seawater and formation temperature profiles, operation mode, fluid system, type, and base fluid.

### Rules

- fluid system is tied to operation mode
- temperature profiles must be ordered and non-duplicated at the same depth
- imported values retain source
- missing formation data is optional and shown unavailable, not zero

### Outputs

Project context, fluid-check templates, report background.

### Acceptance IDs

VTX-FSY-001 to VTX-FSY-005.

---

## Module VTX-DIR — Directional

### Purpose

Store the directional survey used for TVD/context and reporting.

### Evidence

Observed starting MD, inclination, azimuth, directional profile, Excel and WITSML import/export entry points.

### Rules

- first station and survey order validated
- duplicates and decreasing MD blocked
- source and import row retained
- TVD may be calculated by a future shared trajectory service or imported
- Vantix does not silently fabricate TVD

### Outputs

Survey table and profile.

### Acceptance IDs

VTX-DIR-001 to VTX-DIR-004.

---

## Module VTX-PIT — Pits

### Purpose

Configure transactional and informational pits/tanks and their capacities/types.

### Evidence

Observed pit descriptions, capacities, pit types such as active/reserve/storage/brine, and non-transactional pits.

### Rules

- transactional pits participate in volume movements
- non-transactional pits are informational and may receive manual readings only
- pit type and fluid system are distinct
- capacity breach creates warning/block according to policy
- archived pits remain in history

### Outputs

Pit setup, opening/closing pit state, volume accounting.

### Acceptance IDs

VTX-PIT-001 to VTX-PIT-004.

---

## Module VTX-LOS — Loss categories and daily losses

### Purpose

Configure surface/subsurface loss categories and record daily loss events.

### Evidence

Observed categories include shaker wetting, centrifuge discharge, seepage, ballooning, circulating losses, running casing, total losses, spills, connection losses, programmed/non-programmed discharge, interface, leaks, pills/sweeps/spacers, and dewatering.

### Rules

- category carries surface/subsurface type
- daily event records volume, depth/time where applicable, and description
- loss event creates or links a volume transaction
- deletion after posting uses reversal
- category wording can be organisation-configured

### Outputs

Loss summary, total surface loss, total subsurface loss, caveats.

### Acceptance IDs

VTX-LOS-001 to VTX-LOS-005.

---

## Module VTX-GEN — Daily general

### Purpose

Capture the daily operational header, activity, contacts, time distribution, personnel, and problems.

### Evidence

Observed fields include default interval, present activity, default fluid system, representatives, contact numbers, report number, alternate fluid name, engineer phones, time distribution, operational problems, fluid problems, personnel charges.

### Rules

- date, operation, interval, and fluid system are mandatory
- report number assigned according to project policy
- time total validated
- problem duration cannot be negative
- carried-forward personnel are selections, not automatically chargeable
- section status reflects unresolved required data

### Outputs

Report summary and operations section.

### Acceptance IDs

VTX-DAY-001 to VTX-DAY-008.

---

## Module VTX-COM — Comments

### Purpose

Capture structured operations, service-company, fluid, and additional comments with visibility control.

### Evidence

Observed multiple large comment areas and numbered comment blocks.

### Rules

- comment type and visibility are explicit
- internal comments excluded from client output
- prior-day comments are not copied as new comments
- rich text is limited to safe formatting
- report snapshot preserves exact submitted text

### Outputs

Operations summary, service remarks, client notes, internal notes.

### Acceptance IDs

VTX-COM-001 to VTX-COM-004.

---

## Module VTX-PMP — Pumps and drilling parameters

### Purpose

Capture pump configuration, drilling parameters, temperature, flow/pressure, and hole-cleaning inputs.

### Evidence

Observed pump make/model/type, liner, stroke, rod diameter, efficiency, pump rate per stroke, riser connection, rotary/motor RPM, rotating hours, WOB, ROP, flow, pressure, riser flow, boostline geometry, temperatures, cuttings dimensions/SG, and surface loss code.

### Rules

- fields have explicit units
- not-applicable riser/boostline fields do not display as zero
- pump-rate-derived calculations show basis
- cuttings class and explicit dimensions can coexist, with precedence documented
- values may be point values in MVP; range support can be added where operationally needed

### Outputs

Drilling parameter report table and optional calculated diagnostics.

### Acceptance IDs

VTX-PMP-001 to VTX-PMP-004.

---

## Module VTX-FLD — Fluid checks

### Purpose

Record one or more fluid-property samples per fluid system and compare them to daily specifications.

### Evidence

Observed sample source/time, funnel viscosity, solids, pH, temperature, SG, measured/corrected density, TCT, NTU, iron, in-hole SG/temperature/density, extra properties, daily min/max specifications, primary check, Excel/WITSML/OpenWells/DrillOps actions.

### Rules

- property list is configuration-driven
- each value carries unit and status
- multiple checks are supported
- one check can be primary
- out-of-spec values are flagged and may require comment
- corrected values never overwrite measured values
- export uses the frozen report values

### Outputs

Fluid check tables, out-of-spec summary, primary values.

### Acceptance IDs

VTX-FLD-001 to VTX-FLD-007.

---

## Module VTX-GEO — Geometry

### Purpose

Record the daily wellbore geometry, drilling progress, and volume basis.

### Evidence

Observed wellbore type, casing OD/ID, depth, TVD, liner top, hole size, riser, air gap, water depth, bit depth, hole depth, daily drilled length/volume, bit size, washout, survey, plug back, sidetrack/lateral, and downhole tools.

### Rules

- interval boundaries must be ordered
- IDs must be less than ODs where both apply
- hole size and casing geometry cannot be mixed without type
- daily drilled volume is calculated with a visible basis or entered as measured with source
- washout calculation preserves base and adjusted hole size
- land projects mark riser/water-depth fields not applicable

### Outputs

Geometry table, daily progress, hole-volume basis.

### Acceptance IDs

VTX-GEO-001 to VTX-GEO-005.

---

## Module VTX-BHA — Drillstring/BHA

### Purpose

Capture or import the active drillstring and BHA used for the day.

### Evidence

Observed add/import actions, geometry canvas, drillstring/wellbore views, import/export.

### Rules

- components are ordered by depth/sequence
- length, OD, and ID have units and validation
- imported source retained
- snapshot is report-specific
- Vantix does not require the same level of simulation detail as WellOptix, but compatible identifiers should be planned

### Outputs

BHA/drillstring table and report summary.

### Acceptance IDs

VTX-BHA-001 to VTX-BHA-004.

---

## Module VTX-TRF — Material transfers

### Purpose

Record product receipts, returns, and transfers through traceable tickets.

### Evidence

Observed ticket summary with type, ticket number, ordered/received by, ship via, item code, product, alternate name, batch, UOM, price, ticket quantity, actual quantity, retrieve/copy actions.

### Rules

- posting is atomic with inventory ledger
- actual quantity controls posted stock
- ticket quantity remains as documentary reference
- correction uses reversal/replacement
- duplicate ticket warning by project/counterparty/type
- attachments optional in MVP but recommended
- supplier receipts require project-scoped supplier/delivery-note identity, explicit posting date,
  current reviewed configuration snapshot, stable product lineage, and frozen product/package data
- authenticated posting actor is the V1 received-by user
- supplier-document price takes precedence over configured effective price; missing cost is
  unavailable and never zero
- canonical receipt quantity uses the shared 12-decimal ledger rule; preview and posting use the
  same server calculation
- receipt correction is one exact reversal retaining original snapshot, batch/date, and cost source
- freight allocation, PO workflow, AP matching, and inventory valuation methods remain outside V1

### Outputs

Transfer log and inventory movements.

### Acceptance IDs

VTX-TRF-001 to VTX-TRF-012.

---

## Module VTX-INV — Inventory

### Purpose

Show opening, movement, usage, calculated closing, physical closing, variance, and cost by product.

### Evidence

Observed opening/start, received, returned, used for fluid, used for filtration, used other, on order, final, daily used, daily cost, exclude from print, product metadata, and total chemical weight.

### Rules

- calculated closing is ledger-derived
- physical closing is optional count
- variance is explicit
- negative inventory warns or blocks based on policy
- usage categories create transactions
- `exclude from print` affects report visibility, not ledger
- chemical weight calculation exposes SG/pack basis and unavailable status where basis is missing
- opening stock uses positive append-only lines, explicit units/dates, frozen product/price context,
  and exact-opposite reversal postings; unavailable price remains null rather than becoming zero

### Outputs

Inventory table, usage, variance, chemical cost, total weight.

### Acceptance IDs

VTX-INV-001 to VTX-INV-008.

---

## Module VTX-VOL — Volume accounting

### Purpose

Reconcile pit volumes, fluid movements, fluids in hole, and losses.

### Evidence

Observed pit capacity/opening/calculated end/fluid weight/type/end volume; fluids in hole by annulus/drillstring/below bit; active/reserve/other pit balances; fluid built, received, backload, transfer in/out, loss/dumped; non-transactional pits; loss details and transaction management.

### Rules

- physical and calculated closing remain separate
- all movement has a transaction type and source
- surface and subsurface losses are separate
- fluids in hole have location and basis
- non-transactional pits cannot be movement endpoints
- adjustments require reason
- reconciliation state appears in report

### Outputs

Pit table, movement ledger, fluid balance, variance, loss summary.

### Acceptance IDs

VTX-VOL-001 to VTX-VOL-009.

---

## Module VTX-DSP — Displacements

### Purpose

Record fluid displacement cycles and their planned/actual volumes.

### Evidence

A daily `Create New Displacement` entry point is observed; detailed cycle form is not supplied.

### MVP design

- from fluid
- to fluid
- start/end
- planned/actual volume
- source/destination context
- status
- comments

### Source-gap rule

Do not invent advanced fields until a displacement source screen or stakeholder workflow is provided.

### Acceptance IDs

VTX-DSP-001 to VTX-DSP-003.

---

## Module VTX-FIL — Filtration

### Purpose

Configure filtration properties and record daily filtration cycles.

### Evidence

Observed project properties: description, NTU, oil content, pressure, particle-size distribution, solids, TSS, warehouse details. Daily screen shows create new cycle, continue prior cycle, and recalculate.

### MVP design

- cycle start/end
- carry forward prior cycle
- volume processed
- configured measurement values
- notes
- status

### Source-gap rule

Detailed equipment/process fields require further source evidence.

### Acceptance IDs

VTX-FIL-001 to VTX-FIL-004.

---

## Module VTX-WST — Waste management

### Purpose

Record waste transport and disposal volumes, truck counts, costs, and remarks.

### Evidence

Observed disposal site, solid/liquid haul truck counts, solids/liquid volumes, total or cost-per-volume entry, daily/interval/cumulative values, and remarks.

### Rules

- disposal site is configured
- costs support total or per-volume basis, not both simultaneously
- cumulative values are calculated
- unit and currency explicit
- waste record can link to volume/loss transactions without duplicating them

### Outputs

Waste summary, cost, cumulative metrics.

### Acceptance IDs

VTX-WST-001 to VTX-WST-005.

---

## Module VTX-RPT — Reporting

See `08-reporting-contract.md`.

### Acceptance IDs

VTX-RPT-001 to VTX-RPT-012.

---

## Module VTX-INT — Utility and integrations

### Evidence

Observed actions/reference to Excel, DrillOps, WITSML, OpenWells, fluid-check sync, and mud-program generation.

### Rule

Treat each as an adapter. MVP provides file import/export foundations; vendor connections are separate approved integrations.

### Acceptance IDs

VTX-INT-001 onward.
