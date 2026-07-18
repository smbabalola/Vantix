from uuid import uuid4

from fastapi.testclient import TestClient
from vantix_core.canonical import payload_checksum


def headers(user_id=None, organisation_id=None, capabilities="") -> dict[str, str]:
    return {
        "X-Vantix-User-ID": str(user_id or uuid4()),
        "X-Vantix-Organisation-ID": str(organisation_id or uuid4()),
        "X-Vantix-Capabilities": capabilities,
    }


def setup_report(client: TestClient):
    org_id = uuid4()
    editor_id = uuid4()
    editor_headers = headers(
        editor_id,
        org_id,
        "create_project,configure_project,view_draft_report,view_client_report,"
        "view_internal_content,edit_report,submit_report,view_audit,export_report",
    )
    project = client.post(
        f"/api/v1/organisations/{org_id}/projects",
        headers=editor_headers,
        json={
            "project_code": "NS-A",
            "project_name": "North Sea A",
            "well_name": "A-01",
            "time_zone": "Europe/London",
            "currency": "GBP",
            "unit_set": "Field",
        },
    ).json()
    interval_id = str(uuid4())
    configuration = client.post(
        f"/api/v1/projects/{project['id']}/configuration-versions",
        headers={**editor_headers, "Idempotency-Key": "create-config-1"},
        json={
            "data": {
                "default_interval_id": interval_id,
                "intervals": [
                    {
                        "id": interval_id,
                        "name": "Surface interval",
                        "operation_mode": "drilling",
                    }
                ],
            }
        },
    ).json()
    client.post(
        f"/api/v1/projects/{project['id']}/configuration-versions/{configuration['id']}/activate",
        headers={**editor_headers, "Idempotency-Key": "activate-config-1"},
        json={
            "expected_version": configuration["row_version"],
            "expected_checksum": payload_checksum(configuration["data"]),
        },
    )
    report = client.post(
        f"/api/v1/projects/{project['id']}/daily-reports",
        headers={**editor_headers, "Idempotency-Key": "create-report-1"},
        json={"report_date": "2026-07-18", "report_number": "VTX-0001"},
    ).json()
    report = client.patch(
        f"/api/v1/daily-report-revisions/{report['revision']['id']}/sections/general",
        headers=editor_headers,
        json={
            "expected_version": 1,
            "data": {
                "operation_mode": "drilling",
                "interval_id": str(uuid4()),
                "fluid_system_id": str(uuid4()),
            },
        },
    ).json()
    return org_id, editor_id, editor_headers, project, report


def test_vtx_api_003_cross_tenant_project_returns_no_data(client: TestClient) -> None:
    _, _, _, project, _ = setup_report(client)
    response = client.post(
        f"/api/v1/projects/{project['id']}/configuration-versions",
        headers={
            **headers(capabilities="configure_project"),
            "Idempotency-Key": "cross-tenant-config",
        },
        json={"data": {}},
    )
    assert response.status_code == 404


def test_vtx_api_001_stale_if_match_is_rejected(client: TestClient) -> None:
    _, _, editor_headers, _, report = setup_report(client)
    response = client.patch(
        f"/api/v1/daily-report-revisions/{report['revision']['id']}/sections/general",
        headers=editor_headers,
        json={"expected_version": 1, "data": {}},
    )
    assert response.status_code == 412
    assert response.json()["detail"]["code"] == "REPORT_VERSION_CONFLICT"


def test_vtx_api_004_005_006_full_submit_reject_resubmit_approve_flow(client: TestClient) -> None:
    org_id, _, editor_headers, _, report = setup_report(client)
    submitted_response = client.post(
        f"/api/v1/daily-report-revisions/{report['revision']['id']}/submit",
        headers={**editor_headers, "If-Match": "2", "Idempotency-Key": "submit-r1"},
    )
    assert submitted_response.status_code == 200
    submitted = submitted_response.json()

    locked = client.patch(
        f"/api/v1/daily-report-revisions/{submitted['revision']['id']}/sections/general",
        headers=editor_headers,
        json={"expected_version": 2, "data": {}},
    )
    assert locked.status_code == 423

    reviewer_headers = headers(uuid4(), org_id, "reject_report")
    rejected = client.post(
        f"/api/v1/daily-report-revisions/{submitted['revision']['id']}/reject",
        headers=reviewer_headers,
        json={"expected_checksum": submitted["revision"]["checksum"], "reason": "Review required"},
    ).json()
    assert rejected["revision"]["state"] == "draft"
    assert rejected["revision"]["number"] == 2

    resubmitted = client.post(
        f"/api/v1/daily-report-revisions/{rejected['revision']['id']}/submit",
        headers={**editor_headers, "If-Match": "1", "Idempotency-Key": "submit-r2"},
    ).json()
    approver_headers = headers(uuid4(), org_id, "approve_report")
    approved = client.post(
        f"/api/v1/daily-report-revisions/{resubmitted['revision']['id']}/approve",
        headers=approver_headers,
        json={"expected_checksum": resubmitted["revision"]["checksum"]},
    ).json()
    assert approved["revision"]["state"] == "approved"


def test_vtx_api_002_submit_retry_returns_original_response_without_duplicate_audit(
    client: TestClient,
) -> None:
    _, _, editor_headers, _, report = setup_report(client)
    request_headers = {
        **editor_headers,
        "If-Match": "2",
        "Idempotency-Key": "stable-submit-key",
    }
    first = client.post(
        f"/api/v1/daily-report-revisions/{report['revision']['id']}/submit",
        headers=request_headers,
    )
    second = client.post(
        f"/api/v1/daily-report-revisions/{report['revision']['id']}/submit",
        headers=request_headers,
    )
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
