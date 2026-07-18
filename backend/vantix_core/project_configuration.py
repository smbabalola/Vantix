"""Foundation project-configuration readiness and immutable snapshot construction."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal
from uuid import UUID

from .canonical import payload_checksum
from .products import ProductValidationError, canonicalise_products


@dataclass(frozen=True, slots=True)
class ConfigurationIssue:
    code: str
    field: str
    message: str
    severity: Literal["error", "warning"] = "error"


@dataclass(frozen=True, slots=True)
class ConfigurationReadiness:
    state: Literal["ready", "incomplete"]
    can_activate: bool
    issues: tuple[ConfigurationIssue, ...]


class ConfigurationActivationError(ValueError):
    """A repository-independent project-configuration transition failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


PROJECT_REQUIRED_FIELDS = (
    "project_code",
    "project_name",
    "well_name",
    "time_zone",
    "currency",
    "unit_set",
)

UNIT_SET_LENGTH_UNITS = {"Metric": "m", "Field": "ft"}
LENGTH_UNITS = frozenset(UNIT_SET_LENGTH_UNITS.values())
OPERATION_MODES = frozenset({"drilling", "completion", "workover"})


def _depth_value(
    interval: Mapping[str, Any], field: str, index: int, issues: list[ConfigurationIssue]
) -> tuple[Decimal, str] | None:
    raw = interval.get(field)
    if raw is None:
        return None
    path = f"intervals.{index}.{field}"
    if not isinstance(raw, Mapping):
        issues.append(ConfigurationIssue("INVALID_DEPTH_VALUE", path, "Depth must be an object."))
        return None
    value = raw.get("value")
    unit = raw.get("unit")
    provenance = raw.get("provenance")
    if not isinstance(value, str) or not value.strip():
        issues.append(
            ConfigurationIssue(
                "INVALID_DEPTH_VALUE", f"{path}.value", "Depth requires a decimal string."
            )
        )
        return None
    if not isinstance(unit, str) or not unit.strip():
        issues.append(
            ConfigurationIssue("DEPTH_UNIT_REQUIRED", f"{path}.unit", "Depth unit is required.")
        )
        return None
    if unit not in LENGTH_UNITS:
        issues.append(
            ConfigurationIssue(
                "DEPTH_UNIT_UNRECOGNISED",
                f"{path}.unit",
                "Depth unit must be m or ft.",
            )
        )
        return None
    if provenance != "entered":
        issues.append(
            ConfigurationIssue(
                "DEPTH_PROVENANCE_REQUIRED",
                f"{path}.provenance",
                "Foundation depth provenance must be entered.",
            )
        )
        return None
    try:
        parsed = Decimal(value)
    except InvalidOperation:
        parsed = Decimal("NaN")
    if not parsed.is_finite():
        issues.append(
            ConfigurationIssue(
                "INVALID_DEPTH_VALUE", f"{path}.value", "Depth must be a finite decimal string."
            )
        )
        return None
    if parsed < 0:
        issues.append(
            ConfigurationIssue(
                "NEGATIVE_MEASURED_DEPTH",
                f"{path}.value",
                "Measured depth cannot be negative.",
            )
        )
        return None
    return parsed, unit.strip()


def _canonical_decimal(value: str) -> str:
    parsed = Decimal(value)
    return "0" if parsed == 0 else format(parsed.normalize(), "f")


def validate_project_configuration(
    project: Mapping[str, Any], data: Mapping[str, Any]
) -> ConfigurationReadiness:
    """Validate only confirmed foundation fields; source-gap values remain optional."""

    issues: list[ConfigurationIssue] = []
    for field in PROJECT_REQUIRED_FIELDS:
        value = project.get(field)
        if not isinstance(value, str) or not value.strip():
            issues.append(
                ConfigurationIssue(
                    "PROJECT_FIELD_REQUIRED", f"project.{field}", f"{field} is required."
                )
            )

    expected_depth_unit = UNIT_SET_LENGTH_UNITS.get(str(project.get("unit_set")))
    if expected_depth_unit is None:
        issues.append(
            ConfigurationIssue(
                "UNIT_SET_UNSUPPORTED",
                "project.unit_set",
                "Unit set must be Metric or Field.",
            )
        )

    intervals = data.get("intervals")
    if not isinstance(intervals, list) or not intervals:
        issues.append(
            ConfigurationIssue(
                "INTERVAL_REQUIRED", "intervals", "At least one basic interval is required."
            )
        )
        intervals = []

    interval_ids: set[str] = set()
    for index, raw_interval in enumerate(intervals):
        path = f"intervals.{index}"
        if not isinstance(raw_interval, Mapping):
            issues.append(
                ConfigurationIssue("INVALID_INTERVAL", path, "Interval must be an object.")
            )
            continue
        raw_id = raw_interval.get("id")
        try:
            interval_id = str(UUID(str(raw_id)))
        except (ValueError, TypeError, AttributeError):
            interval_id = ""
            issues.append(
                ConfigurationIssue(
                    "INTERVAL_ID_REQUIRED", f"{path}.id", "Interval UUID is required."
                )
            )
        if interval_id:
            if interval_id in interval_ids:
                issues.append(
                    ConfigurationIssue(
                        "DUPLICATE_INTERVAL_ID",
                        f"{path}.id",
                        "Interval IDs must be unique.",
                    )
                )
            interval_ids.add(interval_id)
        for field in ("name", "operation_mode"):
            value = raw_interval.get(field)
            if not isinstance(value, str) or not value.strip():
                issues.append(
                    ConfigurationIssue(
                        "INTERVAL_FIELD_REQUIRED", f"{path}.{field}", f"{field} is required."
                    )
                )
        operation_mode = raw_interval.get("operation_mode")
        if isinstance(operation_mode, str) and operation_mode not in OPERATION_MODES:
            issues.append(
                ConfigurationIssue(
                    "OPERATION_MODE_UNRECOGNISED",
                    f"{path}.operation_mode",
                    "Operation mode must be drilling, completion, or workover.",
                )
            )

        top = _depth_value(raw_interval, "top_md", index, issues)
        bottom = _depth_value(raw_interval, "bottom_md", index, issues)
        for field, depth in (("top_md", top), ("bottom_md", bottom)):
            if depth and expected_depth_unit and depth[1] != expected_depth_unit:
                issues.append(
                    ConfigurationIssue(
                        "DEPTH_UNIT_PROFILE_MISMATCH",
                        f"{path}.{field}.unit",
                        f"Depth unit must match the project profile ({expected_depth_unit}).",
                    )
                )
        if top and bottom:
            if top[1] != bottom[1]:
                issues.append(
                    ConfigurationIssue(
                        "INTERVAL_DEPTH_UNIT_MISMATCH",
                        path,
                        "Top and bottom MD must use the same unit.",
                    )
                )
            elif bottom[0] <= top[0]:
                issues.append(
                    ConfigurationIssue(
                        "INTERVAL_DEPTH_ORDER_INVALID",
                        path,
                        "Bottom MD must be greater than top MD.",
                    )
                )

    default_interval_id = data.get("default_interval_id")
    try:
        canonical_default = str(UUID(str(default_interval_id)))
    except (ValueError, TypeError, AttributeError):
        canonical_default = ""
    if not canonical_default:
        issues.append(
            ConfigurationIssue(
                "DEFAULT_INTERVAL_REQUIRED",
                "default_interval_id",
                "A default interval is required.",
            )
        )
    elif canonical_default not in interval_ids:
        issues.append(
            ConfigurationIssue(
                "DEFAULT_INTERVAL_NOT_FOUND",
                "default_interval_id",
                "Default interval must reference a configured interval.",
            )
        )

    raw_products = data.get("products")
    if not isinstance(raw_products, list):
        issues.append(
            ConfigurationIssue(
                "ACTIVE_PRODUCT_REQUIRED",
                "products",
                "At least one active product with an effective price is required.",
            )
        )
    else:
        try:
            canonicalise_products(raw_products, str(project.get("currency", "")))
        except ProductValidationError as exc:
            issues.append(ConfigurationIssue(exc.code, exc.field, str(exc)))

    return ConfigurationReadiness(
        state="ready" if not issues else "incomplete",
        can_activate=not issues,
        issues=tuple(issues),
    )


def guard_configuration_activation(
    *,
    project: Mapping[str, Any],
    data: Mapping[str, Any],
    state: str,
    row_version: int,
    expected_version: int,
    expected_checksum: str,
    version_number: int,
    latest_version_number: int,
    active_version_number: int | None,
) -> ConfigurationReadiness:
    """Enforce activation invariants consistently across persistence adapters."""

    if state != "draft":
        raise ConfigurationActivationError(
            "CONFIGURATION_NOT_DRAFT", "Only a draft configuration can be activated."
        )
    if row_version != expected_version or payload_checksum(data) != expected_checksum:
        raise ConfigurationActivationError(
            "CONFIGURATION_VERSION_CONFLICT",
            "Configuration changed after it was reviewed.",
        )
    if version_number != latest_version_number:
        raise ConfigurationActivationError(
            "CONFIGURATION_NOT_LATEST", "Only the latest configuration can be activated."
        )
    if active_version_number is not None and version_number <= active_version_number:
        raise ConfigurationActivationError(
            "CONFIGURATION_VERSION_REGRESSION",
            "An older configuration cannot replace the active configuration.",
        )
    readiness = validate_project_configuration(project, data)
    if not readiness.can_activate:
        raise ConfigurationActivationError(
            "CONFIGURATION_NOT_READY",
            "Resolve configuration readiness issues before activation.",
        )
    return readiness


def build_project_snapshot(
    *,
    organisation_id: UUID,
    project_id: UUID,
    project: Mapping[str, Any],
    data: Mapping[str, Any],
    version_id: UUID,
    version_number: int,
    activated_by: UUID,
    activated_at: datetime,
) -> tuple[dict[str, Any], str]:
    """Build the canonical V1 snapshot only after readiness succeeds."""

    readiness = validate_project_configuration(project, data)
    if not readiness.can_activate:
        raise ValueError("Project configuration is not ready for activation.")
    intervals = deepcopy(data["intervals"])
    products = canonicalise_products(data["products"], str(project["currency"]))
    canonical_unit = UNIT_SET_LENGTH_UNITS[str(project["unit_set"])]
    for interval in intervals:
        for field in ("top_md", "bottom_md"):
            if field in interval:
                interval[field]["value"] = _canonical_decimal(interval[field]["value"])
                interval[field]["unit"] = canonical_unit

    snapshot = {
        "schema_version": "1.2",
        "organisation_id": str(organisation_id),
        "project": {
            "id": str(project_id),
            **{field: project.get(field) for field in PROJECT_REQUIRED_FIELDS},
            **{
                field: project[field]
                for field in (
                    "operator_name",
                    "client_name",
                    "rig_name",
                    "location_text",
                )
                if project.get(field) is not None
            },
        },
        "configuration": {
            "version_id": str(version_id),
            "version_number": version_number,
            "activated_by": str(activated_by),
            "activated_at": activated_at.isoformat().replace("+00:00", "Z"),
        },
        "default_interval_id": str(data["default_interval_id"]),
        "intervals": intervals,
        "products": products,
    }
    return snapshot, payload_checksum(snapshot)
