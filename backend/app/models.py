from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class TenantMixin:
    organisation_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)


class Organisation(Base):
    __tablename__ = "organisations"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class User(Base):
    __tablename__ = "users"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    external_subject: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active")


class OrganisationMembership(Base):
    __tablename__ = "organisation_memberships"
    organisation_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id"), primary_key=True
    )
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active")


class Project(TenantMixin, Base):
    __tablename__ = "projects"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    project_code: Mapped[str] = mapped_column(String(50), nullable=False)
    project_name: Mapped[str] = mapped_column(String(200), nullable=False)
    well_name: Mapped[str] = mapped_column(String(200), nullable=False)
    time_zone: Mapped[str] = mapped_column(String(100), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    unit_set: Mapped[str] = mapped_column(String(100), nullable=False)
    current_configuration_snapshot_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    __table_args__ = (UniqueConstraint("organisation_id", "project_code"),)


class ProjectMembership(TenantMixin, Base):
    __tablename__ = "project_memberships"
    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id"), primary_key=True
    )
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), primary_key=True
    )
    capabilities: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)


class ConfigurationVersion(TenantMixin, Base):
    __tablename__ = "project_configuration_versions"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(30), nullable=False, default="draft")
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    __table_args__ = (UniqueConstraint("project_id", "version_number"),)


class ConfigurationSnapshot(TenantMixin, Base):
    __tablename__ = "project_configuration_snapshots"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    configuration_version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("project_configuration_versions.id"), nullable=False
    )
    schema_version: Mapped[str] = mapped_column(String(30), nullable=False)
    snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    canonical_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DailyReport(TenantMixin, Base):
    __tablename__ = "daily_reports"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    report_date: Mapped[date] = mapped_column(Date, nullable=False)
    shift_code: Mapped[str] = mapped_column(String(30), nullable=False, default="")
    report_number: Mapped[str] = mapped_column(String(100), nullable=False)
    active_configuration_snapshot_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("project_configuration_snapshots.id"), nullable=False
    )
    aggregate_state: Mapped[str] = mapped_column(String(30), nullable=False, default="draft")
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    __table_args__ = (UniqueConstraint("project_id", "report_date", "shift_code"),)


class DailyReportRevision(TenantMixin, Base):
    __tablename__ = "daily_report_revisions"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    daily_report_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("daily_reports.id"), nullable=False
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    revision_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    state: Mapped[str] = mapped_column(String(30), nullable=False)
    based_on_revision_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    configuration_snapshot_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("project_configuration_snapshots.id"), nullable=False
    )
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    submitted_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    approved_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (UniqueConstraint("daily_report_id", "revision_number"),)


class ReportPayload(TenantMixin, Base):
    __tablename__ = "report_payload_versions"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    daily_report_revision_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("daily_report_revisions.id"), unique=True, nullable=False
    )
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    payload_schema_version: Mapped[str] = mapped_column(String(30), nullable=False)
    payload_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    template_key: Mapped[str] = mapped_column(String(100), nullable=False)
    template_version: Mapped[str] = mapped_column(String(30), nullable=False)


class ReportDecision(TenantMixin, Base):
    __tablename__ = "report_decisions"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    daily_report_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("daily_reports.id"), nullable=False
    )
    daily_report_revision_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("daily_report_revisions.id"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    actor_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    acted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    reason: Mapped[str | None] = mapped_column(Text)
    expected_payload_checksum: Mapped[str | None] = mapped_column(String(64))
    from_state: Mapped[str | None] = mapped_column(String(30))
    to_state: Mapped[str] = mapped_column(String(30), nullable=False)


class ReportExport(TenantMixin, Base):
    __tablename__ = "report_exports"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    payload_version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("report_payload_versions.id"), nullable=False
    )
    export_type: Mapped[str] = mapped_column(String(10), nullable=False)
    visibility: Mapped[str] = mapped_column(String(20), nullable=False)
    export_kind: Mapped[str] = mapped_column(String(20), nullable=False, default="original")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="queued")
    binary_checksum: Mapped[str | None] = mapped_column(String(64))
    template_version: Mapped[str] = mapped_column(String(30), nullable=False)
    renderer_version: Mapped[str] = mapped_column(String(100), nullable=False)


class AuditEvent(TenantMixin, Base):
    __tablename__ = "audit_events"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("projects.id"))
    actor_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    correlation_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    before_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    after_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    reason: Mapped[str | None] = mapped_column(Text)


class IdempotencyRecord(TenantMixin, Base):
    __tablename__ = "idempotency_records"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    operation_type: Mapped[str] = mapped_column(String(100), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    response_status: Mapped[int] = mapped_column(Integer, nullable=False)
    response_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    __table_args__ = (UniqueConstraint("organisation_id", "operation_type", "idempotency_key"),)
