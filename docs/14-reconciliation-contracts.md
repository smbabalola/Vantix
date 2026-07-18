# Inventory and Volume Reconciliation Contracts

## 1. General ledger rules

- Posted transactions are append-only.
- A transaction header and all ledger lines commit atomically.
- Draft transactions do not affect balances.
- Every line stores entered quantity/unit and canonical quantity/unit.
- A correction creates a reversal group and, when needed, a replacement group.
- An adjustment requires reason, capability, and audit event.
- A transaction has an idempotency key unique within organisation and operation type.
- Balances use posted, non-voided lines through the report cut-off timestamp.
- Physical counts/readings never overwrite ledger-derived balances.

## 2. Inventory sign convention

Positive canonical quantity increases project stock; negative quantity decreases it.

| Transaction type | Sign |
|---|---:|
| Opening balance | + |
| Receipt | + |
| Transfer in | + |
| Customer/warehouse return into project | + |
| Return out of project | - |
| Transfer out | - |
| Used in fluid | - |
| Used in filtration | - |
| Other approved usage | - |
| Disposal/write-off | - |
| Adjustment increase | + |
| Adjustment decrease | - |
| Reversal | Exact opposite of original |

### Inventory equation

For product/batch `p` at cut-off `t`:

```text
calculated_closing(p,t) = sum(posted canonical inventory lines for p with posted_at <= t)
```

For a daily explanation:

```text
daily_calculated_closing = opening_snapshot
                         + receipts
                         + transfers_in
                         + returns_in
                         - returns_out
                         - transfers_out
                         - fluid_usage
                         - filtration_usage
                         - other_usage
                         - disposal
                         +/- approved_adjustments
```

`opening_snapshot` equals the prior approved day's calculated closing, or an approved opening-balance transaction for the first day. It is not a manually editable substitute for the ledger.

```text
inventory_variance = physical_closing_count - calculated_closing
```

### Inventory atomicity

- A posted receipt writes ticket status, ticket lines, ledger lines, applied prices, and audit event in one transaction.
- An inter-project transfer writes outbound and inbound groups with one transfer group ID. Both commit or neither commits.
- Unit conversion is validated before posting.
- Applied price is selected by effective date before posting and copied to the posted line.
- A repeated idempotency key returns the original posting result.

## 3. Volume sign convention

Each transactional pit has its own ledger. Positive quantity increases that pit; negative quantity decreases it.

### Pit movement lines

| Event | Source pit line | Destination pit line |
|---|---:|---:|
| Pit-to-pit transfer | -V | +V |
| Fluid built into pit | none/external | +V |
| Fluid received | none/external | +V |
| Backloaded out of project | -V | none/external |
| Dumped/disposed | -V | none/external |
| Surface loss | -V | loss sink |
| Subsurface loss | -V | loss sink |
| Adjustment | +/-V | explicit adjustment basis |
| Reversal | exact opposite | exact opposite |

### Pit equation

For pit `q`:

```text
expected_closing(q) = opening_physical(q) + sum(posted signed volume lines for q during report period)
```

```text
pit_variance(q) = physical_closing(q) - expected_closing(q)
```

Project surface-system variance:

```text
system_variance = sum(physical_closing transactional pits)
                - sum(expected_closing transactional pits)
```

Fluids in hole are a separate snapshot and are not silently included in surface-pit balances. A movement between surface and hole requires an explicit transaction category and basis.

### Volume atomicity

- Pit-to-pit transfer creates equal canonical debit and credit lines in one transaction.
- A loss event and its volume ledger line commit together.
- A disposal/waste link cannot create a second volume deduction when it references an existing dump transaction.
- Non-transactional pits cannot be ledger endpoints.
- Capacity checks run before commit; policy determines warning versus block.
- Reversing a linked event reverses all associated lines together.

## 4. Reconciliation states

- `reconciled`: absolute variance is within configured tolerance and no blocking issue exists
- `out_of_balance`: variance exceeds tolerance
- `incomplete`: required opening/closing or movement data is missing
- `unavailable`: basis cannot be established
- `not_applicable`: module does not apply

Tolerance is configuration data with value, unit, effective date, and approver. A tolerance never changes the recorded variance; it changes only classification.

## 5. Pricing and rounding

- Quantities use `Decimal` in canonical units.
- Unit price is stored as decimal with currency and price-basis unit.
- Monetary line amount is calculated at posting and rounded `ROUND_HALF_UP` to currency minor units.
- Daily cost totals sum posted line amounts; they do not re-multiply display-rounded quantities.
- Reversal copies and negates the original monetary line amount.

## 6. Concurrency

- Draft tickets can use optimistic concurrency.
- Posting locks the relevant draft transaction row and validates current state.
- Balance reads used during posting occur in the same database transaction.
- Serializable isolation is preferred for inter-project transfers; otherwise use deterministic row locking and retry on serialization/deadlock errors.

## 7. Acceptance criteria

- **VTX-REC-001**: draft transaction does not affect balance.
- **VTX-REC-002**: posting and ledger lines are atomic.
- **VTX-REC-003**: duplicate idempotency key does not double-post.
- **VTX-REC-004**: reversal is equal and opposite.
- **VTX-REC-005**: posted line cannot be edited.
- **VTX-REC-006**: inter-project transfer commits both sides or neither.
- **VTX-REC-007**: inventory closing follows the signed-line equation.
- **VTX-REC-008**: physical count remains separate and variance is correct.
- **VTX-REC-009**: pit-to-pit transfer creates balanced debit/credit lines.
- **VTX-REC-010**: loss event and volume line commit together.
- **VTX-REC-011**: waste link does not double-deduct volume.
- **VTX-REC-012**: non-transactional pit cannot be movement endpoint.
- **VTX-REC-013**: tolerance affects status, not variance.
- **VTX-REC-014**: applied price and line amount remain historical.
- **VTX-REC-015**: reversal negates original monetary amount exactly.
