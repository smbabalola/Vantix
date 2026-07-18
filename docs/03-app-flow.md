# Document 03 — Vantix App Flow

## 1. Navigation model

### Global sidebar

- Dashboard
- Projects
- Daily Reports
- Inventory
- Transfers
- Reports
- Administration
- Settings

### Project navigation

- Overview
- Project Setup
- Daily Operations
- Inventory & Logistics
- Reports
- Documents
- Audit

### Persistent project/day context

When working inside a daily report, the header always shows:

- project/well
- report date
- report number
- operation
- interval
- fluid system
- unit system
- report state
- save state

Actions:

- previous day
- next day
- browse calendar
- create day
- preview report
- submit/review action
- more actions

## 2. Route outline

```text
/login
/dashboard
/projects
/projects/new
/projects/:projectId/overview
/projects/:projectId/setup/*
/projects/:projectId/days
/projects/:projectId/days/:reportId/*
/projects/:projectId/inventory
/projects/:projectId/transfers
/projects/:projectId/reports
/projects/:projectId/documents
/projects/:projectId/audit
/admin/*
/settings/*
```

## 3. First-time organisation flow

1. Sign in.
2. Create or join organisation.
3. Configure organisation name, default currency, time zone, and unit set.
4. Invite initial users.
5. Create first project.
6. Start project setup wizard.
7. Activate project after readiness check.

## 4. Project setup flow

### Step 1 — General

- project and well identity
- operator/client
- rig
- location
- time zone
- currency
- default unit set
- reporting start date
- report numbering rule

### Step 2 — Intervals and operation modes

- interval name/number
- top and bottom MD/TVD where available
- hole/casing section
- drilling/completion/workover mode
- planned start/end
- default fluid system

Detailed interval fields are a source gap and require product review before final implementation.

### Step 3 — Fluid and formation context

- operational mode
- fluid systems
- type and base fluid
- fluid property template
- lithology
- temperature gradient/profile
- directional survey

### Step 4 — Operational assets

- pits and pit types
- equipment
- screens
- loss categories
- filtration property set

### Step 5 — Commercial/master data

- personnel and daily charge basis
- products, units, batches, SG, price, status
- equipment rental/standby prices
- screen prices
- waste disposal sites

### Step 6 — Validate and activate

Readiness groups:

- identity
- active interval
- units
- fluid systems
- pits
- products
- personnel
- report template

The project may remain draft with incomplete optional modules, but daily reporting cannot start without required foundations.

## 5. Create daily report flow

1. From project overview or calendar, choose `Create day`.
2. Select date.
3. Choose:
   - copy closing state from previous approved day
   - create from project defaults
   - create blank report
4. Confirm active interval, operation, and fluid system.
5. Vantix creates a draft and navigates to Daily Overview.
6. A readiness panel shows incomplete sections and balance issues.

Copy-forward includes:

- opening inventory
- opening pit volumes
- installed screens
- active equipment
- active personnel selection
- current geometry/BHA snapshot where configured
- active project configuration reference

Copy-forward excludes:

- prior-day activity hours
- problems
- daily remarks/comments
- fluid-check measurements
- losses
- waste transactions
- daily usage
- costs not tied to carried assets

## 6. Daily report section flow

Recommended left-side section navigation:

### Operations

- Overview & General
- Time Distribution
- Personnel
- Problems
- Comments
- Pumps & Drilling Parameters

### Engineering record

- Fluid Checks
- Geometry
- Drillstring / BHA
- Displacements
- Filtration
- Losses

### Materials and fluids

- Material Transfers
- Inventory
- Pits & Volume Accounting
- Screens
- Equipment
- Waste

### Review

- Cost Summary
- Readiness & Reconciliation
- Report Preview
- Approval History

Each section shows `Not started`, `In progress`, `Complete`, or `Needs attention`.

## 7. Core journey: fluid check

1. Open Fluid Checks.
2. select fluid system.
3. choose sample count or add sample.
4. enter sample source and time.
5. enter configured properties.
6. Vantix evaluates daily min/max specifications.
7. out-of-spec values require a comment or acknowledgement.
8. select primary check if multiple checks exist.
9. save and mark section complete.

## 8. Core journey: material receipt/transfer

1. Open Transfers.
2. create transfer ticket.
3. select type: receipt, return, transfer in, transfer out, backload.
4. enter ticket number, counterpart, transport, ordered/received by.
5. add products and quantities.
6. upload ticket evidence.
7. post transaction.
8. inventory updates atomically.
9. corrections create reversal/replacement, not silent edits.

## 9. Core journey: volume accounting

1. Review opening pit state.
2. record pit readings or volume transactions.
3. record fluids built, received, backloaded, transferred, dumped, and lost.
4. record fluids in hole by annulus/drillstring/below bit where applicable.
5. Vantix calculates expected closing state.
6. compare with physical end volumes.
7. investigate variance.
8. create approved adjustment when justified.
9. mark reconciled or leave out-of-balance with caveat.

## 10. Core journey: submit, reject, or approve

1. Open Readiness & Reconciliation.
2. Resolve required missing fields and blocking balance issues.
3. Preview client-visible content.
4. Submit the current draft revision online.
5. Server validates the expected version, creates canonical payload/checksum, and stores an immutable submitted revision.
6. Reviewer acts on that exact revision and checksum.
7. Approval locks the revision and starts PDF/Excel export jobs.
8. Rejection records a reason, preserves the submitted revision, and creates a new mutable draft revision.
9. The rejected revision remains viewable in history.

## 11. Amendment flow

1. Authorised user selects an approved revision and chooses `Create amendment`.
2. Vantix creates a mutable amendment draft and requires a reason.
3. Changes are compared with the approved parent.
4. Submission creates a new immutable amendment revision.
5. Approval makes the amendment current and marks the prior approved revision superseded.
6. Both versions and exports remain accessible.

## 12. Empty states

- No projects: explain project creation and import.
- No daily reports: show `Create first day`.
- No product catalogue: link to Product Setup.
- No pits: explain why volume accounting is unavailable.
- No fluid properties: allow template creation.
- No prior day: create from project defaults.
- No directional data: show optional status rather than zero trajectory.

## 13. Error and conflict states

- network interruption: retain only supported local draft changes and show offline state
- stale edit version: apply the documented merge rules or show conflict comparison; never overwrite automatically
- export failure: report remains approved; export job can be retried
- balance validation failure: block submission when organisation rule says required
- duplicate report date: navigate to existing report or create shift report if enabled
- import row failure: provide downloadable row-level error file
- permission failure: preserve draft and explain required role

## 14. Keyboard interaction

- Tab/Shift+Tab moves across editable cells
- Enter confirms cell and moves down
- Ctrl/Cmd+S triggers save
- Ctrl/Cmd+K opens project/action search
- date and unit fields support direct keyboard entry
- grid paste validates all pasted cells before commit
