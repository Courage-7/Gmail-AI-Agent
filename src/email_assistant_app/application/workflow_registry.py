"""Approved workflow builder node registry."""

from __future__ import annotations

from email_assistant_app.domain.workflow import WorkflowNodeConfigField, WorkflowNodeType


class WorkflowNodeRegistry:
    """Expose only backend-approved node types to the visual builder."""

    def __init__(self) -> None:
        self._node_types = {
            node_type.type: node_type
            for node_type in [
                WorkflowNodeType(
                    type="input.manual",
                    label="Manual Input",
                    category="input",
                    description="Starting values supplied by a user or future API request.",
                    config_schema=[
                        WorkflowNodeConfigField(
                            name="inputName",
                            label="Input name",
                            required=True,
                            default="request",
                        ),
                        WorkflowNodeConfigField(
                            name="sampleValue",
                            label="Sample value",
                            required=False,
                            multiline=True,
                            default="Summarize my latest important email.",
                        ),
                    ],
                    default_config={
                        "inputName": "request",
                        "sampleValue": "Summarize my latest important email.",
                    },
                    outputs=["value"],
                ),
                WorkflowNodeType(
                    type="llm.chat",
                    label="LLM Chat",
                    category="llm",
                    description="Prepare a server-side LLM chat call through the approved LLM adapter.",
                    config_schema=[
                        WorkflowNodeConfigField(
                            name="systemPrompt",
                            label="System prompt",
                            required=True,
                            multiline=True,
                            default="You are a careful email workflow assistant.",
                        ),
                        WorkflowNodeConfigField(
                            name="userPrompt",
                            label="User prompt",
                            required=True,
                            multiline=True,
                            default="{{input.manual.request}}",
                        ),
                    ],
                    default_config={
                        "systemPrompt": "You are a careful email workflow assistant.",
                        "userPrompt": "{{input.manual.request}}",
                    },
                    inputs=["context"],
                    outputs=["text"],
                ),
                WorkflowNodeType(
                    type="gmail.search_messages",
                    label="Search Gmail",
                    category="mcp_tool",
                    description="Search Gmail through the existing approved Docker Gmail MCP service.",
                    config_schema=[
                        WorkflowNodeConfigField(
                            name="query",
                            label="Gmail query",
                            required=True,
                            multiline=True,
                            default="in:inbox newer_than:7d",
                        ),
                    ],
                    default_config={"query": "in:inbox newer_than:7d"},
                    inputs=["query"],
                    outputs=["messages"],
                ),
                WorkflowNodeType(
                    type="condition.contains",
                    label="Contains Condition",
                    category="condition",
                    description="Route based on whether a configured field contains a configured value.",
                    config_schema=[
                        WorkflowNodeConfigField(name="field", label="Field", required=True, default="subject"),
                        WorkflowNodeConfigField(name="contains", label="Contains", required=True, default="urgent"),
                    ],
                    default_config={"field": "subject", "contains": "urgent"},
                    inputs=["value"],
                    outputs=["true", "false"],
                ),
                WorkflowNodeType(
                    type="output.final",
                    label="Final Output",
                    category="output",
                    description="Collect the final workflow result.",
                    config_schema=[
                        WorkflowNodeConfigField(
                            name="outputName",
                            label="Output name",
                            required=True,
                            default="result",
                        ),
                    ],
                    default_config={"outputName": "result"},
                    inputs=["value"],
                ),
            ]
        }

    def list_node_types(self) -> list[WorkflowNodeType]:
        """Return all node types approved for the visual builder."""
        return list(self._node_types.values())

    def get_node_type(self, node_type: str) -> WorkflowNodeType | None:
        """Return one approved node type by id."""
        return self._node_types.get(node_type)
