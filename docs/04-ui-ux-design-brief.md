# Document 04 — Vantix UI/UX Design Brief

## 1. Aesthetic

Professional, calm, data-dense, and modern. Vantix should feel like an engineering operations workspace rather than a generic admin template.

References in spirit:

- Linear for clear hierarchy and status
- Notion for structured information
- modern industrial operations dashboards for dense tables
- WellOptix for explicit units, status, caveats, and engineering traceability

Do not imitate the legacy desktop application's crowded tab strip or grey form styling.

## 2. Design principles

1. Context never disappears.
2. Data entry is fast and keyboard-friendly.
3. Units are visible before values are entered.
4. Calculated and entered values are distinguishable.
5. Missing and unavailable states are explicit.
6. Reconciliation problems are visible without being alarmist.
7. Draft, submitted, approved, and amended states look different in text and iconography.
8. Dense tables remain readable through grouping, sticky columns, and progressive disclosure.
9. User work is never lost silently.
10. Client-visible report preview is available before submission.

## 3. Colour and typography

Use design tokens rather than hard-coded component colours.

Suggested direction:

- neutral light workspace as default
- optional dark mode
- restrained blue/teal primary action
- amber for needs attention
- red for blocking error
- green for reconciled/approved
- grey for unavailable/not applicable

Typography:

- Inter or equivalent sans-serif for UI
- tabular numerals for engineering, quantity, and cost columns
- 14–16 px body text
- compact 13–14 px grid text on desktop
- clear heading hierarchy, not oversized marketing typography

## 4. Application shell

### Global sidebar

Collapsible, never covered by modal report content.

### Top bar

- breadcrumb
- organisation/project selector
- search
- notifications
- user menu

### Project context bar

Sticky below top bar:

- project
- report date
- operation
- interval
- fluid system
- units
- state
- save indicator
- primary actions

### Section navigation

Use a left section rail or grouped tabs with completion badges. On smaller screens it becomes a drawer.

## 5. Key screen patterns

### Project list

- table/card hybrid
- project status
- latest report date
- report completeness
- inventory or reconciliation warning count
- assigned team
- quick open

### Project setup

- step-based navigation
- section readiness summary
- version and last-changed metadata
- tables for repeatable records
- import buttons adjacent to manual entry
- activation checklist

### Daily workspace

Three-column concept when space allows:

1. section navigation
2. main data-entry content
3. contextual summary/readiness drawer

The main content must stay usable at 1366×768 without horizontal page scrolling; individual data grids may scroll within their region.

### Data grids

- sticky identifier columns
- units in headers
- row add action at end of table
- inline validation
- bulk paste
- visible calculated columns
- column chooser for advanced fields
- totals row
- no destructive action without confirmation
- correction/reversal language for posted transactions

### Status and provenance

Each derived value may show:

- status badge
- source link
- basis tooltip/drawer
- caveat icon with accessible text
- last recalculation timestamp where relevant

## 6. Section-specific UI

### Daily overview

- report identity
- active operation/interval/fluid
- time distribution
- personnel
- problems
- readiness summary
- daily cost strip

### Fluid checks

- sample columns or sample cards depending width
- property rows
- fixed unit column
- min/max specification alongside measured value
- out-of-spec indicator and required comment
- primary check selection
- property configuration in a drawer

### Pumps and drilling parameters

Group into:

- pump configuration
- drilling parameters
- temperatures
- flow/pressure
- hole-cleaning inputs
- optional surface/riser/boostline fields

Fields not applicable to the project are hidden or marked not applicable; they are not shown as zeros.

### Inventory

- product, item code, batch, UOM, applied price
- opening, receipts, returns, transfers, usage groups, adjustments, calculated closing
- daily cost
- reconciliation status
- expandable transaction detail

### Volume accounting

- pit state table
- movement ledger
- fluids-in-hole summary
- expected versus physical closing
- variance explanation
- separate surface and subsurface loss summaries

### Reports

- page preview
- section visibility controls
- internal/client comment classification
- validation warnings
- version and approval history
- export buttons and job status

## 7. Responsive behaviour

### Desktop

Full editing experience.

### Tablet landscape

Editing supported with collapsible navigation and horizontal grid scroll.

### Mobile

MVP supports:

- project/report overview
- read-only report
- comments
- attachment capture
- approval action where permitted

Complex grids remain desktop/tablet-first.

## 8. Accessibility

- WCAG 2.1 AA target
- clear focus states
- all icons have labels or accessible names
- no colour-only state
- validation tied to fields
- keyboard grid navigation
- sufficient contrast
- text zoom does not hide primary actions
- PDFs use semantic headings and tagged structure where renderer permits

## 9. Loading, saving, and failure feedback

Visible save states:

- Saved
- Saving
- Offline draft
- Sync pending
- Conflict
- Save failed

Use skeletons for initial loading. Use inline retry for section failures. Toasts may supplement but never replace persistent error information.

## 10. Report visual style

- clear project/report header
- restrained branding
- repeating page header/footer
- page number and report version
- units in tables
- no clipped wide tables
- section-level caveats
- approval block
- draft/submitted/amended watermark as applicable
