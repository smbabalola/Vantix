from uuid import UUID, uuid4

from app.store import FoundationStore
from fastapi.testclient import TestClient


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
    product = client.post(
        f"/api/v1/projects/{project['id']}/products",
        headers=editor_headers,
        json={
            "configuration_version_id": configuration["id"],
            "expected_configuration_version": configuration["row_version"],
            "item_code": "BAR-001",
            "item_name": "Barite",
            "packaging": "sack",
            "package_size": "25",
            "package_unit_code": "kg",
            "inventory_applicable": True,
            "inventory_unit_code": "package",
            "specific_gravity": "4.2",
        },
    ).json()
    client.post(
        f"/api/v1/project-products/{product['id']}/prices",
        headers=editor_headers,
        json={
            "expected_configuration_version": product["configuration_row_version"],
            "effective_from": "2026-01-01",
            "unit_price": "18.50",
            "currency": "GBP",
            "price_basis_unit_code": "package",
        },
    )
    readiness = client.post(
        f"/api/v1/projects/{project['id']}/configuration-versions/{configuration['id']}/validate",
        headers=editor_headers,
    ).json()
    client.post(
        f"/api/v1/projects/{project['id']}/configuration-versions/{configuration['id']}/activate",
        headers={**editor_headers, "Idempotency-Key": "activate-config-1"},
        json={
            "expected_version": readiness["validated_version"],
            "expected_checksum": readiness["draft_checksum"],
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


def test_vtx_prj_003_in_memory_activation_matches_hardened_lifecycle(
    client: TestClient, foundation_store: FoundationStore
) -> None:
    org_id = uuid4()
    request_headers = headers(uuid4(), org_id, "create_project,configure_project")

    def create_project(code: str) -> dict:
        response = client.post(
            f"/api/v1/organisations/{org_id}/projects",
            headers=request_headers,
            json={
                "project_code": code,
                "project_name": f"Project {code}",
                "well_name": f"Well {code}",
                "time_zone": "Europe/London",
                "currency": "GBP",
                "unit_set": "Metric",
            },
        )
        assert response.status_code == 201
        return response.json()

    incomplete_project = create_project("INC")
    incomplete = client.post(
        f"/api/v1/projects/{incomplete_project['id']}/configuration-versions",
        headers={**request_headers, "Idempotency-Key": "create-incomplete"},
        json={"data": {}},
    ).json()
    incomplete_readiness = client.post(
        f"/api/v1/projects/{incomplete_project['id']}/configuration-versions/"
        f"{incomplete['id']}/validate",
        headers=request_headers,
    ).json()
    incomplete_activation = client.post(
        f"/api/v1/projects/{incomplete_project['id']}/configuration-versions/"
        f"{incomplete['id']}/activate",
        headers={**request_headers, "Idempotency-Key": "activate-incomplete"},
        json={
            "expected_version": incomplete_readiness["validated_version"],
            "expected_checksum": incomplete_readiness["draft_checksum"],
        },
    )
    assert incomplete_activation.status_code == 422
    assert incomplete_activation.json()["detail"]["code"] == "CONFIGURATION_NOT_READY"

    project = create_project("SEQ")
    project_id = project["id"]

    def create_ready_configuration(key: str, name: str) -> dict:
        interval_id = str(uuid4())
        response = client.post(
            f"/api/v1/projects/{project_id}/configuration-versions",
            headers={**request_headers, "Idempotency-Key": key},
            json={
                "data": {
                    "default_interval_id": interval_id,
                    "intervals": [
                        {
                            "id": interval_id,
                            "name": name,
                            "operation_mode": "drilling",
                        }
                    ],
                }
            },
        )
        assert response.status_code == 201
        configuration = response.json()
        product = client.post(
            f"/api/v1/projects/{project_id}/products",
            headers=request_headers,
            json={
                "configuration_version_id": configuration["id"],
                "expected_configuration_version": configuration["row_version"],
                "item_code": "BAR-001",
                "item_name": "Barite",
                "packaging": "sack",
                "package_size": "25",
                "package_unit_code": "kg",
                "inventory_applicable": True,
                "inventory_unit_code": "package",
                "specific_gravity": "4.2",
            },
        ).json()
        price = client.post(
            f"/api/v1/project-products/{product['id']}/prices",
            headers=request_headers,
            json={
                "expected_configuration_version": product["configuration_row_version"],
                "effective_from": "2026-01-01",
                "unit_price": "18.50",
                "currency": "GBP",
                "price_basis_unit_code": "package",
            },
        )
        assert price.status_code == 201
        return configuration

    def activate(configuration: dict, key: str):
        readiness = client.post(
            f"/api/v1/projects/{project_id}/configuration-versions/{configuration['id']}/validate",
            headers=request_headers,
        ).json()
        return client.post(
            f"/api/v1/projects/{project_id}/configuration-versions/{configuration['id']}/activate",
            headers={**request_headers, "Idempotency-Key": key},
            json={
                "expected_version": readiness["validated_version"],
                "expected_checksum": readiness["draft_checksum"],
            },
        )

    first = create_ready_configuration("create-v1", "First interval")
    assert activate(first, "activate-v1").status_code == 200
    active_retry = activate(first, "reactivate-active-v1")
    assert active_retry.status_code == 409
    assert active_retry.json()["detail"]["code"] == "CONFIGURATION_NOT_DRAFT"

    second = create_ready_configuration("create-v2", "Second interval")
    assert activate(second, "activate-v2").status_code == 200
    superseded_retry = activate(first, "reactivate-superseded-v1")
    assert superseded_retry.status_code == 409
    assert superseded_retry.json()["detail"]["code"] == "CONFIGURATION_NOT_DRAFT"

    project_record = foundation_store.projects[UUID(project_id)]
    records = project_record.configuration_versions
    assert [record["state"] for record in records] == ["superseded", "active"]
    assert sum(record["state"] == "active" for record in records) == 1
    assert project_record.active_snapshot is not None
    assert project_record.active_snapshot.version == 2


def test_vtx_pro_001_002_003_products_prices_readiness_and_snapshot_contract(
    client: TestClient, foundation_store: FoundationStore
) -> None:
    org_id = uuid4()
    request_headers = headers(uuid4(), org_id, "create_project,configure_project")
    project = client.post(
        f"/api/v1/organisations/{org_id}/projects",
        headers=request_headers,
        json={
            "project_code": "PRO",
            "project_name": "Product Project",
            "well_name": "Well PRO",
            "time_zone": "Europe/London",
            "currency": "GBP",
            "unit_set": "Metric",
        },
    ).json()
    interval_id = str(uuid4())
    configuration = client.post(
        f"/api/v1/projects/{project['id']}/configuration-versions",
        headers={**request_headers, "Idempotency-Key": "product-configuration"},
        json={
            "data": {
                "default_interval_id": interval_id,
                "intervals": [
                    {
                        "id": interval_id,
                        "name": "Product interval",
                        "operation_mode": "drilling",
                    }
                ],
            }
        },
    ).json()
    product_request = {
        "configuration_version_id": configuration["id"],
        "expected_configuration_version": 1,
        "item_code": "BAR-001",
        "item_name": "Barite",
        "packaging": "sack",
        "package_size": "025.000",
        "package_unit_code": "kg",
        "inventory_applicable": True,
        "inventory_unit_code": "package",
        "specific_gravity": "04.2000",
    }
    product = client.post(
        f"/api/v1/projects/{project['id']}/products",
        headers=request_headers,
        json=product_request,
    )
    assert product.status_code == 201
    product_body = product.json()
    assert product_body["package_size"] == "25"
    assert product_body["specific_gravity"] == "4.2"

    stale = client.post(
        f"/api/v1/projects/{project['id']}/products",
        headers=request_headers,
        json={**product_request, "item_code": "STALE"},
    )
    assert stale.status_code == 412

    first_price = client.post(
        f"/api/v1/project-products/{product_body['id']}/prices",
        headers=request_headers,
        json={
            "expected_configuration_version": 2,
            "effective_from": "2026-01-01",
            "effective_to": "2026-07-01",
            "unit_price": "18.5000",
            "currency": "GBP",
            "price_basis_unit_code": "package",
        },
    )
    assert first_price.status_code == 201
    assert first_price.json()["configuration_row_version"] == 3

    overlap = client.post(
        f"/api/v1/project-products/{product_body['id']}/prices",
        headers=request_headers,
        json={
            "expected_configuration_version": 3,
            "effective_from": "2026-06-30",
            "unit_price": "19",
            "currency": "GBP",
            "price_basis_unit_code": "package",
        },
    )
    assert overlap.status_code == 422
    assert overlap.json()["detail"]["code"] == "PRICE_PERIOD_OVERLAP"

    second_price = client.post(
        f"/api/v1/project-products/{product_body['id']}/prices",
        headers=request_headers,
        json={
            "expected_configuration_version": 3,
            "effective_from": "2026-07-01",
            "unit_price": "19.25",
            "currency": "GBP",
            "price_basis_unit_code": "package",
        },
    )
    assert second_price.status_code == 201
    selected = client.get(
        f"/api/v1/project-products/{product_body['id']}/price-at?date=2026-07-01",
        headers=request_headers,
    )
    assert selected.status_code == 200
    assert selected.json()["unit_price"] == "19.25"

    readiness = client.post(
        f"/api/v1/projects/{project['id']}/configuration-versions/{configuration['id']}/validate",
        headers=request_headers,
    ).json()
    assert readiness["can_activate"] is True
    activated = client.post(
        f"/api/v1/projects/{project['id']}/configuration-versions/{configuration['id']}/activate",
        headers={**request_headers, "Idempotency-Key": "activate-products"},
        json={
            "expected_version": readiness["validated_version"],
            "expected_checksum": readiness["draft_checksum"],
        },
    )
    assert activated.status_code == 200
    snapshot = foundation_store.projects[UUID(project["id"])].active_snapshot
    assert snapshot is not None
    assert snapshot.payload["products"][0]["prices"][1]["unit_price"] == "19.25"
