from uuid import uuid4

import pytest
from vantix_core.lifecycle import ConfigurationSnapshot, DailyReport, LifecycleError, RevisionState


def make_report() -> tuple[DailyReport, object, object]:
    organisation_id = uuid4()
    project_id = uuid4()
    editor_id = uuid4()
    snapshot = ConfigurationSnapshot.create(
        project_id,
        1,
        {"project": {"name": "North Sea A"}, "unit_set": {"name": "Field"}},
    )
    report = DailyReport.create(
        organisation_id=organisation_id,
        project_id=project_id,
        report_date="2026-07-18",
        report_number="VTX-0001",
        configuration_snapshot=snapshot,
        actor_id=editor_id,
    )
    report.edit(
        {
            "general": {
                "operation_mode": "drilling",
                "interval_id": str(uuid4()),
                "fluid_system_id": str(uuid4()),
            }
        },
        expected_version=1,
        actor_id=editor_id,
    )
    return report, editor_id, uuid4()


def test_vtx_mvp_004_configuration_snapshot_is_defensively_immutable() -> None:
    snapshot = ConfigurationSnapshot.create(uuid4(), 1, {"project": {"name": "Original"}})
    exposed = snapshot.payload
    exposed["project"]["name"] = "Changed"
    assert snapshot.payload["project"]["name"] == "Original"


def test_vtx_mvp_005_stale_draft_edit_is_rejected() -> None:
    report, editor_id, _ = make_report()
    with pytest.raises(LifecycleError, match="changed") as error:
        report.edit({"comments": {}}, expected_version=1, actor_id=editor_id)
    assert error.value.code == "REPORT_VERSION_CONFLICT"


def test_vtx_mvp_006_vtx_rpt_002_submission_is_immutable_and_checksummed() -> None:
    report, editor_id, _ = make_report()
    submitted = report.submit(expected_version=2, actor_id=editor_id)
    assert submitted.state is RevisionState.SUBMITTED
    assert submitted.checksum and len(submitted.checksum) == 64
    with pytest.raises(LifecycleError) as error:
        report.edit({"general": {}}, expected_version=2, actor_id=editor_id)
    assert error.value.code == "REPORT_REVISION_LOCKED"


def test_vtx_mvp_007_008_vtx_api_005_rejection_retains_submission_and_creates_draft() -> None:
    report, editor_id, reviewer_id = make_report()
    submitted = report.submit(expected_version=2, actor_id=editor_id)
    checksum = submitted.checksum
    draft = report.reject(
        submitted_revision_id=submitted.id,
        expected_checksum=checksum or "",
        actor_id=reviewer_id,
        reason="Correct interval context",
    )
    assert report.revisions[0].state is RevisionState.REJECTED
    assert report.revisions[0].checksum == checksum
    assert draft.state is RevisionState.DRAFT
    assert draft.based_on_revision_id == submitted.id
    assert draft.data == submitted.data


def test_vtx_auth_009_vtx_api_006_approval_is_checksum_bound_and_not_self_approved() -> None:
    report, editor_id, approver_id = make_report()
    submitted = report.submit(expected_version=2, actor_id=editor_id)
    with pytest.raises(LifecycleError) as mismatch:
        report.approve(
            submitted_revision_id=submitted.id,
            expected_checksum="0" * 64,
            actor_id=approver_id,
        )
    assert mismatch.value.code == "REPORT_CHECKSUM_CONFLICT"
    with pytest.raises(LifecycleError) as self_approval:
        report.approve(
            submitted_revision_id=submitted.id,
            expected_checksum=submitted.checksum or "",
            actor_id=editor_id,
        )
    assert self_approval.value.code == "SELF_APPROVAL_DENIED"
    approved = report.approve(
        submitted_revision_id=submitted.id,
        expected_checksum=submitted.checksum or "",
        actor_id=approver_id,
    )
    assert approved.state is RevisionState.APPROVED


def test_vtx_mvp_010_vtx_aud_001_all_mutations_are_audited() -> None:
    report, editor_id, approver_id = make_report()
    submitted = report.submit(expected_version=2, actor_id=editor_id)
    report.approve(
        submitted_revision_id=submitted.id,
        expected_checksum=submitted.checksum or "",
        actor_id=approver_id,
    )
    assert [event.action for event in report.audit_events] == [
        "create_draft",
        "update_draft",
        "submit",
        "approve",
    ]
    assert all(event.actor_id and event.correlation_id for event in report.audit_events)
