# Canonical Report Serialization and Determinism

## 1. Authority

The canonical report payload is the authoritative report record. PDF and Excel are renderings of that payload. Renderers must not query mutable operational tables or perform new domain calculations.

## 2. Canonical serialization

Payload serialization uses these rules:

- UTF-8
- Unicode normalisation form NFC
- object keys sorted lexicographically by Unicode code point
- arrays ordered by an explicit semantic `sequence` field or a documented stable sort key
- no locale-formatted numbers or dates
- decimal values encoded as normalised strings, never JSON binary floating-point numbers
- booleans and null use normal JSON values
- timestamps use UTC RFC 3339 with `Z` and whole microseconds removed unless domain precision requires them
- report date remains `YYYY-MM-DD` in project local time
- absent optional field is omitted only when schema says optional; known missing value uses the canonical value contract with `value: null` and status
- no random IDs, current clock values, environment paths, or renderer-specific metadata inside the canonical business payload

Canonical bytes are produced with an RFC 8785-compatible JSON canonicalisation process after applying the Vantix decimal-string rules.

## 3. Precision and rounding

### Quantities and engineering values

- Domain calculations use Python `Decimal`.
- Canonical payload preserves the authoritative decimal to the field registry's canonical scale, up to 12 decimal places unless a specific field requires more.
- Display precision is separate and cannot change the stored value.
- Derived totals are calculated in `vantix_core`, not in templates.

### Money

- Currency minor-unit scale comes from the currency registry.
- Posted monetary line amounts use `ROUND_HALF_UP`.
- Report totals sum posted line amounts.
- Templates format but do not recalculate money.

## 4. Checksums

### Payload checksum

```text
payload_checksum = SHA-256(canonical payload bytes excluding checksum field)
```

Stored with:

- payload schema version
- configuration snapshot checksum
- template key/version
- renderer image/version
- visibility policy/version

### Artefact checksum

Each generated PDF/XLSX has its own SHA-256 binary checksum. Binary checksums may differ across renderer versions even when business content is identical; therefore the payload checksum is the primary reproducibility identity.

## 5. Template and renderer versioning

A report export records:

- payload version and checksum
- template key and immutable template version
- CSS/assets bundle version
- renderer name/version
- container image digest or build identifier
- export visibility class
- generated timestamp
- binary checksum

Template assets are immutable once used by an approved report.

## 6. Regeneration behaviour

- Original approved artefacts are retained and never overwritten.
- `Regenerate` creates a new export record referencing the same payload.
- Exact historical regeneration uses the original template and renderer image.
- If that renderer is unavailable, Vantix may create a `reissued` export only after explicit user action; it records the new renderer and does not claim byte identity.
- A reissued export must retain the same payload checksum and pass semantic comparison tests.
- Regeneration never changes report state or approval.
- A change to business data requires a new revision/amendment, not regeneration.

## 7. PDF determinism

- Pin WeasyPrint, fonts, CSS, and asset versions.
- Set document metadata from payload values, not current environment values except export generated timestamp.
- Do not load remote mutable assets at render time.
- Store fonts in the deployment image; do not distribute font files as report attachments.
- Page-break and table-layout regression fixtures are required.

Exact byte-identical PDF output is not guaranteed across different renderer builds. Vantix guarantees payload identity and semantic rendering under the recorded renderer version.

## 8. Excel determinism

- Pin openpyxl.
- Fix sheet names, order, column order, number formats, and workbook properties.
- Normalise ZIP entry timestamps when the build process supports it.
- Formulas may be included for convenience, but frozen payload values are authoritative and must also be present.
- Excel generation cannot query live tables.

## 9. Revision lifecycle

```text
Draft revision (mutable)
-> Submitted revision (immutable)
-> Approved revision (immutable, active approved report)

Submitted revision
-> Rejected decision (submitted revision retained)
-> New draft revision based on rejected revision

Approved revision
-> Amendment draft
-> Submitted amendment revision
-> Approved amendment revision; prior approved revision becomes superseded
```

A report number identifies the business day. A revision number identifies each immutable submission or amendment lineage.

## 10. Acceptance criteria

- **VTX-DET-001**: repeated canonical serialization yields identical bytes.
- **VTX-DET-002**: payload checksum excludes its checksum field.
- **VTX-DET-003**: decimal values are strings and preserve configured scale.
- **VTX-DET-004**: object key and array ordering is stable.
- **VTX-DET-005**: renderer performs no domain recalculation.
- **VTX-DET-006**: PDF and Excel reference the same payload checksum.
- **VTX-DET-007**: approved artefact is never overwritten.
- **VTX-DET-008**: regeneration creates a new export record.
- **VTX-DET-009**: original template/renderer versions are recorded.
- **VTX-DET-010**: reissued export preserves payload checksum and is labelled.
- **VTX-DET-011**: changing live data does not change stored submitted payload.
- **VTX-DET-012**: amendment produces a new revision and payload checksum.
