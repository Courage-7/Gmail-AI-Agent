"""Action and approval domain models."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel


class ActionType(StrEnum):
    """External action types that require approval."""

    SEND_EMAIL = "send_email"


class ApprovalStatus(StrEnum):
    """Approval lifecycle states."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ApprovalRequest(BaseModel):
    """Human approval request for an external action."""

    approval_id: str
    action_type: ActionType
    status: ApprovalStatus
    payload: dict[str, Any]
    created_at: datetime
    resolved_at: datetime | None = None


class ResumeApprovalRequest(BaseModel):
    """Request to approve or reject a pending action."""

    approval_id: str
    approved: bool
