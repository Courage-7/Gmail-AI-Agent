"""Workflow builder validation service."""

from __future__ import annotations

from collections import Counter, defaultdict, deque
from collections.abc import Iterable
from typing import Any

from email_assistant_app.application.workflow_registry import WorkflowNodeRegistry
from email_assistant_app.domain.workflow import (
    WorkflowDraft,
    WorkflowNode,
    WorkflowValidationIssue,
    WorkflowValidationResponse,
)

MAX_WORKFLOW_NODES = 50
MAX_WORKFLOW_EDGES = 100
SENSITIVE_CONFIG_KEY_PARTS = ("secret", "password", "token", "api_key", "apikey")


class WorkflowValidator:
    """Validate untrusted workflow JSON before any future runtime execution."""

    def __init__(self, registry: WorkflowNodeRegistry) -> None:
        self._registry = registry

    def validate(self, workflow: WorkflowDraft) -> WorkflowValidationResponse:
        """Return validation issues for a workflow draft without executing it."""
        errors: list[WorkflowValidationIssue] = []
        warnings: list[WorkflowValidationIssue] = []

        if not workflow.nodes:
            errors.append(
                WorkflowValidationIssue(
                    code="workflow_has_no_nodes",
                    message="Workflow must contain at least one node.",
                    field="nodes",
                )
            )

        if len(workflow.nodes) > MAX_WORKFLOW_NODES:
            errors.append(
                WorkflowValidationIssue(
                    code="too_many_nodes",
                    message=f"Workflow has {len(workflow.nodes)} nodes; maximum is {MAX_WORKFLOW_NODES}.",
                    field="nodes",
                )
            )

        if len(workflow.edges) > MAX_WORKFLOW_EDGES:
            errors.append(
                WorkflowValidationIssue(
                    code="too_many_edges",
                    message=f"Workflow has {len(workflow.edges)} edges; maximum is {MAX_WORKFLOW_EDGES}.",
                    field="edges",
                )
            )

        node_counts = Counter(node.id for node in workflow.nodes)
        duplicate_node_ids = {node_id for node_id, count in node_counts.items() if count > 1}
        for node_id in sorted(duplicate_node_ids):
            errors.append(
                WorkflowValidationIssue(
                    code="duplicate_node_id",
                    message=f"Workflow contains duplicate node id: {node_id}.",
                    node_id=node_id,
                )
            )

        nodes_by_id = {node.id: node for node in workflow.nodes if node.id not in duplicate_node_ids}
        for node in workflow.nodes:
            self._validate_node(node, errors, warnings)

        for edge in workflow.edges:
            if edge.source not in nodes_by_id:
                errors.append(
                    WorkflowValidationIssue(
                        code="invalid_edge_source",
                        message=f"Edge source node does not exist: {edge.source}.",
                        edge_id=edge.id,
                        field="source",
                    )
                )
            if edge.target not in nodes_by_id:
                errors.append(
                    WorkflowValidationIssue(
                        code="invalid_edge_target",
                        message=f"Edge target node does not exist: {edge.target}.",
                        edge_id=edge.id,
                        field="target",
                    )
                )

        if not duplicate_node_ids and nodes_by_id:
            self._validate_graph_shape(workflow, nodes_by_id, errors, warnings)

        return WorkflowValidationResponse(valid=not errors, errors=errors, warnings=warnings)

    def _validate_node(
        self,
        node: WorkflowNode,
        errors: list[WorkflowValidationIssue],
        warnings: list[WorkflowValidationIssue],
    ) -> None:
        node_type = self._registry.get_node_type(node.data.node_type)
        if node_type is None:
            errors.append(
                WorkflowValidationIssue(
                    code="unsupported_node_type",
                    message=f"Unsupported workflow node type: {node.data.node_type}.",
                    node_id=node.id,
                    field="data.nodeType",
                )
            )
            return

        if node.type and node.type != "workflowNode":
            warnings.append(
                WorkflowValidationIssue(
                    code="unexpected_react_flow_node_type",
                    message="React Flow node renderer should be workflowNode for workflow builder nodes.",
                    node_id=node.id,
                    field="type",
                )
            )

        for field in node_type.config_schema:
            if not field.required:
                continue
            value = node.data.config.get(field.name)
            if _is_blank(value):
                errors.append(
                    WorkflowValidationIssue(
                        code="missing_required_config",
                        message=f"Node {node.id} is missing required config field: {field.name}.",
                        node_id=node.id,
                        field=f"data.config.{field.name}",
                    )
                )

        for config_key in node.data.config:
            normalized = config_key.lower().replace("-", "_")
            if any(part in normalized for part in SENSITIVE_CONFIG_KEY_PARTS):
                errors.append(
                    WorkflowValidationIssue(
                        code="frontend_secret_config_not_allowed",
                        message=f"Secrets and credentials cannot be supplied from workflow node config: {config_key}.",
                        node_id=node.id,
                        field=f"data.config.{config_key}",
                    )
                )

    def _validate_graph_shape(
        self,
        workflow: WorkflowDraft,
        nodes_by_id: dict[str, WorkflowNode],
        errors: list[WorkflowValidationIssue],
        warnings: list[WorkflowValidationIssue],
    ) -> None:
        incoming: dict[str, list[str]] = defaultdict(list)
        outgoing: dict[str, list[str]] = defaultdict(list)
        for edge in workflow.edges:
            if edge.source in nodes_by_id and edge.target in nodes_by_id:
                outgoing[edge.source].append(edge.target)
                incoming[edge.target].append(edge.source)

        for node in nodes_by_id.values():
            node_type = node.data.node_type
            if node_type == "input.manual" and incoming[node.id]:
                errors.append(
                    WorkflowValidationIssue(
                        code="input_node_has_incoming_edge",
                        message="Manual input nodes cannot have incoming edges.",
                        node_id=node.id,
                    )
                )
            if node_type == "output.final" and outgoing[node.id]:
                errors.append(
                    WorkflowValidationIssue(
                        code="output_node_has_outgoing_edge",
                        message="Final output nodes cannot have outgoing edges.",
                        node_id=node.id,
                    )
                )
            if node_type != "input.manual" and not incoming[node.id]:
                errors.append(
                    WorkflowValidationIssue(
                        code="node_missing_incoming_edge",
                        message="Non-input nodes must have at least one incoming edge.",
                        node_id=node.id,
                    )
                )
            if node_type != "output.final" and not outgoing[node.id]:
                errors.append(
                    WorkflowValidationIssue(
                        code="node_missing_outgoing_edge",
                        message="Non-output nodes must have at least one outgoing edge.",
                        node_id=node.id,
                    )
                )

        input_nodes = [node for node in nodes_by_id.values() if node.data.node_type == "input.manual"]
        output_nodes = [node for node in nodes_by_id.values() if node.data.node_type == "output.final"]
        if not input_nodes:
            errors.append(
                WorkflowValidationIssue(
                    code="workflow_missing_input_node",
                    message="Workflow must include at least one manual input node.",
                    field="nodes",
                )
            )
        if not output_nodes:
            errors.append(
                WorkflowValidationIssue(
                    code="workflow_missing_output_node",
                    message="Workflow must include at least one final output node.",
                    field="nodes",
                )
            )

        if _has_cycle(nodes_by_id.keys(), outgoing):
            errors.append(
                WorkflowValidationIssue(
                    code="workflow_cycle_detected",
                    message="Workflow contains a cycle; loops are not supported yet.",
                    field="edges",
                )
            )

        if len(input_nodes) > 1:
            warnings.append(
                WorkflowValidationIssue(
                    code="multiple_input_nodes",
                    message="Multiple manual input nodes are allowed for drafts, but execution will need an entry policy.",
                    field="nodes",
                )
            )


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, dict)):
        return not value
    return False


def _has_cycle(node_ids: Iterable[str], outgoing: dict[str, list[str]]) -> bool:
    node_id_set = set(node_ids)
    incoming_counts = {node_id: 0 for node_id in node_id_set}
    for source, targets in outgoing.items():
        if source not in node_id_set:
            continue
        for target in targets:
            if target in incoming_counts:
                incoming_counts[target] += 1

    queue = deque(node_id for node_id, count in incoming_counts.items() if count == 0)
    visited = 0
    while queue:
        node_id = queue.popleft()
        visited += 1
        for target in outgoing.get(node_id, []):
            if target not in incoming_counts:
                continue
            incoming_counts[target] -= 1
            if incoming_counts[target] == 0:
                queue.append(target)

    return visited != len(node_id_set)
