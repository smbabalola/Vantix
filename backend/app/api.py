from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict
from typing import Any, cast
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, status
from vantix_core.lifecycle import (
    ConfigurationSnapshot,
    DailyReport,
    LifecycleError,
    ReportRevision,
)

from .auth import AuthContext, Capability, auth_context
from .config import get_settings
from .postgres_repository import PostgresFoundationRepository, postgres_repository
from .renderers import render_report
from .schemas import (
    ConfigurationCreate,
    ConfigurationView,
    DailyReportCreate,
    DecisionRequest,
    DraftPatch,
    ExportRequest,
    ExportView,
    OrganisationCreate,
    OrganisationView,
    ProjectCreate,
    ProjectView,
    ReadinessView,
    ReportView,
    RevisionView,
)
from .store import ExportRecord, FoundationStore, IdempotencyConflict, ProjectRecord, store

router = APIRouter(prefix="/api/v1")
Repository = FoundationStore | PostgresFoundationRepository


def get_store() -> Repository:
    if get_settings().repository_backend == "postgres":
        return postgres_repository
    return store


def _project(project_id: UUID, auth: AuthContext, repository: FoundationStore) -> ProjectRecord:
    project = repository.projects.get(project_id)
    if not project or project.organisation_id != auth.organisation_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "PROJECT_NOT_FOUND"})
    return project


def _report(report_id: UUID, auth: AuthContext, repository: FoundationStore) -> DailyReport:
    report = repository.reports.get(report_id)
    if not report or report.organisation_id != auth.organisation_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "REPORT_NOT_FOUND"})
    return report


def _report_for_revision(
    revision_id: UUID, auth: AuthContext, repository: FoundationStore
) -> DailyReport:
    report = next(
        (
            candidate
            for candidate in repository.reports.values()
            if any(revision.id == revision_id for revision in candidate.revisions)
        ),
        None,
    )
    if not report or report.organisation_id != auth.organisation_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "REVISION_NOT_FOUND"})
    return report


def _revision_view(revision: ReportRevision) -> RevisionView:
    return RevisionView(
        id=revision.id,
        number=revision.number,
        kind=revision.kind.value,
        state=revision.state.value,
        version=revision.version,
        data=revision.data,
        checksum=revision.checksum,
        based_on_revision_id=revision.based_on_revision_id,
    )


def _report_view(report: DailyReport) -> ReportView:
    return ReportView(
        id=report.id,
        project_id=report.project_id,
        report_date=report.report_date,
        report_number=report.report_number,
        revision=_revision_view(report.current_revision),
    )


def _domain_call[**P, R](function: Callable[P, R], *args: P.args, **kwargs: P.kwargs) -> R:
    try:
        return function(*args, **kwargs)
    except LifecycleError as exc:
        code_map = {
            "REPORT_VERSION_CONFLICT": status.HTTP_412_PRECONDITION_FAILED,
            "REPORT_REVISION_LOCKED": status.HTTP_423_LOCKED,
            "SELF_APPROVAL_DENIED": status.HTTP_403_FORBIDDEN,
            "REPORT_NOT_READY": status.HTTP_422_UNPROCESSABLE_ENTITY,
        }
        raise HTTPException(
            code_map.get(exc.code, status.HTTP_409_CONFLICT),
            detail={"code": exc.code, "message": str(exc)},
        ) from exc


def _request_hash(value: dict[str, Any]) -> str:
    serialised = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialised.encode("utf-8")).hexdigest()


def _idempotent[R](
    repository: FoundationStore,
    auth: AuthContext,
    operation_type: str,
    idempotency_key: str,
    request: dict[str, Any],
    operation: Callable[[], R],
) -> R:
    try:
        return repository.idempotent(
            organisation_id=auth.organisation_id,
            operation_type=operation_type,
            idempotency_key=idempotency_key,
            request_hash=_request_hash(request),
            operation=operation,
        )
    except IdempotencyConflict as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={
                "code": "IDEMPOTENCY_KEY_REUSED",
                "message": "Key reused with a different request.",
            },
        ) from exc


@router.post("/organisations", response_model=OrganisationView, status_code=201)
def create_organisation(
    body: OrganisationCreate,
    auth: AuthContext = Depends(auth_context),
    repository: Repository = Depends(get_store),
) -> OrganisationView:
    auth.require(Capability.CREATE_PROJECT)
    if isinstance(repository, PostgresFoundationRepository):
        return repository.create_organisation(auth, body)
    record = repository.create_organisation(body.name)
    return OrganisationView(id=record.id, name=record.name)


@router.post(
    "/organisations/{organisation_id}/projects", response_model=ProjectView, status_code=201
)
def create_project(
    organisation_id: UUID,
    body: ProjectCreate,
    auth: AuthContext = Depends(auth_context),
    repository: Repository = Depends(get_store),
) -> ProjectView:
    if isinstance(repository, PostgresFoundationRepository):
        return repository.create_project(auth, body, organisation_id)
    auth.require(Capability.CREATE_PROJECT)
    if organisation_id != auth.organisation_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "ORGANISATION_NOT_FOUND"})
    record = repository.create_project(organisation_id, **body.model_dump())
    return ProjectView(**body.model_dump(), id=record.id, organisation_id=record.organisation_id)


@router.post(
    "/projects/{project_id}/configuration-versions",
    response_model=ConfigurationView,
    status_code=201,
)
def create_configuration(
    project_id: UUID,
    body: ConfigurationCreate,
    auth: AuthContext = Depends(auth_context),
    repository: Repository = Depends(get_store),
) -> ConfigurationView:
    if isinstance(repository, PostgresFoundationRepository):
        return repository.create_configuration(auth, project_id, body)
    auth.require(Capability.CONFIGURE_PROJECT)
    project = _project(project_id, auth, repository)
    version = len(project.configuration_versions) + 1
    record = {"id": uuid4(), "version": version, "state": "draft", "data": body.data}
    project.configuration_versions.append(record)
    return ConfigurationView(
        id=cast(UUID, record["id"]),
        project_id=project.id,
        version=cast(int, record["version"]),
        state=cast(Any, record["state"]),
        data=cast(dict[str, Any], record["data"]),
    )


@router.post(
    "/projects/{project_id}/configuration-versions/{version_id}/activate",
    response_model=ConfigurationView,
)
def activate_configuration(
    project_id: UUID,
    version_id: UUID,
    auth: AuthContext = Depends(auth_context),
    repository: Repository = Depends(get_store),
    idempotency_key: str = Header(alias="Idempotency-Key"),
) -> ConfigurationView:
    if isinstance(repository, PostgresFoundationRepository):
        return repository.activate_configuration(auth, project_id, version_id, idempotency_key)
    auth.require(Capability.CONFIGURE_PROJECT)
    project = _project(project_id, auth, repository)
    record = next(
        (item for item in project.configuration_versions if item["id"] == version_id), None
    )
    if not record:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "CONFIGURATION_NOT_FOUND"})

    def activate() -> ConfigurationView:
        snapshot = ConfigurationSnapshot.create(
            project.id,
            cast(int, record["version"]),
            cast(dict[str, Any], record["data"]),
        )
        project.active_snapshot = snapshot
        record["state"] = "active"
        return ConfigurationView(
            id=cast(UUID, record["id"]),
            project_id=project.id,
            version=cast(int, record["version"]),
            state=cast(Any, record["state"]),
            data=cast(dict[str, Any], record["data"]),
            snapshot_id=snapshot.id,
            checksum=snapshot.checksum,
        )

    return _idempotent(
        repository,
        auth,
        "activate_configuration",
        idempotency_key,
        {"project_id": str(project_id), "version_id": str(version_id)},
        activate,
    )


@router.post("/projects/{project_id}/daily-reports", response_model=ReportView, status_code=201)
def create_daily_report(
    project_id: UUID,
    body: DailyReportCreate,
    auth: AuthContext = Depends(auth_context),
    repository: Repository = Depends(get_store),
    idempotency_key: str = Header(alias="Idempotency-Key"),
) -> ReportView:
    if isinstance(repository, PostgresFoundationRepository):
        return repository.create_daily_report(auth, project_id, body, idempotency_key)
    auth.require(Capability.EDIT_REPORT)
    project = _project(project_id, auth, repository)
    if not project.active_snapshot:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail={"code": "ACTIVE_CONFIGURATION_REQUIRED"}
        )

    def create() -> ReportView:
        if any(
            report.project_id == project_id and report.report_date == body.report_date.isoformat()
            for report in repository.reports.values()
        ):
            raise HTTPException(status.HTTP_409_CONFLICT, detail={"code": "REPORT_DATE_CONFLICT"})
        assert project.active_snapshot is not None
        report = DailyReport.create(
            organisation_id=auth.organisation_id,
            project_id=project_id,
            report_date=body.report_date.isoformat(),
            report_number=body.report_number,
            configuration_snapshot=project.active_snapshot,
            actor_id=auth.user_id,
        )
        repository.reports[report.id] = report
        return _report_view(report)

    return _idempotent(
        repository,
        auth,
        "create_daily_report",
        idempotency_key,
        {"project_id": str(project_id), **body.model_dump(mode="json")},
        create,
    )


@router.patch(
    "/daily-report-revisions/{revision_id}/sections/{section_key}", response_model=ReportView
)
def patch_section(
    revision_id: UUID,
    section_key: str,
    body: DraftPatch,
    auth: AuthContext = Depends(auth_context),
    repository: Repository = Depends(get_store),
) -> ReportView:
    if isinstance(repository, PostgresFoundationRepository):
        return repository.patch_section(auth, revision_id, section_key, body)
    auth.require(Capability.EDIT_REPORT)
    report = _report_for_revision(revision_id, auth, repository)
    if report.current_revision.id != revision_id:
        raise HTTPException(status.HTTP_423_LOCKED, detail={"code": "REPORT_REVISION_LOCKED"})
    _domain_call(
        report.edit,
        {section_key: body.data},
        expected_version=body.expected_version,
        actor_id=auth.user_id,
    )
    return _report_view(report)


@router.post("/daily-report-revisions/{revision_id}/validate", response_model=ReadinessView)
def validate_report(
    revision_id: UUID,
    auth: AuthContext = Depends(auth_context),
    repository: Repository = Depends(get_store),
) -> ReadinessView:
    if isinstance(repository, PostgresFoundationRepository):
        return repository.validate_report(auth, revision_id)
    auth.require(Capability.VIEW_DRAFT_REPORT)
    report = _report_for_revision(revision_id, auth, repository)
    result = report.current_revision.readiness()
    return ReadinessView(
        state=result.state,
        can_submit=result.can_submit,
        issues=[asdict(issue) for issue in result.issues],
    )


@router.post("/daily-report-revisions/{revision_id}/submit", response_model=ReportView)
def submit_report(
    revision_id: UUID,
    auth: AuthContext = Depends(auth_context),
    repository: Repository = Depends(get_store),
    if_match: str = Header(alias="If-Match"),
    idempotency_key: str = Header(alias="Idempotency-Key"),
) -> ReportView:
    try:
        version = int(if_match.strip('"'))
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail={"code": "INVALID_IF_MATCH"}
        ) from exc
    if isinstance(repository, PostgresFoundationRepository):
        return repository.submit_report(auth, revision_id, version, idempotency_key)
    auth.require(Capability.SUBMIT_REPORT)
    report = _report_for_revision(revision_id, auth, repository)

    def submit() -> ReportView:
        _domain_call(report.submit, expected_version=version, actor_id=auth.user_id)
        return _report_view(report)

    return _idempotent(
        repository,
        auth,
        "submit_report",
        idempotency_key,
        {"revision_id": str(revision_id), "expected_version": version},
        submit,
    )


@router.post("/daily-report-revisions/{revision_id}/reject", response_model=ReportView)
def reject_report(
    revision_id: UUID,
    body: DecisionRequest,
    auth: AuthContext = Depends(auth_context),
    repository: Repository = Depends(get_store),
) -> ReportView:
    if isinstance(repository, PostgresFoundationRepository):
        return repository.reject_report(auth, revision_id, body)
    auth.require(Capability.REJECT_REPORT)
    report = _report_for_revision(revision_id, auth, repository)
    _domain_call(
        report.reject,
        submitted_revision_id=revision_id,
        expected_checksum=body.expected_checksum,
        actor_id=auth.user_id,
        reason=body.reason or "",
    )
    return _report_view(report)


@router.post("/daily-report-revisions/{revision_id}/approve", response_model=ReportView)
def approve_report(
    revision_id: UUID,
    body: DecisionRequest,
    auth: AuthContext = Depends(auth_context),
    repository: Repository = Depends(get_store),
) -> ReportView:
    if isinstance(repository, PostgresFoundationRepository):
        return repository.approve_report(auth, revision_id, body)
    auth.require(Capability.APPROVE_REPORT)
    report = _report_for_revision(revision_id, auth, repository)
    _domain_call(
        report.approve,
        submitted_revision_id=revision_id,
        expected_checksum=body.expected_checksum,
        actor_id=auth.user_id,
    )
    return _report_view(report)


@router.get("/projects/{project_id}/audit-events")
def audit_events(
    project_id: UUID,
    auth: AuthContext = Depends(auth_context),
    repository: Repository = Depends(get_store),
) -> list[dict[str, Any]]:
    if isinstance(repository, PostgresFoundationRepository):
        return repository.audit_events(auth, project_id)
    auth.require(Capability.VIEW_AUDIT)
    _project(project_id, auth, repository)
    return [
        asdict(event)
        for report in repository.reports.values()
        if report.project_id == project_id
        for event in report.audit_events
    ]


@router.get("/daily-reports/{report_id}", response_model=ReportView)
def get_daily_report(
    report_id: UUID,
    auth: AuthContext = Depends(auth_context),
    repository: Repository = Depends(get_store),
) -> ReportView:
    if isinstance(repository, PostgresFoundationRepository):
        return repository.get_report(auth, report_id)
    auth.require(Capability.VIEW_CLIENT_REPORT)
    return _report_view(_report(report_id, auth, repository))


@router.post(
    "/daily-report-revisions/{revision_id}/exports", response_model=ExportView, status_code=202
)
def create_export(
    revision_id: UUID,
    body: ExportRequest,
    auth: AuthContext = Depends(auth_context),
    repository: Repository = Depends(get_store),
    idempotency_key: str = Header(alias="Idempotency-Key"),
) -> ExportView:
    if isinstance(repository, PostgresFoundationRepository):
        return repository.create_export(auth, revision_id, body, idempotency_key)
    auth.require(Capability.EXPORT_REPORT)
    report = _report_for_revision(revision_id, auth, repository)
    revision = report.current_revision
    if revision.state.value != "approved" or not revision.checksum:
        raise HTTPException(status.HTTP_423_LOCKED, detail={"code": "APPROVED_REVISION_REQUIRED"})
    if revision.payload is None:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "FROZEN_PAYLOAD_MISSING"},
        )

    def generate() -> ExportView:
        assert revision.payload is not None and revision.checksum is not None
        artefact = render_report(body.format, revision.payload, revision.checksum)
        record = ExportRecord(
            uuid4(),
            revision.id,
            body.format,
            body.visibility,
            "completed",
            revision.checksum,
            artefact.binary_checksum,
            artefact.template_version,
            artefact.renderer_version,
            artefact.content,
        )
        repository.exports[record.id] = record
        visible = {key: value for key, value in asdict(record).items() if key != "content"}
        return ExportView(**visible)

    return _idempotent(
        repository,
        auth,
        "create_export",
        idempotency_key,
        {"revision_id": str(revision.id), **body.model_dump()},
        generate,
    )
