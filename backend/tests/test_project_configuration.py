from datetime import UTC, datetime
from uuid import uuid4

from vantix_core.project_configuration import (
    build_project_snapshot,
    validate_project_configuration,
)


def project_identity() -> dict[str, str]:
    return {
        "project_code": "NS-A",
        "project_name": "North Sea A",
        "well_name": "A-01",
        "time_zone": "Europe/London",
        "currency": "GBP",
        "unit_set": "Metric",
    }


def configuration() -> dict:
    interval_id = str(uuid4())
    return {
        "default_interval_id": interval_id,
        "intervals": [
            {
                "id": interval_id,
                "name": "12 1/4 in hole section",
                "operation_mode": "drilling",
                "top_md": {"value": "1000", "unit": "m", "provenance": "entered"},
                "bottom_md": {"value": "1800", "unit": "m", "provenance": "entered"},
            }
        ],
    }


def test_vtx_prj_002_ready_basic_configuration_can_activate() -> None:
    readiness = validate_project_configuration(project_identity(), configuration())
    assert readiness.can_activate is True
    assert readiness.issues == ()


def test_vtx_prj_002_readiness_identifies_missing_required_groups() -> None:
    readiness = validate_project_configuration({}, {})
    assert readiness.can_activate is False
    assert {issue.code for issue in readiness.issues} >= {
        "PROJECT_FIELD_REQUIRED",
        "INTERVAL_REQUIRED",
        "DEFAULT_INTERVAL_REQUIRED",
    }


def test_vtx_prj_006_source_gap_interval_fields_remain_absent() -> None:
    data = configuration()
    data["intervals"][0].pop("top_md")
    data["intervals"][0].pop("bottom_md")
    readiness = validate_project_configuration(project_identity(), data)
    snapshot, _ = build_project_snapshot(
        organisation_id=uuid4(),
        project_id=uuid4(),
        project=project_identity(),
        data=data,
        version_id=uuid4(),
        version_number=1,
        activated_by=uuid4(),
        activated_at=datetime(2026, 7, 18, tzinfo=UTC),
    )
    assert readiness.can_activate is True
    assert "top_md" not in snapshot["intervals"][0]
    assert "bottom_md" not in snapshot["intervals"][0]
    assert "top_tvd" not in snapshot["intervals"][0]


def test_vtx_prj_002_depth_bounds_require_units_and_valid_order() -> None:
    data = configuration()
    data["intervals"][0]["bottom_md"] = {
        "value": "900",
        "unit": "m",
        "provenance": "entered",
    }
    readiness = validate_project_configuration(project_identity(), data)
    assert readiness.can_activate is False
    assert any(issue.code == "INTERVAL_DEPTH_ORDER_INVALID" for issue in readiness.issues)
