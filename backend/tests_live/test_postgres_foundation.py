from __future__ import annotations

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from app.auth import AuthContext, Capability
from app.db import SessionFactory, set_tenant_context
from app.main import app
from app.models import (
    AuditEvent,
    ConfigurationSnapshot,
    ConfigurationVersion,
    DailyReport,
    DailyReportRevision,
    IdempotencyRecord,
    InventoryLedgerLine,
    InventoryPosting,
    Project,
    ProjectProduct,
    ReportPayload,
)
from app.postgres_repository import PostgresFoundationRepository
from app.schemas import (
    ConfigurationCreate,
    ConfigurationPatch,
    ConfigurationVersionExpectation,
    DailyReportCreate,
    DecisionRequest,
    DraftPatch,
    ExportRequest,
    InventoryPostingView,
    InventoryReversalCreate,
    OpeningStockCreate,
    OpeningStockLineCreate,
    OrganisationCreate,
    ProductPriceCreate,
    ProductPricePatch,
    ProjectCreate,
    ProjectProductCreate,
)
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, func, insert, select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

ALL_CAPABILITIES = frozenset(Capability)


def valid_configuration(name: str = "Drilling interval") -> ConfigurationCreate:
    interval_id = uuid4()
    return ConfigurationCreate(
        data={
            "default_interval_id": str(interval_id),
            "intervals": [
                {
                    "id": str(interval_id),
                    "name": name,
                    "operation_mode": "drilling",
                }
            ],
        }
    )


def create_configuration(
    repository: PostgresFoundationRepository,
    auth: AuthContext,
    project_id: UUID,
    body: ConfigurationCreate,
    key: str | None = None,
):
    return repository.create_configuration(
        auth, project_id, body, key or f"create-config-{uuid4()}"
    )


def activate_configuration(
    repository: PostgresFoundationRepository,
    auth: AuthContext,
    project_id: UUID,
    version_id: UUID,
    key: str,
):
    products = repository.list_products(auth, project_id, version_id)
    if not products:
        configuration = repository.get_configuration(auth, project_id, version_id)
        product = repository.create_product(
            auth,
            project_id,
            ProjectProductCreate(
                configuration_version_id=version_id,
                expected_configuration_version=configuration.row_version,
                item_code="BAR-001",
                item_name="Barite",
                packaging="sack",
                package_size="25",
                package_unit_code="kg",
                inventory_applicable=True,
                inventory_unit_code="package",
                specific_gravity="4.2",
            ),
        )
        repository.create_product_price(
            auth,
            product.id,
            ProductPriceCreate(
                expected_configuration_version=product.configuration_row_version,
                effective_from="2026-01-01",
                unit_price="18.50",
                currency="GBP",
                price_basis_unit_code="package",
            ),
        )
    readiness = repository.validate_configuration(auth, project_id, version_id)
    assert readiness.can_activate is True
    return repository.activate_configuration(
        auth,
        project_id,
        version_id,
        key,
        readiness.validated_version,
        readiness.draft_checksum,
    )


def context(user_id: UUID | None = None, organisation_id: UUID | None = None) -> AuthContext:
    return AuthContext(user_id or uuid4(), organisation_id or uuid4(), ALL_CAPABILITIES)


def request_headers(auth: AuthContext) -> dict[str, str]:
    return {
        "X-Vantix-User-ID": str(auth.user_id),
        "X-Vantix-Organisation-ID": str(auth.organisation_id),
        # Deliberately claim everything: database memberships must still win.
        "X-Vantix-Capabilities": ",".join(capability.value for capability in Capability),
    }


def add_project_member(
    auth: AuthContext,
    project_id: UUID,
    *,
    role: str,
    capabilities: list[str],
) -> AuthContext:
    member = context(organisation_id=auth.organisation_id)
    engine = create_engine(os.environ["VANTIX_ADMIN_DATABASE_URL"])
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users (id, external_subject, status) VALUES (:id, :subject, 'active')"
            ),
            {"id": member.user_id, "subject": f"test:{member.user_id}"},
        )
        connection.execute(
            text(
                "INSERT INTO organisation_memberships "
                "(organisation_id, user_id, role, status) "
                "VALUES (:org, :user, :role, 'active')"
            ),
            {
                "org": auth.organisation_id,
                "user": member.user_id,
                "role": role,
            },
        )
        connection.execute(
            text(
                "INSERT INTO project_memberships "
                "(organisation_id, project_id, user_id, role, capabilities) "
                "VALUES (:org, :project, :user, :role, CAST(:caps AS jsonb))"
            ),
            {
                "org": auth.organisation_id,
                "project": project_id,
                "user": member.user_id,
                "role": role,
                "caps": json.dumps(capabilities),
            },
        )
    engine.dispose()
    return member


def prepare_report(
    repository: PostgresFoundationRepository,
    auth: AuthContext,
    *,
    report_date: str = "2026-07-18",
    extra_sections: dict[str, Any] | None = None,
):
    repository.create_organisation(auth, OrganisationCreate(name="Vantix Test Org"))
    project = repository.create_project(
        auth,
        ProjectCreate(
            project_code="NS-A",
            project_name="North Sea A",
            well_name="A-01",
            time_zone="Europe/London",
            currency="GBP",
            unit_set="Field",
        ),
        auth.organisation_id,
    )
    configuration = create_configuration(
        repository,
        auth,
        project.id,
        valid_configuration(),
    )
    activate_configuration(repository, auth, project.id, configuration.id, "activate-foundation")
    report = repository.create_daily_report(
        auth,
        project.id,
        DailyReportCreate(report_date=report_date, report_number="VTX-0001"),
        "create-day",
    )
    data: dict[str, Any] = {
        "operation_mode": "drilling",
        "interval_id": str(uuid4()),
        "fluid_system_id": str(uuid4()),
        "present_activity": "Drilling ahead",
    }
    report = repository.patch_section(
        auth,
        report.revision.id,
        "general",
        DraftPatch(expected_version=1, data=data),
    )
    for section, value in (extra_sections or {}).items():
        report = repository.patch_section(
            auth,
            report.revision.id,
            section,
            DraftPatch(expected_version=report.revision.version, data=value),
        )
    return project, report


def prepare_project(repository: PostgresFoundationRepository, auth: AuthContext):
    repository.create_organisation(auth, OrganisationCreate(name="Vantix Config Org"))
    return repository.create_project(
        auth,
        ProjectCreate(
            project_code="CFG-01",
            project_name="Configuration Project",
            well_name="Well-01",
            time_zone="Europe/London",
            currency="GBP",
            unit_set="Metric",
        ),
        auth.organisation_id,
    )


def test_vtx_prj_002_readiness_blocks_activation_atomically() -> None:
    repository = PostgresFoundationRepository()
    auth = context()
    project = prepare_project(repository, auth)
    configuration = create_configuration(
        repository, auth, project.id, ConfigurationCreate(copy_active=False)
    )

    readiness = repository.validate_configuration(auth, project.id, configuration.id)
    assert readiness.can_activate is False
    assert {issue["code"] for issue in readiness.issues} == {
        "ACTIVE_PRODUCT_REQUIRED",
        "DEFAULT_INTERVAL_REQUIRED",
        "INTERVAL_REQUIRED",
    }
    with pytest.raises(HTTPException) as error:
        repository.activate_configuration(
            auth,
            project.id,
            configuration.id,
            "not-ready",
            readiness.validated_version,
            readiness.draft_checksum,
        )
    assert error.value.status_code == 422

    engine = create_engine(os.environ["VANTIX_ADMIN_DATABASE_URL"])
    with engine.connect() as connection:
        assert connection.scalar(select(ConfigurationSnapshot.id)) is None
        stored_state = connection.scalar(
            select(ConfigurationVersion.state).where(ConfigurationVersion.id == configuration.id)
        )
        assert stored_state == "draft"
    engine.dispose()


def test_vtx_prj_002_activation_is_bound_to_the_validated_draft_version() -> None:
    repository = PostgresFoundationRepository()
    auth = context()
    project = prepare_project(repository, auth)
    configuration = create_configuration(
        repository, auth, project.id, valid_configuration("Reviewed interval")
    )
    reviewed = repository.validate_configuration(auth, project.id, configuration.id)
    changed_data = configuration.data | {
        "intervals": [configuration.data["intervals"][0] | {"name": "Unreviewed change"}]
    }
    repository.patch_configuration(
        auth,
        project.id,
        configuration.id,
        ConfigurationPatch(expected_version=1, data=changed_data),
    )

    with pytest.raises(HTTPException) as conflict:
        repository.activate_configuration(
            auth,
            project.id,
            configuration.id,
            "activate-reviewed-version",
            reviewed.validated_version,
            reviewed.draft_checksum,
        )
    assert conflict.value.status_code == 412
    assert conflict.value.detail["code"] == "CONFIGURATION_VERSION_CONFLICT"

    engine = create_engine(os.environ["VANTIX_ADMIN_DATABASE_URL"])
    with engine.connect() as connection:
        assert connection.scalar(select(ConfigurationSnapshot.id)) is None
    engine.dispose()


def test_vtx_prj_004_draft_creation_is_single_and_idempotent() -> None:
    repository = PostgresFoundationRepository()
    auth = context()
    project = prepare_project(repository, auth)
    body = valid_configuration()
    first = create_configuration(
        repository,
        auth,
        project.id,
        body,
        key="create-one-draft",
    )
    retried = create_configuration(
        repository,
        auth,
        project.id,
        body,
        key="create-one-draft",
    )
    assert retried.id == first.id

    with pytest.raises(HTTPException) as duplicate:
        create_configuration(
            repository,
            auth,
            project.id,
            valid_configuration("Competing draft"),
            key="create-competing-draft",
        )
    assert duplicate.value.status_code == 409
    assert duplicate.value.detail["code"] == "CONFIGURATION_DRAFT_EXISTS"

    engine = create_engine(os.environ["VANTIX_ADMIN_DATABASE_URL"])
    with pytest.raises(DBAPIError), engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO project_configuration_versions "
                "(id, organisation_id, project_id, version_number, state, data, row_version) "
                "VALUES (:id, :org, :project, 2, 'draft', '{}'::jsonb, 1)"
            ),
            {"id": uuid4(), "org": auth.organisation_id, "project": project.id},
        )
    engine.dispose()


def test_vtx_prj_003_004_activation_is_immutable_versioned_and_idempotent() -> None:
    repository = PostgresFoundationRepository()
    auth = context()
    project = prepare_project(repository, auth)
    first = create_configuration(repository, auth, project.id, valid_configuration("Surface"))
    active = activate_configuration(repository, auth, project.id, first.id, "activate-v1")
    retried = activate_configuration(repository, auth, project.id, first.id, "activate-v1")
    assert retried.snapshot_id == active.snapshot_id
    assert retried.checksum == active.checksum

    engine = create_engine(os.environ["VANTIX_ADMIN_DATABASE_URL"])
    with pytest.raises(DBAPIError), engine.begin() as connection:
        connection.execute(
            update(ConfigurationVersion)
            .where(ConfigurationVersion.id == first.id)
            .values(data={"intervals": []})
        )

    copied = create_configuration(repository, auth, project.id, ConfigurationCreate())
    assert copied.version == 2
    assert copied.data == first.data
    interval_id = copied.data["intervals"][0]["id"]
    revised_data = {
        "default_interval_id": interval_id,
        "intervals": [
            {
                "id": interval_id,
                "name": "Production interval",
                "operation_mode": "drilling",
            }
        ],
    }
    saved = repository.patch_configuration(
        auth,
        project.id,
        copied.id,
        ConfigurationPatch(expected_version=1, data=revised_data),
    )
    assert saved.row_version == 2
    with pytest.raises(HTTPException) as conflict:
        repository.patch_configuration(
            auth,
            project.id,
            copied.id,
            ConfigurationPatch(expected_version=1, data=revised_data),
        )
    assert conflict.value.status_code == 412

    with pytest.raises(HTTPException) as reused_key:
        readiness = repository.validate_configuration(auth, project.id, copied.id)
        repository.activate_configuration(
            auth,
            project.id,
            copied.id,
            "activate-v1",
            readiness.validated_version,
            readiness.draft_checksum,
        )
    assert reused_key.value.status_code == 409

    second = activate_configuration(repository, auth, project.id, copied.id, "activate-v2")
    assert second.snapshot_id != active.snapshot_id
    with engine.connect() as connection:
        states = dict(
            connection.execute(
                select(ConfigurationVersion.id, ConfigurationVersion.state).where(
                    ConfigurationVersion.id.in_([first.id, copied.id])
                )
            ).all()
        )
    engine.dispose()
    assert states == {first.id: "superseded", copied.id: "active"}


def test_vtx_prj_004_activation_cannot_regress_to_an_older_draft() -> None:
    repository = PostgresFoundationRepository()
    auth = context()
    project = prepare_project(repository, auth)
    first = create_configuration(repository, auth, project.id, valid_configuration("First"))
    activate_configuration(repository, auth, project.id, first.id, "activate-first")
    older_draft = create_configuration(repository, auth, project.id, ConfigurationCreate())

    engine = create_engine(os.environ["VANTIX_ADMIN_DATABASE_URL"])
    with engine.begin() as connection:
        connection.execute(text("SET LOCAL session_replication_role = 'replica'"))
        connection.execute(
            text(
                "INSERT INTO project_configuration_versions "
                "(id, organisation_id, project_id, version_number, state, data, row_version) "
                "VALUES (:id, :org, :project, 3, 'superseded', '{}'::jsonb, 1)"
            ),
            {"id": uuid4(), "org": auth.organisation_id, "project": project.id},
        )
    engine.dispose()

    readiness = repository.validate_configuration(auth, project.id, older_draft.id)
    with pytest.raises(HTTPException) as conflict:
        repository.activate_configuration(
            auth,
            project.id,
            older_draft.id,
            "activate-older",
            readiness.validated_version,
            readiness.draft_checksum,
        )
    assert conflict.value.status_code == 409
    assert conflict.value.detail["code"] == "CONFIGURATION_NOT_LATEST"


def test_vtx_prj_005_report_revisions_retain_their_configuration_snapshot() -> None:
    repository = PostgresFoundationRepository()
    auth = context()
    project = prepare_project(repository, auth)
    first = create_configuration(repository, auth, project.id, valid_configuration("First"))
    active_first = activate_configuration(repository, auth, project.id, first.id, "first")
    report_one = repository.create_daily_report(
        auth,
        project.id,
        DailyReportCreate(report_date="2026-07-18", report_number="CFG-1"),
        "report-one",
    )

    second = create_configuration(repository, auth, project.id, ConfigurationCreate())
    active_second = activate_configuration(repository, auth, project.id, second.id, "second")
    report_two = repository.create_daily_report(
        auth,
        project.id,
        DailyReportCreate(report_date="2026-07-19", report_number="CFG-2"),
        "report-two",
    )

    engine = create_engine(os.environ["VANTIX_ADMIN_DATABASE_URL"])
    with engine.connect() as connection:
        bindings = dict(
            connection.execute(
                select(DailyReport.id, DailyReport.active_configuration_snapshot_id).where(
                    DailyReport.id.in_([report_one.id, report_two.id])
                )
            ).all()
        )
    engine.dispose()
    assert bindings[report_one.id] == active_first.snapshot_id
    assert bindings[report_two.id] == active_second.snapshot_id


def test_vtx_prj_006_configuration_reads_are_tenant_isolated() -> None:
    repository = PostgresFoundationRepository()
    owner = context()
    project = prepare_project(repository, owner)
    create_configuration(repository, owner, project.id, valid_configuration())

    outsider = context()
    repository.create_organisation(outsider, OrganisationCreate(name="Other Org"))
    with pytest.raises(HTTPException) as error:
        repository.list_configurations(outsider, project.id)
    assert error.value.status_code == 404


def test_vtx_pro_001_002_products_prices_are_ready_frozen_and_database_guarded() -> None:
    repository = PostgresFoundationRepository()
    auth = context()
    project = prepare_project(repository, auth)
    configuration = create_configuration(repository, auth, project.id, valid_configuration())
    product = repository.create_product(
        auth,
        project.id,
        ProjectProductCreate(
            configuration_version_id=configuration.id,
            expected_configuration_version=configuration.row_version,
            item_code="BAR-001",
            item_name="Barite",
            packaging="sack",
            package_size="25",
            package_unit_code="kg",
            inventory_applicable=True,
            inventory_unit_code="package",
            specific_gravity="4.2",
        ),
    )
    incomplete = repository.validate_configuration(auth, project.id, configuration.id)
    assert incomplete.can_activate is False
    assert {issue["code"] for issue in incomplete.issues} == {"ACTIVE_PRODUCT_PRICE_REQUIRED"}

    with_price = repository.create_product_price(
        auth,
        product.id,
        ProductPriceCreate(
            expected_configuration_version=product.configuration_row_version,
            effective_from="2026-01-01",
            effective_to="2026-07-01",
            unit_price="18.5",
            currency="GBP",
            price_basis_unit_code="package",
        ),
    )
    engine = create_engine(os.environ["VANTIX_ADMIN_DATABASE_URL"])
    with pytest.raises(DBAPIError), engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO product_price_history "
                "(id, organisation_id, project_id, project_product_id, effective_from, "
                "effective_to, unit_price, currency, price_basis_unit_code) VALUES "
                "(:id, :org, :project, :product, '2026-06-30', NULL, 19, 'GBP', 'package')"
            ),
            {
                "id": uuid4(),
                "org": auth.organisation_id,
                "project": project.id,
                "product": product.id,
            },
        )

    active = activate_configuration(repository, auth, project.id, configuration.id, "products")
    with engine.connect() as connection:
        snapshot = connection.scalar(
            select(ConfigurationSnapshot.snapshot_json).where(
                ConfigurationSnapshot.id == active.snapshot_id
            )
        )
    assert snapshot["products"][0]["specific_gravity"] == "4.2"
    assert snapshot["products"][0]["prices"][0]["unit_price"] == "18.5"

    with pytest.raises(DBAPIError), engine.begin() as connection:
        connection.execute(
            update(ProjectProduct)
            .where(ProjectProduct.id == product.id)
            .values(item_name="Mutated after activation")
        )
    engine.dispose()
    assert with_price.configuration_row_version == 3


def test_vtx_pro_004_revised_configuration_preserves_stable_product_lineage() -> None:
    repository = PostgresFoundationRepository()
    auth = context()
    project = prepare_project(repository, auth)
    first = create_configuration(repository, auth, project.id, valid_configuration())
    product_v1 = repository.create_product(
        auth,
        project.id,
        ProjectProductCreate(
            configuration_version_id=first.id,
            expected_configuration_version=first.row_version,
            item_code="BAR-001",
            item_name="Barite",
            packaging="sack",
            package_size="25",
            package_unit_code="kg",
            inventory_applicable=True,
            inventory_unit_code="package",
        ),
    )
    repository.create_product_price(
        auth,
        product_v1.id,
        ProductPriceCreate(
            expected_configuration_version=product_v1.configuration_row_version,
            effective_from="2026-01-01",
            unit_price="18.5",
            currency="GBP",
            price_basis_unit_code="t",
        ),
    )
    activate_configuration(repository, auth, project.id, first.id, "activate-lineage-v1")

    second = create_configuration(
        repository,
        auth,
        project.id,
        ConfigurationCreate(copy_active=True),
        "copy-lineage-v2",
    )
    product_v2 = repository.list_products(auth, project.id, second.id)[0]

    assert product_v2.id != product_v1.id
    assert product_v2.product_definition_id == product_v1.product_definition_id
    assert product_v2.item_code == product_v1.item_code

    active_v2 = activate_configuration(
        repository, auth, project.id, second.id, "activate-lineage-v2"
    )
    engine = create_engine(os.environ["VANTIX_ADMIN_DATABASE_URL"])
    with engine.connect() as connection:
        snapshots = connection.scalars(
            select(ConfigurationSnapshot.snapshot_json)
            .where(ConfigurationSnapshot.project_id == project.id)
            .order_by(ConfigurationSnapshot.created_at)
        ).all()
    engine.dispose()
    assert active_v2.snapshot_id is not None
    assert snapshots[0]["products"][0]["id"] == str(product_v1.id)
    assert snapshots[1]["products"][0]["id"] == str(product_v2.id)
    assert snapshots[0]["products"][0]["product_definition_id"] == str(
        product_v1.product_definition_id
    )
    assert snapshots[1]["products"][0]["product_definition_id"] == str(
        product_v1.product_definition_id
    )


def test_vtx_pro_001_package_content_price_basis_matches_domain_and_database() -> None:
    repository = PostgresFoundationRepository()
    auth = context()
    project = prepare_project(repository, auth)
    configuration = create_configuration(repository, auth, project.id, valid_configuration())
    mass = repository.create_product(
        auth,
        project.id,
        ProjectProductCreate(
            configuration_version_id=configuration.id,
            expected_configuration_version=configuration.row_version,
            item_code="BAR-001",
            item_name="Barite",
            packaging="sack",
            package_size="25",
            package_unit_code="kg",
            inventory_applicable=True,
            inventory_unit_code="package",
        ),
    )
    mass = repository.create_product_price(
        auth,
        mass.id,
        ProductPriceCreate(
            expected_configuration_version=mass.configuration_row_version,
            effective_from="2026-01-01",
            unit_price="900",
            currency="GBP",
            price_basis_unit_code="t",
        ),
    )
    volume = repository.create_product(
        auth,
        project.id,
        ProjectProductCreate(
            configuration_version_id=configuration.id,
            expected_configuration_version=mass.configuration_row_version,
            item_code="LIQ-001",
            item_name="Liquid additive",
            packaging="drum",
            package_size="200",
            package_unit_code="L",
            inventory_applicable=True,
            inventory_unit_code="package",
        ),
    )
    repository.create_product_price(
        auth,
        volume.id,
        ProductPriceCreate(
            expected_configuration_version=volume.configuration_row_version,
            effective_from="2026-01-01",
            unit_price="4.5",
            currency="GBP",
            price_basis_unit_code="L",
        ),
    )

    engine = create_engine(os.environ["VANTIX_ADMIN_DATABASE_URL"])
    with pytest.raises(DBAPIError), engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO product_price_history "
                "(id, organisation_id, project_id, project_product_id, effective_from, "
                "unit_price, currency, price_basis_unit_code) VALUES "
                "(:id, :org, :project, :product, '2027-01-01', 1, 'GBP', 'L')"
            ),
            {
                "id": uuid4(),
                "org": auth.organisation_id,
                "project": project.id,
                "product": mass.id,
            },
        )
    engine.dispose()


def test_vtx_pro_001_002_priced_product_delete_is_atomic_and_audited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = PostgresFoundationRepository()
    auth = context()
    project = prepare_project(repository, auth)
    configuration = create_configuration(repository, auth, project.id, valid_configuration())

    def create_priced_product(code: str, expected_version: int):
        product = repository.create_product(
            auth,
            project.id,
            ProjectProductCreate(
                configuration_version_id=configuration.id,
                expected_configuration_version=expected_version,
                item_code=code,
                item_name=code,
                packaging="sack",
                package_size="25",
                package_unit_code="kg",
                inventory_applicable=True,
                inventory_unit_code="package",
            ),
        )
        first_price = repository.create_product_price(
            auth,
            product.id,
            ProductPriceCreate(
                expected_configuration_version=product.configuration_row_version,
                effective_from="2026-01-01",
                effective_to="2026-07-01",
                unit_price="18",
                currency="GBP",
                price_basis_unit_code="t",
            ),
        )
        return repository.create_product_price(
            auth,
            product.id,
            ProductPriceCreate(
                expected_configuration_version=first_price.configuration_row_version,
                effective_from="2026-07-01",
                unit_price="19",
                currency="GBP",
                price_basis_unit_code="t",
            ),
        )

    priced = create_priced_product("DEL-001", configuration.row_version)
    deleted = repository.delete_product(
        auth,
        priced.id,
        ConfigurationVersionExpectation(
            expected_configuration_version=priced.configuration_row_version
        ),
    )
    engine = create_engine(os.environ["VANTIX_ADMIN_DATABASE_URL"])
    with engine.connect() as connection:
        assert (
            connection.scalar(
                text("SELECT count(*) FROM project_products WHERE id = :id"), {"id": priced.id}
            )
            == 0
        )
        assert (
            connection.scalar(
                text("SELECT count(*) FROM product_price_history WHERE project_product_id = :id"),
                {"id": priced.id},
            )
            == 0
        )
        audit = connection.scalar(
            select(AuditEvent).where(
                AuditEvent.entity_id == priced.id,
                AuditEvent.action == "delete_draft",
            )
        )
        assert audit is not None
        assert (
            connection.scalar(
                select(ConfigurationVersion.row_version).where(
                    ConfigurationVersion.id == configuration.id
                )
            )
            == deleted.configuration_row_version
        )

    rollback_candidate = create_priced_product("ROLL-001", deleted.configuration_row_version)
    before_version = rollback_candidate.configuration_row_version

    def fail_audit(*args, **kwargs) -> None:
        raise RuntimeError("forced audit failure")

    monkeypatch.setattr(repository, "_audit", fail_audit)
    with pytest.raises(RuntimeError, match="forced audit failure"):
        repository.delete_product(
            auth,
            rollback_candidate.id,
            ConfigurationVersionExpectation(expected_configuration_version=before_version),
        )
    with engine.connect() as connection:
        assert (
            connection.scalar(
                text("SELECT count(*) FROM project_products WHERE id = :id"),
                {"id": rollback_candidate.id},
            )
            == 1
        )
        assert (
            connection.scalar(
                text("SELECT count(*) FROM product_price_history WHERE project_product_id = :id"),
                {"id": rollback_candidate.id},
            )
            == 2
        )
        assert (
            connection.scalar(
                select(ConfigurationVersion.row_version).where(
                    ConfigurationVersion.id == configuration.id
                )
            )
            == before_version
        )
    engine.dispose()


def test_vtx_auth_004_005_product_rows_require_tenant_and_project_authority() -> None:
    repository = PostgresFoundationRepository()
    owner = context()
    project = prepare_project(repository, owner)
    configuration = create_configuration(repository, owner, project.id, valid_configuration())
    product = repository.create_product(
        owner,
        project.id,
        ProjectProductCreate(
            configuration_version_id=configuration.id,
            expected_configuration_version=configuration.row_version,
            item_code="SEC-001",
            item_name="Secured product",
            packaging="drum",
            package_size="200",
            package_unit_code="L",
            inventory_applicable=True,
            inventory_unit_code="L",
        ),
    )
    nonmember = context(organisation_id=owner.organisation_id)
    admin_engine = create_engine(os.environ["VANTIX_ADMIN_DATABASE_URL"])
    with admin_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users (id, external_subject, status) VALUES (:id, :subject, 'active')"
            ),
            {"id": nonmember.user_id, "subject": f"test:{nonmember.user_id}"},
        )
        connection.execute(
            text(
                "INSERT INTO organisation_memberships "
                "(organisation_id, user_id, role, status) "
                "VALUES (:org, :user, 'auditor', 'active')"
            ),
            {"org": owner.organisation_id, "user": nonmember.user_id},
        )
    admin_engine.dispose()

    app_engine = create_engine(os.environ["VANTIX_DATABASE_URL"])

    def set_context(connection) -> None:
        connection.execute(
            text(
                "SELECT set_config('app.current_user_id', :user, true), "
                "set_config('app.current_org_id', :org, true), "
                "set_config('app.current_project_ids', :projects, true), "
                "set_config('app.is_system_service', 'false', true)"
            ),
            {
                "user": str(nonmember.user_id),
                "org": str(owner.organisation_id),
                "projects": str(project.id),
            },
        )

    with app_engine.begin() as connection:
        set_context(connection)
        assert connection.scalar(text("SELECT count(*) FROM project_products")) == 0
        assert connection.scalar(text("SELECT count(*) FROM project_product_definitions")) == 0

    with pytest.raises(DBAPIError), app_engine.begin() as connection:
        set_context(connection)
        connection.execute(
            text(
                "INSERT INTO product_price_history "
                "(id, organisation_id, project_id, project_product_id, effective_from, "
                "unit_price, currency, price_basis_unit_code) VALUES "
                "(:id, :org, :project, :product, '2026-01-01', 1, 'GBP', 'package')"
            ),
            {
                "id": uuid4(),
                "org": owner.organisation_id,
                "project": project.id,
                "product": product.id,
            },
        )
    app_engine.dispose()


def test_vtx_prj_001_organisation_admin_can_manage_all_organisation_projects() -> None:
    repository = PostgresFoundationRepository()
    owner = context()
    project = prepare_project(repository, owner)
    create_configuration(repository, owner, project.id, valid_configuration())
    administrator = context(organisation_id=owner.organisation_id)

    engine = create_engine(os.environ["VANTIX_ADMIN_DATABASE_URL"])
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users (id, external_subject, status) VALUES (:id, :subject, 'active')"
            ),
            {"id": administrator.user_id, "subject": f"test:{administrator.user_id}"},
        )
        connection.execute(
            text(
                "INSERT INTO organisation_memberships "
                "(organisation_id, user_id, role, status) "
                "VALUES (:org, :user, 'organisation_admin', 'active')"
            ),
            {"org": owner.organisation_id, "user": administrator.user_id},
        )
    engine.dispose()

    assert [item.id for item in repository.list_projects(administrator)] == [project.id]
    assert len(repository.list_configurations(administrator, project.id)) == 1


def test_vtx_auth_006_path_supplied_project_id_cannot_escalate_membership() -> None:
    repository = PostgresFoundationRepository()
    owner = context()
    project = prepare_project(repository, owner)
    nonmember = context(organisation_id=owner.organisation_id)
    admin_engine = create_engine(os.environ["VANTIX_ADMIN_DATABASE_URL"])
    with admin_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users (id, external_subject, status) VALUES (:id, :subject, 'active')"
            ),
            {"id": nonmember.user_id, "subject": f"test:{nonmember.user_id}"},
        )
        connection.execute(
            text(
                "INSERT INTO organisation_memberships "
                "(organisation_id, user_id, role, status) "
                "VALUES (:org, :user, 'auditor', 'active')"
            ),
            {"org": owner.organisation_id, "user": nonmember.user_id},
        )
    admin_engine.dispose()

    app_engine = create_engine(os.environ["VANTIX_DATABASE_URL"])

    def set_context(connection) -> None:
        connection.execute(
            text(
                "SELECT set_config('app.current_user_id', :user, true), "
                "set_config('app.current_org_id', :org, true), "
                "set_config('app.current_project_ids', :projects, true), "
                "set_config('app.is_system_service', 'false', true)"
            ),
            {
                "user": str(nonmember.user_id),
                "org": str(owner.organisation_id),
                "projects": str(project.id),
            },
        )

    with app_engine.begin() as connection:
        set_context(connection)
        disclosed = connection.scalar(
            text("SELECT count(*) FROM project_memberships WHERE project_id = :project"),
            {"project": project.id},
        )
        assert disclosed == 0

    with pytest.raises(DBAPIError), app_engine.begin() as connection:
        set_context(connection)
        connection.execute(
            text(
                "INSERT INTO project_memberships "
                "(organisation_id, project_id, user_id, role, capabilities) "
                "VALUES (:org, :project, :user, 'project_admin', '[]'::jsonb)"
            ),
            {
                "org": owner.organisation_id,
                "project": project.id,
                "user": nonmember.user_id,
            },
        )

    with app_engine.begin() as connection:
        set_context(connection)
        updated = connection.execute(
            text(
                "UPDATE project_memberships SET role = 'project_admin' "
                "WHERE project_id = :project AND user_id = :owner"
            ),
            {"project": project.id, "owner": owner.user_id},
        )
        deleted = connection.execute(
            text(
                "DELETE FROM project_memberships WHERE project_id = :project AND user_id = :owner"
            ),
            {"project": project.id, "owner": owner.user_id},
        )
        assert updated.rowcount == 0
        assert deleted.rowcount == 0
    app_engine.dispose()


def test_vtx_prj_003_cross_project_snapshot_bindings_are_rejected_by_database() -> None:
    repository = PostgresFoundationRepository()
    auth = context()
    project_a = prepare_project(repository, auth)
    project_b = repository.create_project(
        auth,
        ProjectCreate(
            project_code="CFG-02",
            project_name="Second Project",
            well_name="Well-02",
            time_zone="Europe/London",
            currency="GBP",
            unit_set="Metric",
        ),
        auth.organisation_id,
    )
    config_a = create_configuration(repository, auth, project_a.id, valid_configuration("A"))
    active_a = activate_configuration(repository, auth, project_a.id, config_a.id, "activate-a")
    config_b = create_configuration(repository, auth, project_b.id, valid_configuration("B"))
    active_b = activate_configuration(repository, auth, project_b.id, config_b.id, "activate-b")
    draft_b = create_configuration(repository, auth, project_b.id, ConfigurationCreate())
    report_a = repository.create_daily_report(
        auth,
        project_a.id,
        DailyReportCreate(report_date="2026-07-20", report_number="OWN-A"),
        "create-ownership-report",
    )

    engine = create_engine(os.environ["VANTIX_ADMIN_DATABASE_URL"])
    with pytest.raises(DBAPIError), engine.begin() as connection:
        connection.execute(
            update(Project)
            .where(Project.id == project_a.id)
            .values(
                current_configuration_version_id=config_b.id,
                current_configuration_snapshot_id=active_b.snapshot_id,
            )
        )

    with pytest.raises(DBAPIError), engine.begin() as connection:
        connection.execute(
            update(ConfigurationVersion)
            .where(ConfigurationVersion.id == config_a.id)
            .values(project_id=project_b.id)
        )

    with pytest.raises(DBAPIError), engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO project_configuration_snapshots "
                "(id, organisation_id, project_id, configuration_version_id, "
                "schema_version, snapshot_json, canonical_checksum) "
                "VALUES (:id, :org, :project, :version, '1.0', '{}'::jsonb, :checksum)"
            ),
            {
                "id": uuid4(),
                "org": auth.organisation_id,
                "project": project_a.id,
                "version": draft_b.id,
                "checksum": "0" * 64,
            },
        )

    with pytest.raises(DBAPIError), engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO daily_reports "
                "(id, organisation_id, project_id, report_date, shift_code, report_number, "
                "active_configuration_snapshot_id, aggregate_state, row_version) "
                "VALUES (:id, :org, :project, '2026-07-21', '', 'CROSS', "
                ":snapshot, 'draft', 1)"
            ),
            {
                "id": uuid4(),
                "org": auth.organisation_id,
                "project": project_a.id,
                "snapshot": active_b.snapshot_id,
            },
        )

    with pytest.raises(DBAPIError), engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO daily_report_revisions "
                "(id, organisation_id, project_id, daily_report_id, revision_number, "
                "revision_kind, state, configuration_snapshot_id, data, row_version) "
                "VALUES (:id, :org, :project, :report, 2, 'amendment', 'submitted', "
                ":snapshot, '{}'::jsonb, 1)"
            ),
            {
                "id": uuid4(),
                "org": auth.organisation_id,
                "project": project_a.id,
                "report": report_a.id,
                "snapshot": active_b.snapshot_id,
            },
        )
    engine.dispose()
    assert active_a.snapshot_id != active_b.snapshot_id


def test_vtx_mvp_003_vtx_auth_004_005_live_rls_blocks_cross_tenant_access() -> None:
    repository = PostgresFoundationRepository()
    auth_a = context()
    project_a, _ = prepare_report(repository, auth_a)

    auth_b = context()
    project_b, _ = prepare_report(repository, auth_b, report_date="2026-07-19")

    with SessionFactory.begin() as session:
        set_tenant_context(
            session,
            user_id=auth_a.user_id,
            organisation_id=auth_a.organisation_id,
            project_ids=(project_a.id, project_b.id),
        )
        assert session.scalar(select(Project).where(Project.id == project_a.id)) is not None
        assert session.scalar(select(Project).where(Project.id == project_b.id)) is None
        result = session.execute(
            update(Project).where(Project.id == project_b.id).values(project_name="Breached")
        )
        assert result.rowcount == 0


def test_vtx_mvp_005_vtx_api_001_concurrent_edits_do_not_silently_overwrite() -> None:
    repository = PostgresFoundationRepository()
    auth = context()
    _, report = prepare_report(repository, auth)

    def edit(activity: str) -> str:
        try:
            repository.patch_section(
                auth,
                report.revision.id,
                "general",
                DraftPatch(
                    expected_version=report.revision.version,
                    data={
                        **report.revision.data["general"],
                        "present_activity": activity,
                    },
                ),
            )
            return "saved"
        except HTTPException as exc:
            return exc.detail["code"]

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(edit, ["Drilling", "Circulating"]))
    assert sorted(results) == ["REPORT_VERSION_CONFLICT", "saved"]


def test_vtx_api_002_live_submission_is_idempotent_and_payload_change_is_rejected() -> None:
    repository = PostgresFoundationRepository()
    auth = context()
    _, report = prepare_report(repository, auth)
    first = repository.submit_report(
        auth, report.revision.id, report.revision.version, "submit-once"
    )
    retry = repository.submit_report(
        auth, report.revision.id, report.revision.version, "submit-once"
    )
    assert retry == first

    with pytest.raises(HTTPException) as reused:
        repository.submit_report(
            auth, report.revision.id, report.revision.version + 1, "submit-once"
        )
    assert reused.value.detail["code"] == "IDEMPOTENCY_KEY_REUSED"


def test_vtx_mvp_006_010_submission_rolls_back_every_side_effect_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = PostgresFoundationRepository()
    auth = context()
    _, report = prepare_report(repository, auth)

    def fail(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("injected failure before commit")

    monkeypatch.setattr(repository, "_remember_idempotency", fail)
    with pytest.raises(RuntimeError):
        repository.submit_report(
            auth, report.revision.id, report.revision.version, "rollback-submit"
        )

    with SessionFactory.begin() as session:
        set_tenant_context(
            session,
            user_id=auth.user_id,
            organisation_id=auth.organisation_id,
            project_ids=(report.project_id,),
        )
        revision = session.get(DailyReportRevision, report.revision.id)
        assert revision is not None and revision.state == "draft"
        assert (
            session.scalar(
                select(ReportPayload).where(
                    ReportPayload.daily_report_revision_id == report.revision.id
                )
            )
            is None
        )
        submit_audits = session.scalars(
            select(AuditEvent).where(
                AuditEvent.entity_id == report.revision.id,
                AuditEvent.action == "submit",
            )
        ).all()
        assert submit_audits == []


def test_vtx_mvp_007_008_rejection_preserves_submission_and_creates_new_draft() -> None:
    repository = PostgresFoundationRepository()
    editor = context()
    project, report = prepare_report(repository, editor)
    submitted = repository.submit_report(
        editor, report.revision.id, report.revision.version, "submit-reject"
    )
    reviewer = add_project_member(
        editor,
        project.id,
        role="reviewer",
        capabilities=[Capability.REJECT_REPORT.value],
    )
    rejected = repository.reject_report(
        reviewer,
        submitted.revision.id,
        DecisionRequest(
            expected_checksum=submitted.revision.checksum or "",
            reason="Correct the interval",
        ),
    )
    assert rejected.revision.state == "draft"
    assert rejected.revision.based_on_revision_id == submitted.revision.id
    with SessionFactory.begin() as session:
        set_tenant_context(
            session,
            user_id=editor.user_id,
            organisation_id=editor.organisation_id,
            project_ids=(project.id,),
        )
        original = session.get(DailyReportRevision, submitted.revision.id)
        assert original is not None and original.state == "rejected"
        assert original.data == rejected.revision.data


def test_vtx_mvp_006_009_database_trigger_blocks_direct_immutable_data_mutation() -> None:
    repository = PostgresFoundationRepository()
    auth = context()
    project, report = prepare_report(repository, auth)
    submitted = repository.submit_report(
        auth, report.revision.id, report.revision.version, "submit-trigger"
    )
    with pytest.raises(DBAPIError), SessionFactory.begin() as session:
        set_tenant_context(
            session,
            user_id=auth.user_id,
            organisation_id=auth.organisation_id,
            project_ids=(project.id,),
        )
        session.execute(
            update(DailyReportRevision)
            .where(DailyReportRevision.id == submitted.revision.id)
            .values(data={"general": {"operation_mode": "tampered"}})
        )


def test_vtx_auth_010_client_viewer_never_receives_internal_comments() -> None:
    repository = PostgresFoundationRepository()
    editor = context()
    project, report = prepare_report(
        repository,
        editor,
        extra_sections={
            "comments": {
                "items": [
                    {"content": "Client note", "visibility": "client"},
                    {"content": "Internal note", "visibility": "internal"},
                ]
            }
        },
    )
    submitted = repository.submit_report(
        editor, report.revision.id, report.revision.version, "submit-client"
    )
    approver = add_project_member(
        editor,
        project.id,
        role="approver",
        capabilities=[
            Capability.APPROVE_REPORT.value,
            Capability.VIEW_CLIENT_REPORT.value,
            Capability.VIEW_INTERNAL_CONTENT.value,
        ],
    )
    approved = repository.approve_report(
        approver,
        submitted.revision.id,
        DecisionRequest(expected_checksum=submitted.revision.checksum or ""),
    )
    client = add_project_member(
        editor,
        project.id,
        role="client_viewer",
        capabilities=[Capability.VIEW_CLIENT_REPORT.value],
    )
    client_report = repository.get_report(client, approved.id)
    rendered = json_text = str(client_report.revision.data)
    assert "Client note" in rendered
    assert "Internal note" not in json_text


def test_vtx_det_006_011_exports_use_stored_frozen_payload_and_checksum() -> None:
    repository = PostgresFoundationRepository()
    editor = context()
    project, report = prepare_report(repository, editor)
    submitted = repository.submit_report(
        editor, report.revision.id, report.revision.version, "submit-export"
    )
    approver = add_project_member(
        editor,
        project.id,
        role="approver",
        capabilities=[
            Capability.APPROVE_REPORT.value,
            Capability.EXPORT_REPORT.value,
            Capability.VIEW_CLIENT_REPORT.value,
            Capability.VIEW_INTERNAL_CONTENT.value,
        ],
    )
    approved = repository.approve_report(
        approver,
        submitted.revision.id,
        DecisionRequest(expected_checksum=submitted.revision.checksum or ""),
    )
    first = repository.create_export(
        approver,
        approved.revision.id,
        ExportRequest(format="xlsx", visibility="internal"),
        "export-one",
    )
    second = repository.create_export(
        approver,
        approved.revision.id,
        ExportRequest(format="xlsx", visibility="internal"),
        "export-two",
    )
    assert first.payload_checksum == second.payload_checksum == approved.revision.checksum


def test_vtx_mvp_006_terminal_revision_state_cannot_escape_via_repository_or_raw_sql() -> None:
    repository = PostgresFoundationRepository()
    auth = context()
    project, report = prepare_report(repository, auth)
    submitted = repository.submit_report(
        auth, report.revision.id, report.revision.version, "submit-terminal-guard"
    )

    with pytest.raises(HTTPException) as locked:
        repository.patch_section(
            auth,
            submitted.revision.id,
            "general",
            DraftPatch(expected_version=submitted.revision.version, data={}),
        )
    assert locked.value.detail["code"] == "REPORT_REVISION_LOCKED"

    with pytest.raises(DBAPIError), SessionFactory.begin() as session:
        set_tenant_context(
            session,
            user_id=auth.user_id,
            organisation_id=auth.organisation_id,
            project_ids=(project.id,),
        )
        session.execute(
            text("UPDATE daily_report_revisions SET state = 'draft' WHERE id = :revision_id"),
            {"revision_id": submitted.revision.id},
        )


@pytest.mark.parametrize("decision", ["approved", "rejected"])
def test_vtx_mvp_006_terminal_revision_state_cannot_escape_via_orm(decision: str) -> None:
    repository = PostgresFoundationRepository()
    editor = context()
    project, report = prepare_report(repository, editor)
    submitted = repository.submit_report(
        editor, report.revision.id, report.revision.version, f"submit-{decision}-guard"
    )
    if decision == "approved":
        actor = add_project_member(
            editor,
            project.id,
            role="approver",
            capabilities=[Capability.APPROVE_REPORT.value],
        )
        repository.approve_report(
            actor,
            submitted.revision.id,
            DecisionRequest(expected_checksum=submitted.revision.checksum or ""),
        )
    else:
        actor = add_project_member(
            editor,
            project.id,
            role="reviewer",
            capabilities=[Capability.REJECT_REPORT.value],
        )
        repository.reject_report(
            actor,
            submitted.revision.id,
            DecisionRequest(
                expected_checksum=submitted.revision.checksum or "",
                reason="Correction required",
            ),
        )

    with pytest.raises(DBAPIError), SessionFactory.begin() as session:
        set_tenant_context(
            session,
            user_id=editor.user_id,
            organisation_id=editor.organisation_id,
            project_ids=(project.id,),
        )
        revision = session.get(DailyReportRevision, submitted.revision.id)
        assert revision is not None
        revision.state = "draft"
        session.flush()


def test_vtx_auth_010_read_endpoints_use_database_capabilities_and_visibility() -> None:
    repository = PostgresFoundationRepository()
    editor = context()
    project, report = prepare_report(
        repository,
        editor,
        extra_sections={
            "comments": {
                "items": [
                    {"content": "Client note", "visibility": "client"},
                    {"content": "Internal note", "visibility": "internal"},
                ]
            }
        },
    )
    client = add_project_member(
        editor,
        project.id,
        role="client_viewer",
        capabilities=[
            Capability.VIEW_CLIENT_REPORT.value,
            Capability.EXPORT_REPORT.value,
        ],
    )
    capabilityless = add_project_member(
        editor,
        project.id,
        role="observer",
        capabilities=[],
    )

    with pytest.raises(HTTPException) as client_draft:
        repository.get_report(client, report.id)
    assert client_draft.value.status_code == 404
    with pytest.raises(HTTPException) as client_validate:
        repository.validate_report(client, report.revision.id)
    assert client_validate.value.detail["code"] == "CAPABILITY_DENIED"
    with pytest.raises(HTTPException) as unprivileged_draft:
        repository.get_report(capabilityless, report.id)
    assert unprivileged_draft.value.status_code == 404

    submitted = repository.submit_report(
        editor, report.revision.id, report.revision.version, "submit-read-auth"
    )
    approver = add_project_member(
        editor,
        project.id,
        role="approver",
        capabilities=[Capability.APPROVE_REPORT.value],
    )
    approved = repository.approve_report(
        approver,
        submitted.revision.id,
        DecisionRequest(expected_checksum=submitted.revision.checksum or ""),
    )
    visible = repository.get_report(client, approved.id)
    assert "Client note" in str(visible.revision.data)
    assert "Internal note" not in str(visible.revision.data)

    with pytest.raises(HTTPException) as unprivileged_approved:
        repository.get_report(capabilityless, approved.id)
    assert unprivileged_approved.value.status_code == 404
    with pytest.raises(HTTPException) as unprivileged_audit:
        repository.audit_events(capabilityless, project.id)
    assert unprivileged_audit.value.detail["code"] == "CAPABILITY_DENIED"
    with pytest.raises(HTTPException) as internal_export:
        repository.create_export(
            client,
            approved.revision.id,
            ExportRequest(format="xlsx", visibility="internal"),
            "client-internal-export",
        )
    assert internal_export.value.detail["code"] == "INTERNAL_VISIBILITY_DENIED"
    client_export = repository.create_export(
        client,
        approved.revision.id,
        ExportRequest(format="xlsx", visibility="client"),
        "client-visible-export",
    )
    assert client_export.visibility == "client"

    with TestClient(app) as api_client:
        client_detail = api_client.get(
            f"/api/v1/daily-reports/{approved.id}", headers=request_headers(client)
        )
        assert client_detail.status_code == 200
        assert "Internal note" not in str(client_detail.json())
        denied_detail = api_client.get(
            f"/api/v1/daily-reports/{approved.id}", headers=request_headers(capabilityless)
        )
        assert denied_detail.status_code == 404
        denied_validation = api_client.post(
            f"/api/v1/daily-report-revisions/{approved.revision.id}/validate",
            headers=request_headers(client),
        )
        assert denied_validation.status_code == 403
        denied_audit = api_client.get(
            f"/api/v1/projects/{project.id}/audit-events",
            headers=request_headers(capabilityless),
        )
        assert denied_audit.status_code == 403
        denied_export = api_client.post(
            f"/api/v1/daily-report-revisions/{approved.revision.id}/exports",
            headers={**request_headers(client), "Idempotency-Key": "api-client-internal"},
            json={"format": "xlsx", "visibility": "internal"},
        )
        assert denied_export.status_code == 403


def test_vtx_mvp_001_live_migration_head_and_force_rls_are_active() -> None:
    engine = create_engine(os.environ["VANTIX_ADMIN_DATABASE_URL"])
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
            "0007_inventory_opening_stock"
        )
        flags = connection.execute(
            text(
                """
                SELECT relrowsecurity, relforcerowsecurity FROM pg_class
                WHERE relname = 'daily_report_revisions'
                """
            )
        ).one()
        assert flags == (True, True)
    engine.dispose()


def test_vtx_mvp_001_alembic_metadata_has_no_schema_drift() -> None:
    environment = {
        **os.environ,
        "VANTIX_DATABASE_URL": os.environ["VANTIX_ADMIN_DATABASE_URL"],
    }
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "check"],
        check=True,
        cwd=os.getcwd(),
        env=environment,
        capture_output=True,
        text=True,
    )
    assert "No new upgrade operations detected" in result.stdout


def test_vtx_pro_004_005_live_opening_cost_is_frozen_and_reversal_is_exact() -> None:
    repository = PostgresFoundationRepository()
    auth = context()
    project = prepare_project(repository, auth)
    configuration = create_configuration(repository, auth, project.id, valid_configuration())
    activate_configuration(repository, auth, project.id, configuration.id, "activate-opening-v1")
    authority = repository.opening_stock_authority(auth, project.id, date(2026, 7, 18))
    product = authority.products[0]
    request = OpeningStockCreate(
        expected_configuration_snapshot_id=authority.configuration_snapshot_id,
        posting_date="2026-07-18",
        lines=[
            OpeningStockLineCreate(
                product_definition_id=product.product_definition_id,
                entered_quantity="4",
                entered_unit_code="package",
            )
        ],
    )
    posted = repository.post_opening_stock(auth, project.id, request, "opening-live-1")
    assert posted.lines[0].canonical_signed_quantity == "100"
    assert posted.lines[0].applied_unit_price == "18.5"
    assert posted.lines[0].posted_line_amount == "74.00"
    assert (
        repository.post_opening_stock(auth, project.id, request, "opening-live-1").id == posted.id
    )
    with pytest.raises(HTTPException) as reused:
        repository.post_opening_stock(
            auth,
            project.id,
            request.model_copy(update={"posting_date": date(2026, 7, 19)}),
            "opening-live-1",
        )
    assert reused.value.status_code == 409

    draft_v2 = create_configuration(
        repository, auth, project.id, ConfigurationCreate(copy_active=True), "opening-v2"
    )
    copied_product = repository.list_products(auth, project.id, draft_v2.id)[0]
    copied_price = copied_product.prices[0]
    updated_product = repository.patch_product_price(
        auth,
        copied_price.id,
        ProductPricePatch(
            expected_configuration_version=draft_v2.row_version,
            effective_from=copied_price.effective_from,
            effective_to=copied_price.effective_to,
            unit_price="999",
            currency="GBP",
            price_basis_unit_code="package",
        ),
    )
    readiness = repository.validate_configuration(auth, project.id, draft_v2.id)
    active_v2 = repository.activate_configuration(
        auth,
        project.id,
        draft_v2.id,
        "activate-opening-v2",
        updated_product.configuration_row_version,
        readiness.draft_checksum,
    )
    historical = repository.list_inventory_postings(auth, project.id)[0]
    assert historical.lines[0].applied_unit_price == "18.5"
    assert historical.lines[0].posted_line_amount == "74.00"

    assert active_v2.snapshot_id is not None
    admin = create_engine(os.environ["VANTIX_ADMIN_DATABASE_URL"])
    with pytest.raises(DBAPIError), admin.begin() as connection:
        connection.execute(
            insert(InventoryPosting).values(
                id=uuid4(),
                organisation_id=auth.organisation_id,
                project_id=project.id,
                source_configuration_snapshot_id=active_v2.snapshot_id,
                posting_type="reversal",
                status="building",
                posting_date=date(2026, 7, 19),
                reversal_of_posting_id=posted.id,
                reason="Forged reversal snapshot",
                posted_by=auth.user_id,
            )
        )

    reversal = repository.reverse_inventory_posting(
        auth,
        project.id,
        posted.id,
        InventoryReversalCreate(
            posting_date="2026-07-19", reason="Verified opening count correction"
        ),
        "reverse-opening-live-1",
    )
    assert (
        reversal.lines[0].configuration_product_version_id
        == posted.lines[0].configuration_product_version_id
    )
    assert reversal.lines[0].product_price_version_id == posted.lines[0].product_price_version_id
    assert reversal.lines[0].canonical_signed_quantity == "-100"
    assert reversal.lines[0].posted_line_amount == "-74.00"

    with pytest.raises(DBAPIError), admin.begin() as connection:
        connection.execute(
            update(InventoryLedgerLine)
            .where(InventoryLedgerLine.id == posted.lines[0].id)
            .values(canonical_signed_quantity=999)
        )
    with pytest.raises(DBAPIError), admin.begin() as connection:
        connection.execute(
            update(InventoryPosting)
            .where(InventoryPosting.id == posted.id)
            .values(status="building")
        )
    with pytest.raises(DBAPIError), admin.begin() as connection:
        connection.execute(
            delete(InventoryLedgerLine).where(InventoryLedgerLine.id == posted.lines[0].id)
        )
    with pytest.raises(DBAPIError), admin.begin() as connection:
        connection.execute(
            insert(InventoryPosting).values(
                id=uuid4(),
                organisation_id=auth.organisation_id,
                project_id=project.id,
                source_configuration_snapshot_id=posted.source_configuration_snapshot_id,
                posting_type="reversal",
                status="building",
                posting_date=date(2026, 7, 20),
                reversal_of_posting_id=posted.id,
                reason="Forged second reversal",
                posted_by=auth.user_id,
            )
        )
    admin.dispose()


def test_vtx_auth_004_inventory_tables_enforce_cross_tenant_rls() -> None:
    repository = PostgresFoundationRepository()
    auth = context()
    project = prepare_project(repository, auth)
    configuration = create_configuration(repository, auth, project.id, valid_configuration())
    activate_configuration(repository, auth, project.id, configuration.id, "activate-inventory-rls")
    authority = repository.opening_stock_authority(auth, project.id, date(2026, 7, 18))
    repository.post_opening_stock(
        auth,
        project.id,
        OpeningStockCreate(
            expected_configuration_snapshot_id=authority.configuration_snapshot_id,
            posting_date="2026-07-18",
            lines=[
                OpeningStockLineCreate(
                    product_definition_id=authority.products[0].product_definition_id,
                    entered_quantity="1",
                    entered_unit_code="package",
                )
            ],
        ),
        "opening-rls",
    )
    poster = add_project_member(auth, project.id, role="logistics", capabilities=["post_inventory"])
    assert (
        repository.opening_stock_authority(poster, project.id, date(2026, 7, 18)).project_id
        == project.id
    )
    assert len(repository.list_inventory_postings(poster, project.id)) == 1
    outsider = context()
    with SessionFactory.begin() as session:
        set_tenant_context(
            session,
            user_id=outsider.user_id,
            organisation_id=outsider.organisation_id,
            project_ids=(project.id,),
        )
        assert session.scalar(select(func.count()).select_from(InventoryPosting)) == 0
        assert session.scalar(select(func.count()).select_from(InventoryLedgerLine)) == 0


def test_vtx_pro_004_stale_reviewed_snapshot_rolls_back_posting_idempotency_and_audit() -> None:
    repository = PostgresFoundationRepository()
    auth = context()
    project = prepare_project(repository, auth)
    first = create_configuration(repository, auth, project.id, valid_configuration())
    activate_configuration(repository, auth, project.id, first.id, "activate-stale-v1")
    old_authority = repository.opening_stock_authority(auth, project.id, date(2026, 7, 18))
    stale_request = OpeningStockCreate(
        expected_configuration_snapshot_id=old_authority.configuration_snapshot_id,
        posting_date="2026-07-18",
        lines=[
            OpeningStockLineCreate(
                product_definition_id=old_authority.products[0].product_definition_id,
                entered_quantity="4",
                entered_unit_code="package",
            )
        ],
    )
    second = create_configuration(
        repository, auth, project.id, ConfigurationCreate(copy_active=True), "stale-v2"
    )
    copied_product = repository.list_products(auth, project.id, second.id)[0]
    copied_price = copied_product.prices[0]
    changed = repository.patch_product_price(
        auth,
        copied_price.id,
        ProductPricePatch(
            expected_configuration_version=second.row_version,
            effective_from=copied_price.effective_from,
            effective_to=copied_price.effective_to,
            unit_price="24",
            currency="GBP",
            price_basis_unit_code="package",
        ),
    )
    readiness = repository.validate_configuration(auth, project.id, second.id)
    repository.activate_configuration(
        auth,
        project.id,
        second.id,
        "activate-stale-v2",
        changed.configuration_row_version,
        readiness.draft_checksum,
    )
    audit_before = len(repository.audit_events(auth, project.id))
    with pytest.raises(HTTPException) as stale:
        repository.post_opening_stock(auth, project.id, stale_request, "stale-reviewed-opening")
    assert stale.value.status_code == 412
    assert stale.value.detail["code"] == "INVENTORY_AUTHORITY_CHANGED"
    assert repository.list_inventory_postings(auth, project.id) == []
    assert len(repository.audit_events(auth, project.id)) == audit_before
    admin = create_engine(os.environ["VANTIX_ADMIN_DATABASE_URL"])
    with pytest.raises(DBAPIError), admin.begin() as connection:
        connection.execute(
            insert(InventoryPosting).values(
                id=uuid4(),
                organisation_id=auth.organisation_id,
                project_id=project.id,
                source_configuration_snapshot_id=old_authority.configuration_snapshot_id,
                posting_type="opening_stock",
                status="building",
                posting_date=date(2026, 7, 18),
                reversal_of_posting_id=None,
                reason=None,
                posted_by=auth.user_id,
            )
        )
    with admin.connect() as connection:
        assert (
            connection.scalar(
                select(func.count())
                .select_from(IdempotencyRecord)
                .where(IdempotencyRecord.operation_type == "post_opening_stock")
            )
            == 0
        )
    admin.dispose()


def test_vtx_pro_005_concurrent_opening_occupancy_is_per_product_lineage() -> None:
    repository = PostgresFoundationRepository()
    auth = context()
    project = prepare_project(repository, auth)
    configuration = create_configuration(repository, auth, project.id, valid_configuration())
    barite = repository.create_product(
        auth,
        project.id,
        ProjectProductCreate(
            configuration_version_id=configuration.id,
            expected_configuration_version=configuration.row_version,
            item_code="BAR-001",
            item_name="Barite",
            packaging="sack",
            package_size="25",
            package_unit_code="kg",
            inventory_applicable=True,
            inventory_unit_code="package",
            specific_gravity="4.2",
        ),
    )
    barite = repository.create_product_price(
        auth,
        barite.id,
        ProductPriceCreate(
            expected_configuration_version=barite.configuration_row_version,
            effective_from="2026-01-01",
            unit_price="18.50",
            currency="GBP",
            price_basis_unit_code="package",
        ),
    )
    bentonite = repository.create_product(
        auth,
        project.id,
        ProjectProductCreate(
            configuration_version_id=configuration.id,
            expected_configuration_version=barite.configuration_row_version,
            item_code="BEN-001",
            item_name="Bentonite",
            packaging="sack",
            package_size="25",
            package_unit_code="kg",
            inventory_applicable=True,
            inventory_unit_code="package",
            specific_gravity="2.6",
        ),
    )
    repository.create_product_price(
        auth,
        bentonite.id,
        ProductPriceCreate(
            expected_configuration_version=bentonite.configuration_row_version,
            effective_from="2026-01-01",
            unit_price="22.00",
            currency="GBP",
            price_basis_unit_code="package",
        ),
    )
    active = activate_configuration(
        repository, auth, project.id, configuration.id, "activate-two-products"
    )
    assert active.snapshot_id is not None
    authority = repository.opening_stock_authority(auth, project.id, date(2026, 7, 18))
    definitions = {
        product.item_code: product.product_definition_id for product in authority.products
    }

    def post(definition_id: UUID, key: str) -> InventoryPostingView | str:
        try:
            return repository.post_opening_stock(
                auth,
                project.id,
                OpeningStockCreate(
                    expected_configuration_snapshot_id=active.snapshot_id,
                    posting_date="2026-07-18",
                    lines=[
                        OpeningStockLineCreate(
                            product_definition_id=definition_id,
                            entered_quantity="1",
                            entered_unit_code="package",
                        )
                    ],
                ),
                key,
            )
        except HTTPException as exc:
            return str(exc.detail["code"])

    with ThreadPoolExecutor(max_workers=2) as executor:
        disjoint = list(
            executor.map(
                lambda args: post(*args),
                [
                    (definitions["BAR-001"], "open-barite"),
                    (definitions["BEN-001"], "open-bentonite"),
                ],
            )
        )
    assert all(not isinstance(result, str) for result in disjoint)
    for index, result in enumerate(disjoint):
        assert not isinstance(result, str)
        repository.reverse_inventory_posting(
            auth,
            project.id,
            result.id,
            InventoryReversalCreate(posting_date="2026-07-19", reason="Reset concurrency fixture"),
            f"reverse-disjoint-{index}",
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        duplicate = list(
            executor.map(
                lambda key: post(definitions["BAR-001"], key),
                ["same-lineage-a", "same-lineage-b"],
            )
        )
    assert sum(not isinstance(result, str) for result in duplicate) == 1
    assert duplicate.count("OPENING_STOCK_PRODUCT_ALREADY_POSTED") == 1
    refreshed = repository.opening_stock_authority(auth, project.id, date(2026, 7, 18))
    opened = {product.item_code: product.opened_by_posting_id for product in refreshed.products}
    assert opened["BAR-001"] is not None
    assert opened["BEN-001"] is None


def test_vtx_cst_001_four_decimal_currency_survives_posting_and_reversal_exactly() -> None:
    repository = PostgresFoundationRepository()
    auth = context()
    repository.create_organisation(auth, OrganisationCreate(name="Four Decimal Org"))
    project = repository.create_project(
        auth,
        ProjectCreate(
            project_code="CLF-01",
            project_name="Four Decimal Project",
            well_name="Well-CLF",
            time_zone="America/Santiago",
            currency="CLF",
            unit_set="Metric",
        ),
        auth.organisation_id,
    )
    configuration = create_configuration(repository, auth, project.id, valid_configuration())
    product = repository.create_product(
        auth,
        project.id,
        ProjectProductCreate(
            configuration_version_id=configuration.id,
            expected_configuration_version=configuration.row_version,
            item_code="EA-001",
            item_name="Counted additive",
            packaging="each",
            package_size="1",
            package_unit_code="each",
            inventory_applicable=True,
            inventory_unit_code="each",
        ),
    )
    repository.create_product_price(
        auth,
        product.id,
        ProductPriceCreate(
            expected_configuration_version=product.configuration_row_version,
            effective_from="2026-01-01",
            unit_price="1.2345",
            currency="CLF",
            price_basis_unit_code="each",
        ),
    )
    active = activate_configuration(
        repository, auth, project.id, configuration.id, "activate-four-decimal"
    )
    assert active.snapshot_id is not None
    authority = repository.opening_stock_authority(auth, project.id, date(2026, 7, 18))
    request = OpeningStockCreate(
        expected_configuration_snapshot_id=active.snapshot_id,
        posting_date="2026-07-18",
        lines=[
            OpeningStockLineCreate(
                product_definition_id=authority.products[0].product_definition_id,
                entered_quantity="3",
                entered_unit_code="each",
            )
        ],
    )
    preview = repository.preview_opening_stock(auth, project.id, request)
    assert preview.lines[0].line_amount == "3.7035"
    assert preview.currencies == {"CLF": "3.7035"}
    posted = repository.post_opening_stock(auth, project.id, request, "four-decimal-open")
    assert posted.lines[0].currency_minor_unit_scale == 4
    assert posted.lines[0].posted_line_amount == "3.7035"
    reversed_posting = repository.reverse_inventory_posting(
        auth,
        project.id,
        posted.id,
        InventoryReversalCreate(posting_date="2026-07-19", reason="Four-decimal test"),
        "four-decimal-reverse",
    )
    assert reversed_posting.lines[0].currency_minor_unit_scale == 4
    assert reversed_posting.lines[0].posted_line_amount == "-3.7035"


def test_vtx_unit_002_high_precision_conversion_matches_preview_and_posted_ledger() -> None:
    repository = PostgresFoundationRepository()
    auth = context()
    project = prepare_project(repository, auth)
    configuration = create_configuration(repository, auth, project.id, valid_configuration())
    active = activate_configuration(
        repository, auth, project.id, configuration.id, "activate-precision"
    )
    assert active.snapshot_id is not None
    authority = repository.opening_stock_authority(auth, project.id, date(2026, 7, 18))
    request = OpeningStockCreate(
        expected_configuration_snapshot_id=active.snapshot_id,
        posting_date="2026-07-18",
        lines=[
            OpeningStockLineCreate(
                product_definition_id=authority.products[0].product_definition_id,
                entered_quantity="1.000000000001",
                entered_unit_code="lb",
            )
        ],
    )

    preview = repository.preview_opening_stock(auth, project.id, request)
    posted = repository.post_opening_stock(auth, project.id, request, "precision-opening")

    assert preview.lines[0].entered_quantity == "1.000000000001"
    assert preview.lines[0].canonical_quantity == "0.45359237"
    assert posted.lines[0].canonical_signed_quantity == preview.lines[0].canonical_quantity


def test_vtx_pro_004_database_rejects_forged_frozen_opening_authority() -> None:
    repository = PostgresFoundationRepository()
    auth = context()
    project = prepare_project(repository, auth)
    first = create_configuration(repository, auth, project.id, valid_configuration())
    active = activate_configuration(repository, auth, project.id, first.id, "activate-forgery-v1")
    assert active.snapshot_id is not None
    v1_product = repository.list_products(auth, project.id, first.id)[0]
    v1_price = v1_product.prices[0]
    second = create_configuration(
        repository, auth, project.id, ConfigurationCreate(copy_active=True), "forgery-v2"
    )
    v2_product = repository.list_products(auth, project.id, second.id)[0]
    v2_price = v2_product.prices[0]
    frozen_product = {
        "item_code": v1_product.item_code,
        "item_name": v1_product.item_name,
        "alternate_name": v1_product.alternate_name,
        "packaging": v1_product.packaging,
        "package_size": v1_product.package_size,
        "package_unit_code": v1_product.package_unit_code,
        "inventory_unit_code": v1_product.inventory_unit_code,
        "specific_gravity": v1_product.specific_gravity,
    }
    base_line: dict[str, Any] = {
        "organisation_id": auth.organisation_id,
        "project_id": project.id,
        "product_definition_id": v1_product.product_definition_id,
        "configuration_product_version_id": v1_product.id,
        "product_price_version_id": v1_price.id,
        "entered_quantity": Decimal("4"),
        "entered_unit_code": "package",
        "canonical_signed_quantity": Decimal("100"),
        "canonical_unit_code": "kg",
        "price_status": "ready",
        "applied_unit_price": Decimal("18.5"),
        "price_basis_unit_code": "package",
        "price_effective_from": date(2026, 1, 1),
        "price_effective_to": None,
        "currency": "GBP",
        "currency_minor_unit_scale": 2,
        "posted_line_amount": Decimal("74.00"),
        "frozen_product_json": frozen_product,
    }
    admin = create_engine(os.environ["VANTIX_ADMIN_DATABASE_URL"])
    other_project = repository.create_project(
        auth,
        ProjectCreate(
            project_code="FORGE-02",
            project_name="Other project",
            well_name="Other well",
            time_zone="Europe/London",
            currency="GBP",
            unit_set="Metric",
        ),
        auth.organisation_id,
    )
    with pytest.raises(DBAPIError), admin.begin() as connection:
        connection.execute(
            insert(InventoryPosting).values(
                id=uuid4(),
                organisation_id=auth.organisation_id,
                project_id=other_project.id,
                source_configuration_snapshot_id=active.snapshot_id,
                posting_type="opening_stock",
                status="building",
                posting_date=date(2026, 7, 18),
                reversal_of_posting_id=None,
                reason=None,
                posted_by=auth.user_id,
            )
        )

    def assert_rejected(**overrides: Any) -> None:
        posting_id = uuid4()
        line_values = {**base_line, **overrides, "id": uuid4(), "posting_id": posting_id}
        with pytest.raises(DBAPIError), admin.begin() as connection:
            connection.execute(
                insert(InventoryPosting).values(
                    id=posting_id,
                    organisation_id=auth.organisation_id,
                    project_id=project.id,
                    source_configuration_snapshot_id=active.snapshot_id,
                    posting_type="opening_stock",
                    status="building",
                    posting_date=date(2026, 7, 18),
                    reversal_of_posting_id=None,
                    reason=None,
                    posted_by=auth.user_id,
                )
            )
            connection.execute(insert(InventoryLedgerLine).values(**line_values))

    assert_rejected(
        configuration_product_version_id=v2_product.id,
        product_price_version_id=v2_price.id,
    )
    assert_rejected(product_price_version_id=v2_price.id)
    assert_rejected(frozen_product_json={**frozen_product, "package_size": "50"})
    assert_rejected(canonical_signed_quantity=Decimal("999"))
    assert_rejected(posted_line_amount=Decimal("999.00"))
    admin.dispose()


def test_vtx_mvp_001_clean_migration_upgrade_downgrade_cycle() -> None:
    admin_url = make_url(os.environ["VANTIX_ADMIN_DATABASE_URL"])
    probe_name = f"vantix_migration_{uuid4().hex}"
    server_url = admin_url.set(database="postgres")
    server = create_engine(server_url, isolation_level="AUTOCOMMIT")
    with server.connect() as connection:
        connection.exec_driver_sql(f'CREATE DATABASE "{probe_name}"')

    probe_url = admin_url.set(database=probe_name)
    migration_environment = {**os.environ, "VANTIX_DATABASE_URL": probe_url.render_as_string(False)}

    def migrate(*arguments: str) -> None:
        subprocess.run(
            [sys.executable, "-m", "alembic", *arguments],
            check=True,
            cwd=os.getcwd(),
            env=migration_environment,
            capture_output=True,
            text=True,
        )

    try:
        migrate("upgrade", "head")
        migrate("downgrade", "0001_foundation")
        probe = create_engine(probe_url)
        with probe.connect() as connection:
            restored = connection.scalar(
                text(
                    """
                    SELECT count(*) FROM pg_policies
                    WHERE policyname IN (
                      'projects_select_project_scope',
                      'projects_update_project_scope',
                      'projects_delete_project_scope',
                      'project_memberships_project_scope'
                    )
                    """
                )
            )
            assert restored == 4
        probe.dispose()
        migrate("upgrade", "head")
        migrate("downgrade", "base")
        probe = create_engine(probe_url)
        with probe.connect() as connection:
            residue = connection.scalar(
                text(
                    """
                    SELECT
                      (SELECT count(*) FROM pg_tables
                       WHERE schemaname = 'public' AND tablename <> 'alembic_version')
                      +
                      (SELECT count(*) FROM pg_proc
                       WHERE proname IN (
                         'vantix_guard_revision_mutation',
                         'vantix_guard_configuration_mutation',
                         'vantix_guard_product_configuration',
                         'vantix_guard_product_price',
                         'vantix_enforce_same_project_ownership',
                         'vantix_guard_snapshot_binding',
                         'vantix_reject_mutation'
                       ))
                    """
                )
            )
            assert residue == 0
        probe.dispose()
        migrate("upgrade", "head")
    finally:
        with server.connect() as connection:
            connection.exec_driver_sql(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (probe_name,),
            )
            connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{probe_name}"')
        server.dispose()
