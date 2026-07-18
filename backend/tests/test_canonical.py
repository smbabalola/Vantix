from datetime import UTC, datetime
from decimal import Decimal

import pytest
from vantix_core.canonical import CanonicalisationError, canonical_bytes, payload_checksum


def test_vtx_det_001_003_004_canonical_serialisation_is_stable() -> None:
    left = {
        "z": Decimal("10.2000"),
        "a": "Cafe\u0301",
        "at": datetime(2026, 7, 18, 12, 1, 2, 900, tzinfo=UTC),
    }
    right = {
        "at": datetime(2026, 7, 18, 12, 1, 2, tzinfo=UTC),
        "a": "Café",
        "z": Decimal("10.2"),
    }
    assert canonical_bytes(left) == canonical_bytes(right)
    assert b'"z":"10.2"' in canonical_bytes(left)


def test_vtx_det_002_checksum_field_is_excluded() -> None:
    payload = {"schema_version": "1", "value": Decimal("1.25")}
    with_checksum = {**payload, "checksum": "not-part-of-identity"}
    assert payload_checksum(payload) == payload_checksum(with_checksum)


def test_vtx_det_003_binary_float_is_rejected() -> None:
    with pytest.raises(CanonicalisationError):
        canonical_bytes({"value": 1.2})
