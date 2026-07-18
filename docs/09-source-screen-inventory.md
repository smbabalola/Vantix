# Source Screen Inventory

## Purpose

This document records what was observed in the 25 supplied legacy application photographs and how each source informs Vantix. It intentionally excludes personal names, IDs, email addresses, and project-specific commercial values visible in the photographs.

## Source limitations

- photographs contain screen moiré and perspective distortion
- some tabs are visible without their detail screens
- empty-state screens do not reveal all fields in the create/edit dialog
- the source shows one project/day and does not prove every workflow variant
- Vantix requirements marked proposed are not claims about the legacy application

## Image mapping

| No. | Original filename suffix | Observed screen | Vantix module |
|---:|---|---|---|
| 1 | `07.51.52 (1)` | Daily Filtration empty state; create/continue/recalculate | VTX-FIL |
| 2 | `07.51.52 (2)` | Daily Displacements empty state; create displacement | VTX-DSP |
| 3 | `07.51.52 (3)` | Daily Volume Accounting; pits, fluids in hole, balances, losses, transactions | VTX-VOL |
| 4 | `07.51.52 (4)` | Daily Equipment; performance checks, utilisation, charge states | VTX-EQP |
| 5 | `07.51.52 (5)` | Daily Screens; equipment tree, install/uninstall/reuse/trash, screen inventory | VTX-SCR |
| 6 | `07.51.52` | Daily Waste Management; disposal, trucks, volumes, costs, remarks | VTX-WST |
| 7 | `07.51.53 (1)` | Daily Material Transfers; ticket and item detail | VTX-TRF |
| 8 | `07.51.53 (10)` | Project Utility/DrillOps; well info and recap/export options | VTX-INT |
| 9 | `07.51.53 (2)` | Daily Drill String/BHA empty geometry/import workspace | VTX-BHA |
| 10 | `07.51.53 (3)` | Daily Geometry; casing/hole, riser, depth, washout, survey, tools | VTX-GEO |
| 11 | `07.51.53 (4)` | Daily Fluid Checks populated grid and specification areas | VTX-FLD |
| 12 | `07.51.53 (5)` | Daily Fluid Checks empty state | VTX-FLD |
| 13 | `07.51.53 (6)` | Daily Comments; operations/service remarks and extra comments | VTX-COM |
| 14 | `07.51.53 (7)` | Daily Pumps/Drilling Parameters and hole-cleaning inputs | VTX-PMP |
| 15 | `07.51.53 (8)` | Daily General; context, time, personnel, operational/fluid problems | VTX-GEN/VTX-PER |
| 16 | `07.51.53 (9)` | Project Filtration Setup; properties and warehouse report data | VTX-FIL |
| 17 | `07.51.53` | Daily Inventory; product movement columns, final, use, cost | VTX-INV |
| 18 | `07.51.54 (1)` | Project Loss Setup; surface/subsurface categories and descriptions | VTX-LOS |
| 19 | `07.51.54 (2)` | Project Pits Setup; pits, capacities, pit types, non-transactional pits | VTX-PIT |
| 20 | `07.51.54 (3)` | Project Directional; survey and profile, Excel/WITSML actions | VTX-DIR |
| 21 | `07.51.54 (4)` | Project Formation/Fluid Systems; lithology, temperature, fluid systems | VTX-FSY |
| 22 | `07.51.54 (5)` | Project Equipment Setup; identity, prices, classification, properties | VTX-EQP |
| 23 | `07.51.54 (6)` | Project Screens Setup; code, mesh, price, starting quantities | VTX-SCR |
| 24 | `07.51.54 (7)` | Project Product Setup; products, units, prices, SG, groups, stock | VTX-PRO |
| 25 | `07.51.54 (8)` | Project Personnel Setup; role/service/charge master | VTX-PER |

## Cross-screen observations

### Persistent daily context

The daily workspace consistently shows:

- previous/next day navigation
- date
- create/delete day
- operation
- interval
- fluid system
- PDF-style daily reports
- Excel reports
- daily cost categories

Vantix translates this into a sticky project/day context bar and report state actions. Direct deletion of a historical day is replaced with controlled archive/cancel behaviour.

### Cost strip

Observed categories:

- chemicals
- personnel
- screens
- equipment
- total

Vantix preserves these and adds optional waste/other cost categories while keeping the original four first-class.

### Project tabs visible but not fully captured

- General
- Intervals
- Plan Data

These are marked source gaps. Detailed fields must be confirmed before implementation beyond the minimum project identity and interval model.

### Integration entry points observed

- Excel
- WITSML
- OpenWells
- DrillOps
- fluid-check synchronisation
- mud-program generation

Vantix documentation treats them as adapter boundaries and does not assume vendor credentials, payloads, or entitlement.

## Legacy-to-Vantix design translation

| Legacy pattern | Vantix decision |
|---|---|
| long horizontal tab strip | grouped project/day section navigation |
| final balances editable in grids | transaction ledger plus physical reading |
| create/delete last day | create, cancel, archive, lock, amend |
| mixed operational and client comments | explicit visibility classification |
| local database file | PostgreSQL source of truth with local draft cache |
| daily report generated from current mutable state | frozen report payload |
| repeated recalculation buttons | automatic deterministic recalculation with visible timestamp and manual retry |
| price visible in setup/current inventory | effective-dated price applied and frozen |
| many empty screens with create button | guided empty states and setup links |
| values sometimes displayed as zero when not configured | `Unavailable` or `Not applicable` |
