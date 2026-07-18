from __future__ import annotations

from datetime import date
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
    time_zone: str
    currency: str = Field(min_length=3, max_length=3)
    unit_set: str


class ProjectView(ProjectCreate):
    id: UUID
    organisation_id: UUID
    active_configuration_snapshot_id: UUID | None = None


class ConfigurationCreate(BaseModel):
    data: dict[str, Any]


class ConfigurationView(BaseModel):
    id: UUID
    project_id: UUID
    version: int
    state: Literal["draft", "active"]
    data: dict[str, Any]
    snapshot_id: UUID | None = None
    checksum: str | None = None


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
