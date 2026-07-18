from io import BytesIO

import pytest
from app.renderers import RendererUnavailable, render_excel, render_pdf
from openpyxl import load_workbook
from vantix_core.canonical import payload_checksum


def frozen_payload() -> dict:
    return {
        "schema_version": "1.0",
        "template": {"key": "daily-fluids-report", "version": "1.0"},
        "revision": {"number": 1, "state": "approved"},
        "report": {"number": "VTX-0001", "date": "2026-07-18"},
        "operations": {"general": {"operation_mode": "drilling"}},
    }


def test_vtx_det_005_006_pdf_and_excel_render_same_frozen_payload() -> None:
    payload = frozen_payload()
    checksum = payload_checksum(payload)
    try:
        pdf = render_pdf(payload, checksum)
    except RendererUnavailable:
        pytest.skip("WeasyPrint native libraries are provided by the backend container.")
    excel = render_excel(payload, checksum)
    assert pdf.content.startswith(b"%PDF")
    assert pdf.payload_checksum == excel.payload_checksum == checksum
    assert pdf.binary_checksum != excel.binary_checksum


def test_vtx_rpt_009_excel_embeds_authoritative_payload_checksum() -> None:
    payload = frozen_payload()
    checksum = payload_checksum(payload)
    artefact = render_excel(payload, checksum)
    workbook = load_workbook(BytesIO(artefact.content), read_only=True)
    metadata = workbook["Audit Metadata"]
    assert metadata["B1"].value == checksum
    assert workbook.sheetnames == ["Summary", "Operations", "Audit Metadata"]
