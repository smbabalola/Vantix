# Vantix MVP Baseline

## 1. Authority

This document is the authoritative MVP boundary. A module marked `Later` in this document is not required for the first production MVP even when it appears in the source screenshots or broader product roadmap.

## 2. Release stages

### Foundation slice — implementation gate

The foundation slice proves the platform invariants before operational breadth is added.

Included:

- organisation, user, organisation membership, and project membership
- project creation
- one active project configuration version and immutable configuration snapshot
- unit set selection
- daily report aggregate and mutable draft revision
- section readiness framework
- optimistic concurrency
- submission to immutable revision
- rejection that preserves submitted revision and creates a new draft revision
- approval and lock
- audit history
- canonical report payload
- PDF and Excel rendering from the frozen payload
- deterministic checksum and export metadata

Acceptance groups:

- VTX-MVP-001 to VTX-MVP-012
- VTX-AUTH-001 to VTX-AUTH-012
- VTX-RPT-001 to VTX-RPT-016
- VTX-AUD-001 to VTX-AUD-004

### Production MVP — operational core

Adds only the minimum operational workflow needed for a useful drilling-fluids daily report:

- project identity and basic interval context
- daily general data, time distribution, problems, and comments
- product catalogue and effective-dated prices
- material receipts, returns, transfers, and product usage
- inventory ledger, physical count, variance, and chemical cost
- pit setup and pit readings
- volume movements and surface/subsurface losses
- volume reconciliation
- fluid systems and configurable fluid checks
- readiness and reconciliation review
- approved PDF and Excel reports
- PWA local caching for mutable draft data only

### Later releases

Not required for production MVP:

- personnel commercial charging beyond basic report contacts
- shaker screen transactions and cost
- equipment utilisation and cost
- detailed formation and temperature profiles
- directional survey integrations
- detailed wellbore geometry
- drillstring/BHA
- displacements
- filtration cycles
- waste management
- WITSML, OpenWells, DrillOps, ERP, warehouse, and laboratory integrations
- complete offline transaction queue and offline attachments
- advanced analytics and cross-project trends

These modules retain specifications for future implementation but cannot expand MVP without an approved scope change.

## 3. Module classification

| Module | MVP classification | Notes |
|---|---|---|
| Platform authentication/tenancy | Foundation | Required before data entry |
| Audit | Foundation | Required for every mutation |
| Units | Foundation | Required across all values |
| VTX-PRJ | Foundation/MVP | Basic project and interval only |
| VTX-GEN | Production MVP | General, time, problems |
| VTX-COM | Production MVP | Internal/client visibility |
| VTX-PRO | Production MVP | Products and effective prices |
| VTX-TRF | Production MVP | Posted material movements |
| VTX-INV | Production MVP | Ledger and reconciliation |
| VTX-PIT | Production MVP | Pit setup/readings |
| VTX-LOS | Production MVP | Surface/subsurface loss events |
| VTX-VOL | Production MVP | Volume ledger and reconciliation |
| VTX-FSY | Production MVP | Fluid system and property definitions only |
| VTX-FLD | Production MVP | Multiple checks and specifications |
| VTX-RPT | Foundation/MVP | Frozen payload, approval, PDF/Excel |
| VTX-PER | Later | Basic names may appear in general section |
| VTX-SCR | Later | Source-observed but not MVP |
| VTX-EQP | Later | Source-observed but not MVP |
| VTX-DIR | Later | Manual/import support later |
| VTX-GEO | Later | Detailed geometry later |
| VTX-BHA | Later | Detailed BHA later |
| VTX-PMP | Later | Can be promoted after core MVP |
| VTX-DSP | Later | Source gap |
| VTX-FIL | Later | Source gap |
| VTX-WST | Later | Source-observed but not MVP |
| VTX-INT | Later | Adapter boundary only |
| VTX-PLN | Deferred | Source gap |

## 4. Foundation acceptance criteria

- **VTX-MVP-001**: all mandatory documentation paths exist.
- **VTX-MVP-002**: documentation validation script passes.
- **VTX-MVP-003**: organisation and project tenant isolation is tested.
- **VTX-MVP-004**: active configuration snapshot is immutable.
- **VTX-MVP-005**: draft revision supports optimistic concurrency.
- **VTX-MVP-006**: submission creates an immutable revision.
- **VTX-MVP-007**: rejection preserves the submitted revision.
- **VTX-MVP-008**: rejection creates a new editable draft revision.
- **VTX-MVP-009**: approval locks the approved revision.
- **VTX-MVP-010**: every state transition is audited.
- **VTX-MVP-011**: PDF and Excel use the same canonical payload.
- **VTX-MVP-012**: payload checksum is reproducible.

## 5. Scope-change rule

A new module enters MVP only through a documented decision that states:

- business reason
- dependencies
- acceptance IDs
- schema/API effect
- delivery impact
- modules removed or schedule changed to preserve capacity
