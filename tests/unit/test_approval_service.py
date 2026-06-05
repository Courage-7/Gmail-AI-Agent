import pytest

from email_assistant_app.application.approval_service import ApprovalService
from email_assistant_app.domain.action import ActionType, ApprovalStatus, ResumeApprovalRequest
from email_assistant_app.errors import ApprovalRequiredError


def test_require_approved_creates_pending_approval_when_missing() -> None:
    service = ApprovalService()

    with pytest.raises(ApprovalRequiredError) as exc_info:
        service.require_approved(ActionType.SEND_EMAIL, {"to": "user@example.com"}, None)

    approval = exc_info.value.details["approval"]
    assert approval["status"] == ApprovalStatus.PENDING.value
    assert approval["action_type"] == ActionType.SEND_EMAIL.value


def test_resume_approval_approves_pending_request() -> None:
    service = ApprovalService()
    approval = service.create(ActionType.SEND_EMAIL, {"to": "user@example.com"})

    updated = service.resume(ResumeApprovalRequest(approval_id=approval.approval_id, approved=True))

    assert updated.status == ApprovalStatus.APPROVED
