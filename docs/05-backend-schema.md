# Document 05 — Vantix Backend Schema

## 1. Schema principles

- UUID primary keys
- organisation ID on tenant-owned tables
- UTC timestamps plus project time zone
- `created_by`, `updated_by`, and row version on mutable aggregates
- soft archive for master data; no hard delete when referenced
- immutable posted transactions
- effective-dated prices
- decimal quantities and money
- explicit units
- JSON used for flexible snapshots and external payloads, not as a substitute for core relational structure

## 2. High-level relationships

```text
Organisation
 ├─ Users / Memberships
 ├─ Projects
 │   ├─ Project configuration versions
 │   ├─ Intervals
 │   ├─ Fluid systems
 │   ├─ Pits
 │   ├─ Project products
 │   ├─ Project personnel
 │   ├─ Project equipment
 │   ├─ Project screens
 │   └─ Daily reports
 │       ├─ Section records
 │       ├─ Inventory transactions
 │       ├─ Volume transactions
 │       ├─ Technical measurements
 │       ├─ Cost lines
 │       ├─ Frozen payload versions
 │       └─ Approvals / exports
 └─ Audit events
```

## 3. Identity and access tables

### organisations

- id
- name
- default_currency
- default_unit_set_id
- default_time_zone
- report_numbering_policy
- status
- created_at

### users

- id
- external_subject
- display_name
- email
- status
- created_at

### organisation_memberships

- organisation_id
- user_id
- role
- status

Roles:

- organisation_admin
- operations_manager
- project_admin
- mud_engineer
- supervisor
- logistics
- cost_reviewer
- client_viewer
- auditor

### project_memberships

- project_id
- user_id
- role_override
- can_submit
- can_approve
- can_view_internal_comments

## 4. Project tables

### projects

- id
- organisation_id
- project_code
- project_name
- well_name
- operator_name
- client_name
- rig_name
- location_text
- latitude / longitude optional
- time_zone
- currency
- unit_set_id
- reporting_start_date
- status: draft / active / suspended / completed / archived
- current_configuration_version_id
- row_version

### project_configuration_versions

- id
- project_id
- version_number
- status: draft / active / superseded
- effective_from
- change_summary
- snapshot_json
- created_by
- activated_by
- activated_at

### project_intervals

- id
- configuration_version_id
- interval_number
- name
- operation_mode
- top_md
- bottom_md
- top_tvd
- bottom_tvd
- hole_size
- casing_od
- casing_id
- default_fluid_system_id
- planned_start
- planned_end
- status

Detailed interval fields remain subject to product confirmation.

## 5. Units and catalogue tables

### unit_sets

- id
- organisation_id nullable for system set
- name
- base_system
- is_default

### unit_definitions

- code
- dimension
- canonical_unit
- conversion_rule_key
- display_precision

### unit_set_mappings

- unit_set_id
- field_key
- unit_code

### product_catalogue

Organisation-level optional master catalogue:

- id
- organisation_id
- item_code
- item_name
- description
- default_unit
- default_packaging
- default_specific_gravity
- product_group
- status

### project_products

- id
- configuration_version_id
- catalogue_product_id nullable
- item_code
- item_name
- alternate_name
- batch_number
- unit_size
- unit_code
- packaging
- specific_gravity
- locator
- cost_code
- inventory_item
- starting_quantity
- status

### product_price_history

- id
- project_product_id
- effective_from
- effective_to
- price
- currency
- price_per_unit_code
- discount_percent
- taxable
- source
- approved_by

No overlapping active price ranges for the same project product and price basis.

## 6. Personnel, equipment, and screen tables

### project_personnel

- id
- configuration_version_id
- user_id nullable
- display_name
- employee_reference optional
- email optional
- description/role
- service_line
- charge_item
- daily_charge
- currency
- active

### equipment_catalogue / project_equipment

Fields include:

- equipment code
- serial number
- service product/type
- description
- alternate name
- rental price
- standby price
- discount
- taxable
- hazardous-area classification
- price category
- general information
- status

### equipment_properties

- project_equipment_id
- property_key
- label
- unit_code
- value_type
- required
- check_frequency

### screen_catalogue / project_screens

- code
- description
- mesh_size
- price
- currency
- discount
- taxable
- opening quantity new
- opening quantity used
- status

## 7. Fluid, formation, directional, pit, and loss setup

### fluid_systems

- id
- configuration_version_id
- operation_mode
- name
- fluid_type
- base_fluid
- alternate_name
- is_default
- status

### fluid_property_definitions

- id
- fluid_system_id or organisation template
- property_key
- label
- unit_code
- data_type
- display_order
- min_value optional
- max_value optional
- required
- report_visibility

### lithology_intervals

- configuration_version_id
- starting_tvd
- ending_tvd optional
- lithology
- sand_percent
- comments

### temperature_profiles

- configuration_version_id
- profile_type
- ambient_temperature
- gradient
- starting_tvd
- temperature
- unit codes

### directional_stations

- configuration_version_id
- md
- inclination
- azimuth
- tvd optional
- northing/easting optional
- source
- source_row

### pit_types

- configuration_version_id
- name
- transactional

### project_pits

- configuration_version_id
- description
- capacity
- volume_unit
- pit_type_id
- transactional
- display_order
- active

### loss_categories

- configuration_version_id
- operation_mode
- category
- loss_type: surface / subsurface
- description
- active

### disposal_sites

- configuration_version_id
- name
- location
- permit/reference optional
- active

## 8. Daily report aggregate and immutable revisions

### daily_reports

Business-day aggregate and lineage root:

- id
- organisation_id
- project_id
- report_date
- shift_code nullable
- report_number
- active_configuration_snapshot_id
- current_draft_revision_id nullable
- current_submitted_revision_id nullable
- current_approved_revision_id nullable
- aggregate_state: draft / under_review / approved / amendment_draft / archived
- row_version
- created_at/by

Unique constraint: project_id + report_date + shift_code.

### daily_report_revisions

- id
- organisation_id
- project_id
- daily_report_id
- revision_number
- revision_kind: original / revision_after_rejection / amendment
- state: draft / ready_for_review / submitted / rejected / approved / superseded / cancelled
- parent_revision_id nullable
- based_on_revision_id nullable
- amendment_reason nullable
- rejection_reason nullable
- configuration_snapshot_id
- unit_set_id
- operation_mode
- active_interval_id
- fluid_system_id
- row_version for draft states only
- submitted_at/by nullable
- rejected_at/by nullable
- approved_at/by nullable
- superseded_at nullable
- created_at/by

Rules:

- only active draft revision is mutable
- submitted/rejected/approved/superseded revisions are immutable
- rejection creates a new draft revision in the same database transaction as the rejection decision
- approval is bound to submitted revision ID and payload checksum

### project_configuration_snapshots

- id
- project_id
- configuration_version_id
- schema_version
- snapshot_json
- canonical_checksum
- created_at/by

Immutable after creation.

### daily_section_status

- daily_report_revision_id
- section_key
- state
- validation_error_count
- warning_count
- completed_by
- completed_at

## 9. Daily general and comments

Editable observations, measurements, comments, and physical readings reference `daily_report_revision_id`; records belonging to immutable revisions cannot be changed. Posted inventory and volume ledgers reference the `daily_report_id` business-day aggregate and record `source_revision_id` for provenance, so rejection or amendment does not duplicate postings.

### daily_general

- daily_report_revision_id
- present_activity
- operator_representative
- contractor_representative
- rig_phone
- warehouse_phone
- alternate_fluid_name
- engineer_phone_1
- engineer_phone_2

### daily_time_entries

- id
- daily_report_revision_id
- activity_code
- hours
- comments
- display_order

Constraint: total hours must meet organisation rule, normally 24 hours for a full-day report.

### daily_personnel_usage

- id
- daily_report_revision_id
- project_personnel_id
- service_line
- description
- applied_daily_charge
- charge_quantity
- report_priority
- charge_status

### daily_problems

- id
- daily_report_revision_id
- problem_type: operational / fluid
- problem_code
- duration_hours
- depth
- depth_unit
- comments
- status

### daily_comments

- id
- daily_report_revision_id
- comment_type
- content
- visibility: internal / client
- display_order
- author
- created_at

## 10. Pumps and drilling data

### pump_definitions

- configuration_version_id
- make_model
- pump_type
- liner_diameter
- stroke_length
- rod_diameter_duplex
- efficiency_percent
- rate_per_stroke
- connected_to_riser

### daily_drilling_parameters

- daily_report_revision_id
- rotary_rpm
- motor_rpm
- rotating_hours
- weight_on_bit
- rate_of_penetration
- pump_flow_rate
- pump_pressure
- riser_pump_flow
- boostline_od
- boostline_id
- bottomhole_circulating_temperature
- suction_temperature
- surface_formation_temperature
- cuttings_size_class
- cuttings_specific_gravity
- cuttings_length
- cuttings_diameter
- surface_pressure_loss_code
- source and units per field

## 11. Fluid checks

### fluid_checks

- id
- daily_report_revision_id
- fluid_system_id
- check_number
- sample_from
- sample_time
- is_primary
- status
- notes

### fluid_check_values

- fluid_check_id
- property_definition_id
- numeric_value
- text_value
- unit_code
- status
- out_of_spec
- specification_comment
- source

### daily_fluid_specifications

Allows report-specific overrides with approval:

- daily_report_revision_id
- property_definition_id
- min_value
- max_value
- unit_code
- comment
- approved_by

## 12. Geometry and BHA

### daily_wellbore_geometry

- daily_report_revision_id
- interval sequence
- type
- casing_od
- casing_id
- top_md
- bottom_md/depth
- tvd
- hole_size
- liner_top
- source

### daily_geometry_summary

- air_gap
- water_depth
- bit_depth
- hole_depth
- tvd
- daily_length_drilled
- daily_volume_drilled
- bit_size
- washout_percent
- washout_hole_size
- inclination
- azimuth
- plug_back_md/tvd
- sidetrack data
- downhole tools snapshot

### drillstring_snapshots

- daily_report_revision_id
- name
- source
- imported_file_id
- total_length
- status

### drillstring_components

- snapshot_id
- sequence
- component_type
- description
- top_md
- bottom_md
- length
- od
- id
- unit codes
- metadata_json

## 13. Inventory and transfer schema

### transfer_tickets

A ticket persists across report revisions because posting changes the project ledger.

- id
- organisation_id
- project_id
- daily_report_id
- created_in_revision_id
- ticket_type
- ticket_number
- ordered_by
- received_by
- ship_via
- counterparty
- status: draft / posted / reversed / cancelled
- attachment_id
- row_version while draft
- posted_at/by
- posting_id nullable

### transfer_ticket_items

- id
- ticket_id
- project_product_id
- batch_number
- unit_code
- ticket_quantity
- actual_quantity
- notes

Ticket quantity is documentary. Actual quantity is posted after unit validation.

### inventory_postings

Append-only posting header:

- id
- organisation_id
- project_id
- daily_report_id
- source_revision_id
- posting_type
- source_entity_type/id
- transaction_group_id nullable
- status: posted / reversed
- posted_at/by
- reversal_of_posting_id nullable
- reason nullable
- idempotency_record_id

### inventory_ledger_lines

- id
- posting_id
- project_product_id
- batch_number nullable
- entered_quantity
- entered_unit_code
- canonical_signed_quantity
- canonical_unit_code
- applied_unit_price nullable
- price_basis_unit_code nullable
- currency nullable
- posted_line_amount nullable
- counterparty_project_id nullable
- metadata_json

Positive canonical quantity increases stock; negative quantity decreases stock. A reversal line copies and negates the original canonical quantity and posted line amount.

### inventory_physical_counts

Revision-owned observation:

- daily_report_revision_id
- project_product_id
- batch_number nullable
- physical_closing_quantity
- unit_code
- observed_at/by
- source
- row_version while draft

### inventory_reconciliation_snapshots

Derived for one revision and frozen in its report payload:

- daily_report_revision_id
- project_product_id
- batch_number nullable
- opening_quantity
- calculated_closing_quantity
- physical_closing_quantity nullable
- variance
- unit_code
- tolerance
- status
- ledger_cutoff
- ledger_basis_checksum

The project ledger is authoritative; the snapshot explains what the revision reported.

## 14. Screens and equipment daily records

### screen_transactions

- daily_report_id
- source_revision_id
- project_screen_id
- equipment_id
- action: install / uninstall_to_reuse / uninstall_to_trash / transfer
- quantity
- installation_date
- condition
- applied_price
- source_ticket
- posted_at/by

### daily_equipment_utilisation

- daily_report_revision_id
- project_equipment_id
- daily_used_quantity
- charge_basis: full / standby / no_charge
- applied_charge
- current_cumulative_charge
- remarks
- property_check_json or normalised child rows

## 15. Volume, losses, displacement, filtration, and waste

### pit_readings

Revision-owned physical observation:

- daily_report_revision_id
- project_pit_id
- reading_type: opening / closing / observation
- volume
- unit_code
- fluid_system_id
- fluid_weight nullable
- comment
- observed_at/by
- row_version while draft

### volume_postings

Append-only posting header:

- id
- organisation_id
- project_id
- daily_report_id
- source_revision_id
- posting_type
- source_entity_type/id
- transaction_group_id nullable
- status: posted / reversed
- posted_at/by
- reversal_of_posting_id nullable
- reason nullable
- idempotency_record_id

### volume_ledger_lines

- id
- posting_id
- account_type: pit / external_source / external_sink / surface_loss / subsurface_loss / hole
- project_pit_id nullable
- fluid_system_id nullable
- entered_volume
- entered_unit_code
- canonical_signed_volume
- canonical_unit_code
- metadata_json

Pit-to-pit transfers create equal negative and positive pit lines in one posting. External sources/sinks explain single-pit additions or removals.

### fluids_in_hole_snapshots

Revision-owned snapshot:

- daily_report_revision_id
- location: annulus / drillstring / below_bit / total
- fluid_system_id
- volume
- unit_code
- calculation_basis
- status
- caveats

### loss_events

A posted event is immutable and linked to the ledger deduction:

- id
- organisation_id
- project_id
- daily_report_id
- source_revision_id
- loss_category_id
- volume_posting_id
- start_time/end_time nullable
- depth nullable
- volume
- rate nullable
- unit_codes
- description
- surface_or_subsurface
- status: posted / reversed

### volume_reconciliation_snapshots

- daily_report_revision_id
- project_pit_id nullable for system total
- opening_physical
- signed_movement_total
- expected_closing
- physical_closing nullable
- variance
- tolerance
- status
- ledger_cutoff
- ledger_basis_checksum

### displacement_cycles

Later-module revision-owned record:

- id
- daily_report_revision_id
- sequence
- from_fluid_system_id
- to_fluid_system_id
- planned_volume
- actual_volume
- start_time/end_time
- status
- notes

Detailed cycle fields require a dedicated design review because only the create-entry screen was supplied.

### filtration_cycles

Later-module revision-owned record:

- id
- daily_report_revision_id
- carry_forward_from_cycle_id
- start_time/end_time
- volume_processed
- status
- notes

### filtration_measurements

- filtration_cycle_id
- property_definition_id
- value
- unit_code
- timestamp

### waste_transactions

Later-module posting/reference record:

- id
- organisation_id
- project_id
- daily_report_id
- source_revision_id
- disposal_site_id
- linked_volume_posting_id nullable
- solid_truck_count
- liquid_truck_count
- solids_volume
- liquids_volume
- total_or_per_volume_cost_basis
- solids_cost
- liquid_cost
- remarks

When `linked_volume_posting_id` is present, waste reporting must not create another volume deduction.

## 16. Reporting, decisions, files, idempotency, and audit

### report_payload_versions

- id
- organisation_id
- project_id
- daily_report_revision_id unique
- payload_json
- payload_schema_version
- canonical_bytes_object_id optional
- payload_checksum
- configuration_snapshot_checksum
- template_key/version
- visibility_policy_version
- renderer_name/version/image_digest
- created_at/by

Immutable.

### report_exports

- id
- payload_version_id
- export_type: pdf / xlsx
- visibility: client / internal
- export_kind: original / regenerated / reissued
- file_object_id
- status
- binary_checksum
- template_version
- renderer_version/image_digest
- generated_at
- error_code/message

Original export objects are never overwritten.

### report_decisions

- id
- daily_report_id
- daily_report_revision_id
- action: submit / reject / approve / create_revision / create_amendment / supersede / cancel
- actor_id
- acted_at
- reason/comment
- expected_payload_checksum nullable
- from_state
- to_state

### idempotency_records

- organisation_id
- operation_type
- idempotency_key
- request_hash
- resource_type/id
- response_status
- response_json
- created_at
- expires_at optional

Unique: organisation_id + operation_type + idempotency_key.

### file_objects

- id
- organisation_id
- project_id
- object_key
- original_name
- mime_type
- size
- checksum
- classification
- immutable
- uploaded_by/at

### audit_events

- id
- organisation_id
- project_id
- actor_id
- entity_type/id
- action
- occurred_at
- source_channel
- correlation_id
- before_json
- after_json
- reason
- metadata_json

Audit events are append-only and protected by RLS/capability rules.

## 17. Important constraints

- tenant-owned tables have RLS enabled
- approved/submitted/rejected/superseded revision records are immutable
- only one active draft revision per daily report
- only one current submitted revision may await decision
- rejection preserves submitted revision and creates a new draft
- posted transaction quantity/price cannot be edited
- reversal references original and is equal-and-opposite in canonical quantity and line amount
- two-sided transfers balance and commit atomically
- project configuration snapshot referenced by a revision cannot be deleted
- report payload checksum must match canonical serialization
- report export references payload/template/renderer versions
- audit and idempotency records are not edited through normal application endpoints
- units must be dimensionally compatible
- physical counts/readings remain separate from calculated balances
- no overlapping active price ranges for the same product/price basis
