"""Canonical report serialisation with no infrastructure dependencies."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any


class CanonicalisationError(ValueError):
    """Raised when a value cannot be represented by the report contract."""


def _decimal_string(value: Decimal) -> str:
    if not value.is_finite():
        raise CanonicalisationError("Non-finite decimals are not valid report values.")
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    if rendered in {"", "-0"}:
        return "0"
    return rendered


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        raise CanonicalisationError("Canonical timestamps must be timezone-aware.")
    utc = value.astimezone(UTC).replace(microsecond=0)
    return utc.isoformat().replace("+00:00", "Z")


def normalise(value: Any) -> Any:
    """Convert domain values into deterministic JSON-compatible values."""

    if isinstance(value, Decimal):
        return _decimal_string(value)
    if isinstance(value, datetime):
        return _timestamp(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        raise CanonicalisationError("Binary floating-point values are forbidden.")
    if isinstance(value, Mapping):
        output: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise CanonicalisationError("Canonical object keys must be strings.")
            output[unicodedata.normalize("NFC", key)] = normalise(item)
        return output
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return [normalise(item) for item in value]
    raise CanonicalisationError(f"Unsupported canonical value: {type(value).__name__}")


def canonical_bytes(payload: Mapping[str, Any]) -> bytes:
    """Return stable UTF-8 JSON bytes using the Vantix decimal-string rules."""

    cleaned = dict(payload)
    cleaned.pop("checksum", None)
    return json.dumps(
        normalise(cleaned),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def payload_checksum(payload: Mapping[str, Any]) -> str:
    """Calculate the report identity checksum, excluding its checksum field."""

    return hashlib.sha256(canonical_bytes(payload)).hexdigest()
