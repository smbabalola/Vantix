"""Thread-safe development adapter matching the future PostgreSQL repository boundary."""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from threading import RLock
from typing import Any, cast
from uuid import UUID, uuid4

from vantix_core.lifecycle import ConfigurationSnapshot, DailyReport


class IdempotencyConflict(ValueError):
    pass


@dataclass(slots=True)
class OrganisationRecord:
    id: UUID
    name: str


@dataclass(slots=True)
class ProjectRecord:
    id: UUID
    organisation_id: UUID
    project_code: str
    project_name: str
    well_name: str
    time_zone: str
    currency: str
    unit_set: str
    operator_name: str | None
    client_name: str | None
    rig_name: str | None
    location_text: str | None
    reporting_start_date: Any | None
    configuration_versions: list[dict[str, Any]]
    active_snapshot: ConfigurationSnapshot | None = None


@dataclass(frozen=True, slots=True)
class ExportRecord:
    id: UUID
    revision_id: UUID
    format: str
    visibility: str
    status: str
    payload_checksum: str
    binary_checksum: str
    template_version: str
    renderer_version: str
    content: bytes


class FoundationStore:
    def __init__(self) -> None:
        self._lock = RLock()
        self.organisations: dict[UUID, OrganisationRecord] = {}
        self.projects: dict[UUID, ProjectRecord] = {}
        self.project_products: dict[UUID, dict[str, Any]] = {}
        self.product_prices: dict[UUID, dict[str, Any]] = {}
        self.reports: dict[UUID, DailyReport] = {}
        self.exports: dict[UUID, ExportRecord] = {}
        self.idempotency: dict[tuple[UUID, str, str], tuple[str, Any]] = {}

    def create_organisation(self, name: str) -> OrganisationRecord:
        with self._lock:
            record = OrganisationRecord(uuid4(), name)
            self.organisations[record.id] = record
            return record

    def create_project(self, organisation_id: UUID, **values: str) -> ProjectRecord:
        with self._lock:
            record = ProjectRecord(
                id=uuid4(),
                organisation_id=organisation_id,
                project_code=values["project_code"],
                project_name=values["project_name"],
                well_name=values["well_name"],
                time_zone=values["time_zone"],
                currency=values["currency"],
                unit_set=values["unit_set"],
                operator_name=values.get("operator_name"),
                client_name=values.get("client_name"),
                rig_name=values.get("rig_name"),
                location_text=values.get("location_text"),
                reporting_start_date=values.get("reporting_start_date"),
                configuration_versions=[],
            )
            self.projects[record.id] = record
            return record

    def idempotent[T](
        self,
        *,
        organisation_id: UUID,
        operation_type: str,
        idempotency_key: str,
        request_hash: str,
        operation: Callable[[], T],
    ) -> T:
        key = (organisation_id, operation_type, idempotency_key)
        with self._lock:
            existing = self.idempotency.get(key)
            if existing:
                existing_hash, response = existing
                if existing_hash != request_hash:
                    raise IdempotencyConflict
                return deepcopy(cast(T, response))
            response = operation()
            self.idempotency[key] = (request_hash, deepcopy(response))
            return response


store = FoundationStore()
