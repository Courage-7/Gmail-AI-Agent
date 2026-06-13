"""Deterministic workflow preview runner for the visual builder."""

from __future__ import annotations

import json
import re
from collections import defaultdict, deque
from typing import Any
from uuid import uuid4

from email_assistant_app.application.workflow_validation import WorkflowValidator
from email_assistant_app.domain.workflow import (
    WorkflowDraft,
    WorkflowNode,
    WorkflowRunResponse,
    WorkflowRunStep,
)

TEMPLATE_PATTERN = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")
SUMMARY_LIMIT = 140


class WorkflowPreviewRunner:
    """Run a safe preview of a workflow draft and expose per-node outputs."""

    def __init__(self, validator: WorkflowValidator) -> None:
        self._validator = validator

    async def run(self, workflow: WorkflowDraft) -> WorkflowRunResponse:
        """Validate and run a deterministic preview without external side effects."""
        validation = self._validator.validate(workflow)
        run_id = f"preview-{uuid4().hex[:10]}"
        if not validation.valid:
            return WorkflowRunResponse(
                run_id=run_id,
                status="blocked",
                valid=False,
                validation=validation,
                steps=[],
                result=None,
            )

        context: dict[str, Any] = {}
        outputs_by_node: dict[str, Any] = {}
        steps: list[WorkflowRunStep] = []
        incoming_edges = _incoming_edges_by_target(workflow)

        for node in _topological_nodes(workflow):
            upstream_values = [
                outputs_by_node[edge.source]
                for edge in incoming_edges.get(node.id, [])
                if edge.source in outputs_by_node
            ]
            output, summary = _preview_node(node, upstream_values, context)
            outputs_by_node[node.id] = output
            _store_context(context, node, output)
            steps.append(
                WorkflowRunStep(
                    node_id=node.id,
                    node_type=node.data.node_type,
                    label=node.data.label,
                    status="success",
                    summary=summary,
                    output=output,
                )
            )

        final_result = steps[-1].output if steps else None
        return WorkflowRunResponse(
            run_id=run_id,
            status="completed",
            valid=True,
            validation=validation,
            steps=steps,
            result=final_result,
        )


def _preview_node(
    node: WorkflowNode,
    upstream_values: list[Any],
    context: dict[str, Any],
) -> tuple[Any, str]:
    config = node.data.config
    node_type = node.data.node_type

    if node_type == "input.manual":
        input_name = _clean_name(config.get("inputName"), fallback="request")
        value = _string_config(config, "sampleValue", "")
        return {"name": input_name, "value": value}, f"Loaded manual input `{input_name}`"

    if node_type == "gmail.search_messages":
        query = _render_template(_string_config(config, "query", ""), context)
        output = {
            "query": query,
            "messages": [],
            "preview": "Gmail search is prepared. Live Gmail execution can be connected later.",
        }
        return output, f"Prepared Gmail search: {_limit(query)}"

    if node_type == "llm.chat":
        system_prompt = _render_template(_string_config(config, "systemPrompt", ""), context)
        user_prompt = _render_template(_string_config(config, "userPrompt", ""), context)
        upstream_summary = _limit(_value_to_text(upstream_values[-1])) if upstream_values else "no upstream data"
        output = {
            "text": f"Preview response for: {_limit(user_prompt, 96)}",
            "prompt": user_prompt,
            "systemPrompt": system_prompt,
            "context": upstream_summary,
        }
        return output, "Generated preview LLM response"

    if node_type == "condition.contains":
        source = upstream_values[-1] if upstream_values else ""
        field = _render_template(_string_config(config, "field", "value"), context)
        expected = _render_template(_string_config(config, "contains", ""), context)
        haystack = _field_value(source, field)
        matched = expected.lower() in haystack.lower() if expected else False
        output = {
            "matched": matched,
            "route": "true" if matched else "false",
            "field": field,
            "contains": expected,
        }
        return output, f"Condition routed to `{output['route']}`"

    if node_type == "output.final":
        output_name = _clean_name(config.get("outputName"), fallback="result")
        value = upstream_values[-1] if upstream_values else None
        return {output_name: value}, f"Collected final output `{output_name}`"

    return {
        "preview": "Unsupported preview node type.",
        "nodeType": node_type,
    }, "Skipped unsupported preview node"


def _topological_nodes(workflow: WorkflowDraft) -> list[WorkflowNode]:
    nodes_by_id = {node.id: node for node in workflow.nodes}
    incoming_counts = {node.id: 0 for node in workflow.nodes}
    outgoing: dict[str, list[str]] = defaultdict(list)
    for edge in workflow.edges:
        if edge.source in nodes_by_id and edge.target in nodes_by_id:
            outgoing[edge.source].append(edge.target)
            incoming_counts[edge.target] += 1

    queue = deque(_sort_nodes([node for node in workflow.nodes if incoming_counts[node.id] == 0]))
    ordered: list[WorkflowNode] = []
    while queue:
        node = queue.popleft()
        ordered.append(node)
        newly_ready: list[WorkflowNode] = []
        for target_id in outgoing.get(node.id, []):
            incoming_counts[target_id] -= 1
            if incoming_counts[target_id] == 0:
                newly_ready.append(nodes_by_id[target_id])
        queue.extend(_sort_nodes(newly_ready))

    return ordered if len(ordered) == len(workflow.nodes) else _sort_nodes(workflow.nodes)


def _incoming_edges_by_target(workflow: WorkflowDraft):
    incoming = defaultdict(list)
    for edge in workflow.edges:
        incoming[edge.target].append(edge)
    return incoming


def _sort_nodes(nodes: list[WorkflowNode]) -> list[WorkflowNode]:
    return sorted(nodes, key=lambda node: (node.position.x, node.position.y, node.id))


def _store_context(context: dict[str, Any], node: WorkflowNode, output: Any) -> None:
    output_text = _value_to_text(output)
    context[node.id] = output_text
    context[_context_key(node.data.label)] = output_text
    context[node.data.node_type] = output_text
    if node.data.node_type == "input.manual" and isinstance(output, dict):
        input_name = str(output.get("name") or "request")
        context[f"input.manual.{input_name}"] = output.get("value")
    if node.data.node_type == "llm.chat" and isinstance(output, dict):
        context["llm.chat.text"] = output.get("text")
    if node.data.node_type == "gmail.search_messages" and isinstance(output, dict):
        context["gmail.search_messages.query"] = output.get("query")


def _render_template(value: str, context: dict[str, Any]) -> str:
    def replace(match: re.Match[str]) -> str:
        key = match.group(1).strip()
        replacement = context.get(key)
        return _value_to_text(replacement) if replacement is not None else match.group(0)

    return TEMPLATE_PATTERN.sub(replace, value)


def _field_value(value: Any, field: str) -> str:
    if isinstance(value, dict) and field in value:
        return _value_to_text(value[field])
    return _value_to_text(value)


def _string_config(config: dict[str, Any], key: str, fallback: str) -> str:
    value = config.get(key, fallback)
    return value if isinstance(value, str) else _value_to_text(value)


def _clean_name(value: Any, fallback: str) -> str:
    name = value.strip() if isinstance(value, str) else ""
    return name or fallback


def _context_key(value: str) -> str:
    return ".".join(part for part in re.split(r"[^a-z0-9]+", value.lower()) if part)


def _value_to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=True, sort_keys=True)
    except TypeError:
        return str(value)


def _limit(value: str, limit: int = SUMMARY_LIMIT) -> str:
    clean_value = " ".join(value.split())
    if len(clean_value) <= limit:
        return clean_value
    return f"{clean_value[: limit - 1].rstrip()}..."
