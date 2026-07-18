"""Pure domain model for report revision lifecycle invariants."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from .canonical import payload_checksum
from .readiness import ReadinessResult, validate_foundation_readiness


class LifecycleError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class RevisionKind(StrEnum):
    ORIGINAL = "original"
    REVISION_AFTER_REJECTION = "revision_after_rejection"
    AMENDMENT = "amendment"


class RevisionState(StrEnum):
    DRAFT = "draft"
    READY_FOR_REVIEW = "ready_for_review"
    SUBMITTED = "submitted"
    REJECTED = "rejected"
    APPROVED = "approved"
    SUPERSEDED = "superseded"
    CANCELLED = "cancelled"


IMMUTABLE_STATES = {
    RevisionState.SUBMITTED,
    RevisionState.REJECTED,
    RevisionState.APPROVED,
    RevisionState.SUPERSEDED,
    RevisionState.CANCELLED,
}


@dataclass(frozen=True, slots=True)
class ConfigurationSnapshot:
    id: UUID
    project_id: UUID
    version: int
    _payload: dict[str, Any]
    checksum: str

    @property
    def payload(self) -> dict[str, Any]:
        """Return a defensive copy so activated configuration cannot mutate in place."""

        return deepcopy(self._payload)

    @classmethod
    def create(
        cls, project_id: UUID, version: int, payload: dict[str, Any]
    ) -> ConfigurationSnapshot:
        frozen_payload = deepcopy(payload)
        return cls(uuid4(), project_id, version, frozen_payload, payload_checksum(frozen_payload))


@dataclass(frozen=True, slots=True)
class AuditEvent:
    id: UUID
    organisation_id: UUID
    project_id: UUID
    actor_id: UUID
    entity_type: str
    entity_id: UUID
    action: str
    occurred_at: datetime
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    reason: str | None
    correlation_id: UUID


@dataclass(slots=True)
class ReportRevision:
    id: UUID
    number: int
    kind: RevisionKind
    state: RevisionState
    configuration_snapshot_id: UUID
    data: dict[str, Any]
    version: int = 1
    based_on_revision_id: UUID | None = None
    payload: dict[str, Any] | None = None
    checksum: str | None = None
    submitted_by: UUID | None = None
    approved_by: UUID | None = None
    rejection_reason: str | None = None

    @property
    def mutable(self) -> bool:
        return self.state in {RevisionState.DRAFT, RevisionState.READY_FOR_REVIEW}

    def edit(self, patch: dict[str, Any], *, expected_version: int) -> None:
        if not self.mutable:
            raise LifecycleError(
                "REPORT_REVISION_LOCKED", "Only an active draft revision can be edited."
            )
        if expected_version != self.version:
            raise LifecycleError(
                "REPORT_VERSION_CONFLICT", "The draft changed after it was loaded."
            )
        self.data.update(deepcopy(patch))
        self.version += 1

    def readiness(self) -> ReadinessResult:
        return validate_foundation_readiness(
            configuration_snapshot_id=str(self.configuration_snapshot_id),
            report_data=self.data,
        )


@dataclass(slots=True)
class DailyReport:
    id: UUID
    organisation_id: UUID
    project_id: UUID
    report_date: str
    report_number: str
    configuration_snapshot: ConfigurationSnapshot
    revisions: list[ReportRevision] = field(default_factory=list)
    audit_events: list[AuditEvent] = field(default_factory=list)

    @classmethod
    def create(
        cls,
        *,
        organisation_id: UUID,
        project_id: UUID,
        report_date: str,
        report_number: str,
        configuration_snapshot: ConfigurationSnapshot,
        actor_id: UUID,
        correlation_id: UUID | None = None,
    ) -> DailyReport:
        revision = ReportRevision(
            id=uuid4(),
            number=1,
            kind=RevisionKind.ORIGINAL,
            state=RevisionState.DRAFT,
            configuration_snapshot_id=configuration_snapshot.id,
            data={},
        )
        report = cls(
            uuid4(),
            organisation_id,
            project_id,
            report_date,
            report_number,
            configuration_snapshot,
            [revision],
        )
        report._audit(
            actor_id=actor_id,
            revision=revision,
            action="create_draft",
            before=None,
            after={"state": revision.state.value, "version": revision.version},
            correlation_id=correlation_id or uuid4(),
        )
        return report

    @property
    def current_revision(self) -> ReportRevision:
        return self.revisions[-1]

    def edit(
        self,
        patch: dict[str, Any],
        *,
        expected_version: int,
        actor_id: UUID,
        correlation_id: UUID | None = None,
    ) -> ReportRevision:
        revision = self.current_revision
        before = {"version": revision.version, "data": deepcopy(revision.data)}
        revision.edit(patch, expected_version=expected_version)
        self._audit(
            actor_id=actor_id,
            revision=revision,
            action="update_draft",
            before=before,
            after={"version": revision.version, "data": deepcopy(revision.data)},
            correlation_id=correlation_id or uuid4(),
        )
        return revision

    def submit(
        self,
        *,
        expected_version: int,
        actor_id: UUID,
        correlation_id: UUID | None = None,
    ) -> ReportRevision:
        revision = self.current_revision
        if not revision.mutable:
            raise LifecycleError("REPORT_REVISION_LOCKED", "The current revision is not mutable.")
        if expected_version != revision.version:
            raise LifecycleError(
                "REPORT_VERSION_CONFLICT", "The draft changed after it was loaded."
            )
        readiness = revision.readiness()
        if not readiness.can_submit:
            raise LifecycleError("REPORT_NOT_READY", "Blocking readiness issues must be resolved.")
        before = {"state": revision.state.value, "version": revision.version}
        revision.state = RevisionState.SUBMITTED
        revision.submitted_by = actor_id
        revision.payload = self._build_payload(revision)
        revision.checksum = payload_checksum(revision.payload)
        self._audit(
            actor_id=actor_id,
            revision=revision,
            action="submit",
            before=before,
            after={"state": revision.state.value, "checksum": revision.checksum},
            correlation_id=correlation_id or uuid4(),
        )
        return revision

    def reject(
        self,
        *,
        submitted_revision_id: UUID,
        expected_checksum: str,
        actor_id: UUID,
        reason: str,
        correlation_id: UUID | None = None,
    ) -> ReportRevision:
        submitted = self.current_revision
        self._require_current_submission(submitted, submitted_revision_id, expected_checksum)
        if not reason.strip():
            raise LifecycleError("REJECTION_REASON_REQUIRED", "A rejection reason is required.")
        submitted.state = RevisionState.REJECTED
        submitted.rejection_reason = reason.strip()
        new_draft = ReportRevision(
            id=uuid4(),
            number=submitted.number + 1,
            kind=RevisionKind.REVISION_AFTER_REJECTION,
            state=RevisionState.DRAFT,
            configuration_snapshot_id=submitted.configuration_snapshot_id,
            data=deepcopy(submitted.data),
            based_on_revision_id=submitted.id,
        )
        self.revisions.append(new_draft)
        self._audit(
            actor_id=actor_id,
            revision=submitted,
            action="reject",
            before={"state": RevisionState.SUBMITTED.value},
            after={"state": submitted.state.value, "new_draft_revision_id": str(new_draft.id)},
            reason=reason.strip(),
            correlation_id=correlation_id or uuid4(),
        )
        return new_draft

    def approve(
        self,
        *,
        submitted_revision_id: UUID,
        expected_checksum: str,
        actor_id: UUID,
        allow_self_approval: bool = False,
        correlation_id: UUID | None = None,
    ) -> ReportRevision:
        revision = self.current_revision
        self._require_current_submission(revision, submitted_revision_id, expected_checksum)
        if not allow_self_approval and revision.submitted_by == actor_id:
            raise LifecycleError(
                "SELF_APPROVAL_DENIED", "A submitter cannot approve their own report."
            )
        revision.state = RevisionState.APPROVED
        revision.approved_by = actor_id
        self._audit(
            actor_id=actor_id,
            revision=revision,
            action="approve",
            before={"state": RevisionState.SUBMITTED.value},
            after={"state": revision.state.value, "checksum": revision.checksum},
            correlation_id=correlation_id or uuid4(),
        )
        return revision

    def _require_current_submission(
        self,
        revision: ReportRevision,
        revision_id: UUID,
        checksum: str,
    ) -> None:
        if revision.id != revision_id or revision.state is not RevisionState.SUBMITTED:
            raise LifecycleError(
                "REPORT_NOT_CURRENT_SUBMISSION", "Decision target is not the current submission."
            )
        if revision.checksum != checksum:
            raise LifecycleError(
                "REPORT_CHECKSUM_CONFLICT", "Decision checksum does not match the submission."
            )

    def _build_payload(self, revision: ReportRevision) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "template": {"key": "daily-fluids-report", "version": "1.0"},
            "payload_version": 1,
            "revision": {
                "number": revision.number,
                "kind": revision.kind.value,
                "state": RevisionState.SUBMITTED.value,
                "based_on_revision_id": (
                    str(revision.based_on_revision_id) if revision.based_on_revision_id else None
                ),
            },
            "report": {
                "id": str(self.id),
                "number": self.report_number,
                "date": self.report_date,
                "state": RevisionState.SUBMITTED.value,
            },
            "project_snapshot": deepcopy(self.configuration_snapshot.payload),
            "operations": deepcopy(revision.data),
            "reconciliation": {
                "readiness": {
                    "state": revision.readiness().state,
                    "issues": [],
                }
            },
            "approval": {
                "submitted_by": str(revision.submitted_by),
                "approved_by": None,
                "amendment_of": None,
            },
            "caveats": [],
        }

    def _audit(
        self,
        *,
        actor_id: UUID,
        revision: ReportRevision,
        action: str,
        before: dict[str, Any] | None,
        after: dict[str, Any] | None,
        correlation_id: UUID,
        reason: str | None = None,
    ) -> None:
        self.audit_events.append(
            AuditEvent(
                id=uuid4(),
                organisation_id=self.organisation_id,
                project_id=self.project_id,
                actor_id=actor_id,
                entity_type="daily_report_revision",
                entity_id=revision.id,
                action=action,
                occurred_at=datetime.now(UTC),
                before=deepcopy(before),
                after=deepcopy(after),
                reason=reason,
                correlation_id=correlation_id,
            )
        )
