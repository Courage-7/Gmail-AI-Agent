"""Approval endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from email_assistant_app.application.approval_service import ApprovalService
from email_assistant_app.application.dependencies import get_approval_service
from email_assistant_app.domain.action import ApprovalRequest, ResumeApprovalRequest

router = APIRouter(prefix="/approvals", tags=["approvals"])


@router.post("/resume", response_model=ApprovalRequest)
async def resume_approval(
    body: ResumeApprovalRequest,
    service: ApprovalService = Depends(get_approval_service),
) -> ApprovalRequest:
    """Approve or reject a pending action."""
    return service.resume(body)
