from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class OrganisationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class OrganisationView(BaseModel):
    id: UUID
    name: str


class ProjectCreate(BaseModel):
    project_code: str = Field(min_length=1, max_length=50)
    project_name: str = Field(min_length=1, max_length=200)
    well_name: str = Field(min_length=1, max_length=200)
    operator_name: str | None = Field(default=None, max_length=200)
    client_name: str | None = Field(default=None, max_length=200)
    rig_name: str | None = Field(default=None, max_length=200)
    location_text: str | None = Field(default=None, max_length=500)
    time_zone: str
    currency: str = Field(min_length=3, max_length=3)
    unit_set: str
    reporting_start_date: date | None = None


class ProjectView(ProjectCreate):
    id: UUID
    organisation_id: UUID
    status: str = "draft"
    row_version: int = 1
    current_configuration_version_id: UUID | None = None
    active_configuration_snapshot_id: UUID | None = None


class UnitValue(BaseModel):
    value: str
    unit: str = Field(min_length=1, max_length=30)
    provenance: Literal["entered"] = "entered"


class BasicInterval(BaseModel):
    id: UUID
    name: str = Field(min_length=1, max_length=200)
    operation_mode: str = Field(min_length=1, max_length=100)
    top_md: UnitValue | None = None
    bottom_md: UnitValue | None = None


class ProjectConfigurationData(BaseModel):
    default_interval_id: UUID | None = None
    intervals: list[BasicInterval] = Field(default_factory=list)


class ConfigurationCreate(BaseModel):
    data: ProjectConfigurationData | None = None
    change_summary: str | None = Field(default=None, max_length=1000)
    copy_active: bool = True


class ConfigurationPatch(BaseModel):
    expected_version: int = Field(ge=1)
    data: ProjectConfigurationData
    change_summary: str | None = Field(default=None, max_length=1000)


class ConfigurationView(BaseModel):
    id: UUID
    project_id: UUID
    version: int
    state: Literal["draft", "active", "superseded"]
    row_version: int
    data: dict[str, Any]
    change_summary: str | None = None
    activated_by: UUID | None = None
    activated_at: datetime | None = None
    snapshot_id: UUID | None = None
    checksum: str | None = None


class ConfigurationReadinessView(BaseModel):
    state: Literal["ready", "incomplete"]
    can_activate: bool
    issues: list[dict[str, Any]]


class DailyReportCreate(BaseModel):
    report_date: date
    report_number: str = Field(min_length=1, max_length=100)


class DraftPatch(BaseModel):
    expected_version: int = Field(ge=1)
    data: dict[str, Any]


class DecisionRequest(BaseModel):
    expected_checksum: str
    reason: str | None = None


class RevisionView(BaseModel):
    id: UUID
    number: int
    kind: str
    state: str
    version: int
    data: dict[str, Any]
    checksum: str | None
    based_on_revision_id: UUID | None


class ReportView(BaseModel):
    id: UUID
    project_id: UUID
    report_date: str
    report_number: str
    revision: RevisionView


class ReadinessView(BaseModel):
    state: str
    can_submit: bool
    issues: list[dict[str, Any]]


class ExportRequest(BaseModel):
    format: Literal["pdf", "xlsx"]
    visibility: Literal["client", "internal"]


class ExportView(BaseModel):
    id: UUID
    revision_id: UUID
    format: str
    visibility: str
    status: str
    payload_checksum: str
    binary_checksum: str
    template_version: str
    renderer_version: str
