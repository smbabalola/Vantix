from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from uuid import UUID, uuid4

import pytest
from app.auth import AuthContext, Capability
from app.db import SessionFactory, set_tenant_context
from app.models import (
    AuditEvent,
    DailyReportRevision,
    Project,
    ReportPayload,
)
from app.postgres_repository import PostgresFoundationRepository
from app.schemas import (
    ConfigurationCreate,
    DailyReportCreate,
    DecisionRequest,
    DraftPatch,
    ExportRequest,
    OrganisationCreate,
    ProjectCreate,
)
from fastapi import HTTPException
from sqlalchemy import create_engine, select, text, update
from sqlalchemy.exc import DBAPIError

ALL_CAPABILITIES = frozenset(Capability)


def context(user_id: UUID | None = None, organisation_id: UUID | None = None) -> AuthContext:
    return AuthContext(user_id or uuid4(), organisation_id or uuid4(), ALL_CAPABILITIES)


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
                "caps": __import__("json").dumps(capabilities),
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
        ConfigurationCreate(
            data={"project": {"name": "North Sea A"}, "unit_set": {"name": "Field"}}
        ),
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
        capabilities=[Capability.APPROVE_REPORT.value],
    )
    approved = repository.approve_report(
        approver,
        submitted.revision.id,
        DecisionRequest(expected_checksum=submitted.revision.checksum or ""),
    )
    client = add_project_member(editor, project.id, role="client_viewer", capabilities=[])
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
        capabilities=[Capability.APPROVE_REPORT.value, Capability.EXPORT_REPORT.value],
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


def test_vtx_mvp_001_live_migration_head_and_force_rls_are_active() -> None:
    engine = create_engine(os.environ["VANTIX_ADMIN_DATABASE_URL"])
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
            "0003_project_membership_roles"
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
