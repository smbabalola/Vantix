# Vantix Migration and Integrations

## 1. Migration principles

- preserve source files unchanged
- import into staging first
- map to Vantix canonical entities
- validate units and identifiers
- provide row-level errors
- require review before commit
- record source, checksum, import batch, and actor
- never silently merge ambiguous products, personnel, pits, or equipment
- maintain a legacy-reference field for traceability

## 2. Recommended migration sequence

1. organisation settings and units
2. project identity
3. intervals
4. personnel
5. products and price history
6. screens
7. equipment
8. fluid systems/properties
9. formation/temperature/directional
10. pits and loss categories
11. opening inventory and pit state
12. historical daily reports
13. attachments and exports

## 3. Import staging model

### import_jobs

- type
- source file
- schema/template version
- status
- submitted by/at
- row totals
- warning/error totals
- committed at
- idempotency key

### import_rows

- job
- row number
- source data JSON
- mapped entity type
- mapped data JSON
- status
- errors/warnings
- committed entity ID

## 4. Spreadsheet templates

Provide versioned templates for:

- project setup
- intervals
- personnel
- products and prices
- equipment
- screens
- pits
- loss categories
- directional stations
- fluid-property definitions
- opening inventory

Templates include:

- field description
- required flag
- expected unit
- example
- allowed values
- template version

## 5. Legacy database migration

The source application appears to use a local project database file. A direct importer should be built only after:

- obtaining a representative database copy
- documenting table relationships
- confirming legal right to parse/export it
- validating totals against legacy PDF/Excel reports

Do not reverse-engineer the schema from screenshots alone.

## 6. Integration architecture

```text
External source
  ↓ adapter-specific client/parser
Canonical staging DTO
  ↓ validation and mapping
Vantix service
  ↓ domain rules
Vantix database
```

### WITSML

Potential uses:

- directional survey
- drilling parameters
- well identity
- fluid/lab data where available

Rules:

- retain object UID/version/source server
- map units explicitly
- do not overwrite manually approved daily data without user action
- imported values show provenance

### DrillOps / OpenWells

Treat as separately licensed/exported integrations. Begin with file-based mapping before live API work.

### Excel

Excel is a first-class import/export channel:

- versioned templates
- row validation
- dry-run preview
- error workbook
- import audit
- idempotent commit

### ERP/warehouse

Future use:

- approved product catalogue
- purchase/receipt references
- cost codes
- inventory movements
- invoice reconciliation

Vantix remains authoritative for wellsite daily usage/reporting unless an approved master-data policy says otherwise.

## 7. Attachment migration

- preserve original filename and timestamp where trustworthy
- compute checksum
- classify document
- link to project/day/transaction
- scan files
- do not infer attachment date from filename alone

## 8. Data reconciliation during migration

For each imported day compare:

- opening and closing inventory
- receipts/returns/transfers/usage
- chemical cost
- opening and closing pit volumes
- losses and dumps
- personnel/equipment/screen cost
- total daily cost
- report date/number/state

Generate a migration reconciliation report. Unexplained differences remain flagged; they are not forced to zero.

## 9. Integration acceptance

- VTX-INT-001: integration uses adapter boundary.
- VTX-INT-002: imported value retains source/provenance.
- VTX-INT-003: unit mapping is explicit.
- VTX-INT-004: repeat import does not duplicate.
- VTX-INT-005: user reviews conflicts before overwrite.
