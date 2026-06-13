"""Workflow builder domain models."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class WorkflowNodeConfigField(BaseModel):
    """One editable configuration field for a workflow node type."""

    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(min_length=1)
    label: str = Field(min_length=1)
    field_type: Literal["string", "object", "number", "boolean"] = Field(default="string", alias="type")
    required: bool = True
    multiline: bool = False
    default: Any | None = None
    placeholder: str | None = None


class WorkflowNodeType(BaseModel):
    """Approved workflow node type exposed to the visual builder."""

    model_config = ConfigDict(populate_by_name=True)

    type: str = Field(min_length=1)
    label: str = Field(min_length=1)
    category: Literal["input", "llm", "mcp_tool", "condition", "output"]
    description: str
    config_schema: list[WorkflowNodeConfigField] = Field(default_factory=list, alias="configSchema")
    default_config: dict[str, Any] = Field(default_factory=dict, alias="defaultConfig")
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)


class WorkflowPosition(BaseModel):
    """React Flow-compatible node position."""

    x: float
    y: float


class WorkflowNodeData(BaseModel):
    """React Flow node data used by the backend validator."""

    model_config = ConfigDict(populate_by_name=True)

    label: str = Field(min_length=1)
    node_type: str = Field(alias="nodeType", min_length=1)
    config: dict[str, Any] = Field(default_factory=dict)


class WorkflowNode(BaseModel):
    """Workflow node saved by the builder."""

    id: str = Field(min_length=1)
    type: str | None = None
    position: WorkflowPosition
    data: WorkflowNodeData


class WorkflowEdge(BaseModel):
    """Workflow edge saved by the builder."""

    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(min_length=1)
    source: str = Field(min_length=1)
    target: str = Field(min_length=1)
    source_handle: str | None = Field(default=None, alias="sourceHandle")
    target_handle: str | None = Field(default=None, alias="targetHandle")


class WorkflowDraft(BaseModel):
    """Backend-friendly workflow JSON produced by the visual builder."""

    id: str | None = None
    name: str | None = None
    version: int = Field(default=1, ge=1)
    nodes: list[WorkflowNode] = Field(default_factory=list)
    edges: list[WorkflowEdge] = Field(default_factory=list)
    viewport: dict[str, Any] | None = None


class WorkflowValidationIssue(BaseModel):
    """One workflow validation warning or error."""

    code: str
    message: str
    node_id: str | None = None
    edge_id: str | None = None
    field: str | None = None


class WorkflowValidationResponse(BaseModel):
    """Result returned by the workflow validation endpoint."""

    valid: bool
    errors: list[WorkflowValidationIssue] = Field(default_factory=list)
    warnings: list[WorkflowValidationIssue] = Field(default_factory=list)


class WorkflowRunStep(BaseModel):
    """One visible step from a workflow preview run."""

    node_id: str
    node_type: str
    label: str
    status: Literal["success", "skipped", "error"]
    summary: str
    output: Any | None = None


class WorkflowRunResponse(BaseModel):
    """Result returned by the workflow preview runner."""

    run_id: str
    status: Literal["completed", "blocked"]
    valid: bool
    validation: WorkflowValidationResponse
    steps: list[WorkflowRunStep] = Field(default_factory=list)
    result: Any | None = None
