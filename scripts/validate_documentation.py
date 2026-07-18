from pathlib import Path
import re, sys

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = [
    '.qodo/agents/agents.md',
    'docs/00-vantix-master-app-document.md',
    'docs/05-backend-schema.md',
    'docs/07-module-specifications.md',
    'docs/10-qa-and-acceptance.md',
    'docs/12-mvp-baseline.md',
    'docs/13-auth-tenancy-permissions.md',
    'docs/14-reconciliation-contracts.md',
    'docs/15-report-determinism.md',
    'docs/16-offline-and-conflict-contract.md',
    'docs/17-api-contracts.md',
    'docs/18-mvp-requirement-traceability.md',
    'contracts/inventory-ledger-receipts-v1.md',
]

errors = []
for rel in REQUIRED:
    path = ROOT / rel
    if not path.is_file():
        errors.append(f'Missing required document: {rel}')

all_text = ''
excluded_parts = {'.git', '.venv', 'node_modules', 'dist', 'build'}
for path in ROOT.rglob('*.md'):
    if excluded_parts.intersection(path.relative_to(ROOT).parts):
        continue
    text = path.read_text(encoding='utf-8')
    all_text += '\n' + text
    bad_arrow = chr(0x00E2) + chr(0x2020)
    if bad_arrow in text or '\ufffd' in text:
        errors.append(f'Encoding corruption detected: {path.relative_to(ROOT)}')

required_groups = ['VTX-MVP-', 'VTX-AUTH-', 'VTX-REC-', 'VTX-DET-', 'VTX-OFF-', 'VTX-API-', 'VTX-RPT-']
for group in required_groups:
    if group not in all_text:
        errors.append(f'Missing acceptance group: {group}')

if errors:
    print('Documentation validation failed:')
    for error in errors:
        print(f'- {error}')
    sys.exit(1)

print('Documentation validation passed.')
print(f'Required files: {len(REQUIRED)}')
print('Encoding: UTF-8 without known arrow corruption')
print('Cross-cutting acceptance groups: present')
