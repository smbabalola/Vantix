# Project Configuration Snapshot

A daily report snapshot must contain the configuration needed to understand and reproduce the report.

## Required groups

Groups become required only when their authoritative MVP vertical slice is implemented. Foundation
V1 freezes the following subset:

```text
Project identity and display labels
Organisation ID
Time zone, currency, and unit set
Basic intervals and operation modes
Default interval
Project products, package/inventory units, applicability, optional SG, and effective prices
Configuration version and activation metadata
Snapshot schema version
```

Later operational slices extend the versioned snapshot schema with the applicable groups below;
foundation activation must omit those groups rather than invent placeholders.

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

- product/pricing lineage hardening emits project snapshot schema `1.2`
- created and frozen when a configuration version is activated
- bound immutably to a new daily-report revision at creation; a later activation does not rebind it
- does not include secrets or unnecessary personal identifiers
- stores display labels as well as IDs
- includes products in stable item-code order and prices in effective-from/ID order
- includes immutable `product_definition_id` lineage and configuration-owned product-version `id`
- includes effective price, packaging, inventory applicability, SG availability, and unit context
- indicates `observed`, `imported`, `entered`, or `calculated` provenance where relevant
- compatible with report payload schema versioning
