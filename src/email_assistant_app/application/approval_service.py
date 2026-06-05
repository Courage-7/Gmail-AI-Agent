"""Approval service."""

from __future__ import annotations

from datetime import UTC, datetime
from threading import Lock
from uuid import uuid4

from email_assistant_app.domain.action import (
    ActionType,
    ApprovalRequest,
    ApprovalStatus,
    ResumeApprovalRequest,
)
from email_assistant_app.errors import ApprovalRequiredError, InvalidApprovalError, NotFoundError


class ApprovalService:
    """In-memory approval store for local service use."""

    def __init__(self) -> None:
        self._approvals: dict[str, ApprovalRequest] = {}
        self._lock = Lock()

    def create(self, action_type: ActionType, payload: dict) -> ApprovalRequest:
        """Create a pending approval."""
        approval = ApprovalRequest(
            approval_id=str(uuid4()),
            action_type=action_type,
            status=ApprovalStatus.PENDING,
            payload=payload,
            created_at=datetime.now(UTC),
        )
        with self._lock:
            self._approvals[approval.approval_id] = approval
        return approval

    def get(self, approval_id: str) -> ApprovalRequest:
        """Return an approval by ID."""
        with self._lock:
            approval = self._approvals.get(approval_id)
        if not approval:
            raise NotFoundError("Approval request not found.", details={"approval_id": approval_id})
        return approval

    def resume(self, request: ResumeApprovalRequest) -> ApprovalRequest:
        """Approve or reject a pending action."""
        with self._lock:
            approval = self._approvals.get(request.approval_id)
            if not approval:
                raise NotFoundError("Approval request not found.", details={"approval_id": request.approval_id})
            if approval.status != ApprovalStatus.PENDING:
                return approval
            updated = approval.model_copy(
                update={
                    "status": ApprovalStatus.APPROVED if request.approved else ApprovalStatus.REJECTED,
                    "resolved_at": datetime.now(UTC),
                }
            )
            self._approvals[request.approval_id] = updated
            return updated

    def require_approved(
        self,
        action_type: ActionType,
        payload: dict,
        approval_id: str | None,
    ) -> ApprovalRequest:
        """Require a matching approved approval for an external action."""
        if not approval_id:
            approval = self.create(action_type, payload)
            raise ApprovalRequiredError(
                "Approval is required before executing this action.",
                details={"approval": approval.model_dump(mode="json")},
            )

        approval = self.get(approval_id)
        if approval.action_type != action_type:
            raise InvalidApprovalError(
                "Approval action type does not match the requested action.",
                details={"approval_id": approval_id, "expected": action_type.value},
            )
        if approval.status == ApprovalStatus.PENDING:
            raise ApprovalRequiredError(
                "Approval is still pending.",
                details={"approval": approval.model_dump(mode="json")},
            )
        if approval.status == ApprovalStatus.REJECTED:
            raise InvalidApprovalError(
                "Approval was rejected.",
                details={"approval_id": approval_id},
            )
        return approval
