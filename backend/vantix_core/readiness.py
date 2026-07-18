"""Foundation report readiness rules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

ReadinessState = Literal["ready", "incomplete", "unavailable", "out_of_balance"]


@dataclass(frozen=True, slots=True)
class ReadinessIssue:
    code: str
    section: str
    field: str | None
    message: str
    blocking: bool = True


@dataclass(frozen=True, slots=True)
class ReadinessResult:
    state: ReadinessState
    issues: tuple[ReadinessIssue, ...]

    @property
    def can_submit(self) -> bool:
        return not any(issue.blocking for issue in self.issues)


def validate_foundation_readiness(
    *,
    configuration_snapshot_id: str | None,
    report_data: dict[str, Any],
) -> ReadinessResult:
    """Validate only the foundation fields required before operational modules exist."""

    issues: list[ReadinessIssue] = []
    if not configuration_snapshot_id:
        issues.append(
            ReadinessIssue(
                "CONFIGURATION_SNAPSHOT_REQUIRED",
                "project",
                "configuration_snapshot_id",
                "An active immutable project configuration snapshot is required.",
            )
        )

    general = report_data.get("general")
    if not isinstance(general, dict):
        issues.append(
            ReadinessIssue(
                "GENERAL_SECTION_REQUIRED",
                "general",
                None,
                "The daily general section is required.",
            )
        )
    else:
        for field in ("operation_mode", "interval_id", "fluid_system_id"):
            if general.get(field) in (None, ""):
                issues.append(
                    ReadinessIssue(
                        "REQUIRED_VALUE_MISSING",
                        "general",
                        field,
                        f"{field.replace('_', ' ').title()} is required.",
                    )
                )

    state: ReadinessState = "ready" if not issues else "incomplete"
    return ReadinessResult(state, tuple(issues))
