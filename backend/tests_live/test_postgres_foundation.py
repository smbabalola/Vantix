from __future__ import annotations

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
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
    Project,
    ReportPayload,
)
from app.postgres_repository import PostgresFoundationRepository
from app.schemas import (
    ConfigurationCreate,
    ConfigurationPatch,
    DailyReportCreate,
    DecisionRequest,
    DraftPatch,
    ExportRequest,
    OrganisationCreate,
    ProjectCreate,
)
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text, update
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
    configuration = repository.create_configuration(
        auth,
        project.id,
        valid_configuration(),
    )
    repository.activate_configuration(auth, project.id, configuration.id, "activate-foundation")
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
    configuration = repository.create_configuration(
        auth, project.id, ConfigurationCreate(copy_active=False)
    )

    readiness = repository.validate_configuration(auth, project.id, configuration.id)
    assert readiness.can_activate is False
    assert {issue["code"] for issue in readiness.issues} == {
        "DEFAULT_INTERVAL_REQUIRED",
        "INTERVAL_REQUIRED",
    }
    with pytest.raises(HTTPException) as error:
        repository.activate_configuration(auth, project.id, configuration.id, "not-ready")
    assert error.value.status_code == 422

    engine = create_engine(os.environ["VANTIX_ADMIN_DATABASE_URL"])
    with engine.connect() as connection:
        assert connection.scalar(select(ConfigurationSnapshot.id)) is None
        stored_state = connection.scalar(
            select(ConfigurationVersion.state).where(ConfigurationVersion.id == configuration.id)
        )
        assert stored_state == "draft"
    engine.dispose()


def test_vtx_prj_003_004_activation_is_immutable_versioned_and_idempotent() -> None:
    repository = PostgresFoundationRepository()
    auth = context()
    project = prepare_project(repository, auth)
    first = repository.create_configuration(auth, project.id, valid_configuration("Surface"))
    active = repository.activate_configuration(auth, project.id, first.id, "activate-v1")
    retried = repository.activate_configuration(auth, project.id, first.id, "activate-v1")
    assert retried.snapshot_id == active.snapshot_id
    assert retried.checksum == active.checksum

    engine = create_engine(os.environ["VANTIX_ADMIN_DATABASE_URL"])
    with pytest.raises(DBAPIError), engine.begin() as connection:
        connection.execute(
            update(ConfigurationVersion)
            .where(ConfigurationVersion.id == first.id)
            .values(data={"intervals": []})
        )

    copied = repository.create_configuration(auth, project.id, ConfigurationCreate())
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
        repository.activate_configuration(auth, project.id, copied.id, "activate-v1")
    assert reused_key.value.status_code == 409

    second = repository.activate_configuration(auth, project.id, copied.id, "activate-v2")
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


def test_vtx_prj_005_report_revisions_retain_their_configuration_snapshot() -> None:
    repository = PostgresFoundationRepository()
    auth = context()
    project = prepare_project(repository, auth)
    first = repository.create_configuration(auth, project.id, valid_configuration("First"))
    active_first = repository.activate_configuration(auth, project.id, first.id, "first")
    report_one = repository.create_daily_report(
        auth,
        project.id,
        DailyReportCreate(report_date="2026-07-18", report_number="CFG-1"),
        "report-one",
    )

    second = repository.create_configuration(auth, project.id, ConfigurationCreate())
    active_second = repository.activate_configuration(auth, project.id, second.id, "second")
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
    repository.create_configuration(owner, project.id, valid_configuration())

    outsider = context()
    repository.create_organisation(outsider, OrganisationCreate(name="Other Org"))
    with pytest.raises(HTTPException) as error:
        repository.list_configurations(outsider, project.id)
    assert error.value.status_code == 404


def test_vtx_prj_001_organisation_admin_can_manage_all_organisation_projects() -> None:
    repository = PostgresFoundationRepository()
    owner = context()
    project = prepare_project(repository, owner)
    repository.create_configuration(owner, project.id, valid_configuration())
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
            "0005_project_config_lifecycle"
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
