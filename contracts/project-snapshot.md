# Project Configuration Snapshot

A daily report snapshot must contain the configuration needed to understand and reproduce the report.

## Required groups

```text
Project identity
Organisation/client/operator
Rig and location
Time zone, currency, and unit set
Active interval and operation mode
Fluid system and property definitions
Applicable daily specifications
Pits and capacities/types
Products and effective prices
Personnel charge records
Equipment and charge records
Screens and prices
Loss categories
Formation/temperature context
Directional source/version
Report template version
Configuration version and activation metadata
```

## Snapshot rules

- created at daily-report creation and refreshed only through an explicit action while draft
- frozen at submission
- does not include secrets or unnecessary personal identifiers
- stores display labels as well as IDs
- includes effective price and unit context
- indicates `observed`, `imported`, `entered`, or `calculated` provenance where relevant
- compatible with report payload schema versioning
