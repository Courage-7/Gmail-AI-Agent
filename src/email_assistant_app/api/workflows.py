"""Workflow builder registry and validation endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from email_assistant_app.application.dependencies import (
    get_workflow_node_registry,
    get_workflow_preview_runner,
    get_workflow_validator,
)
from email_assistant_app.application.workflow_execution import WorkflowPreviewRunner
from email_assistant_app.application.workflow_registry import WorkflowNodeRegistry
from email_assistant_app.application.workflow_validation import WorkflowValidator
from email_assistant_app.domain.workflow import (
    WorkflowDraft,
    WorkflowNodeType,
    WorkflowRunResponse,
    WorkflowValidationResponse,
)

router = APIRouter(tags=["workflows"])


@router.get("/workflow-node-types", response_model=list[WorkflowNodeType])
async def workflow_node_types(
    registry: WorkflowNodeRegistry = Depends(get_workflow_node_registry),
) -> list[WorkflowNodeType]:
    """Return backend-approved workflow builder node types."""
    return registry.list_node_types()


@router.post("/workflows/validate", response_model=WorkflowValidationResponse)
async def validate_workflow(
    body: WorkflowDraft,
    validator: WorkflowValidator = Depends(get_workflow_validator),
) -> WorkflowValidationResponse:
    """Validate workflow JSON without saving or executing it."""
    return validator.validate(body)


@router.post("/workflows/run", response_model=WorkflowRunResponse)
async def run_workflow_preview(
    body: WorkflowDraft,
    runner: WorkflowPreviewRunner = Depends(get_workflow_preview_runner),
) -> WorkflowRunResponse:
    """Run a safe preview of a workflow draft and return visible step outputs."""
    return await runner.run(body)
