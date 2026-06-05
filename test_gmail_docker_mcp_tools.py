"""Standalone Docker Gmail MCP smoke test.

This intentionally does not integrate with FastAPI, LangGraph, or the old
LangChain MCP adapter path.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from email_assistant_app.integrations.mcp.gmail_docker_client import (
    GmailDockerMcpEnvironment,
    GmailDockerMcpPreflightError,
    gmail_docker_mcp_session,
    run_preflight,
)

REPORT_PATH = Path("gmail_docker_mcp_test_report.md")
REQUIRED_TOOLS = ("listMessages", "findMessage", "sendMessage")


@dataclass
class ToolTestResult:
    """Recorded result for one Gmail MCP tool call."""

    tool_name: str
    arguments: dict[str, Any]
    status: str
    result_shape: dict[str, Any] = field(default_factory=dict)
    observed_fields: list[str] = field(default_factory=list)
    error: str | None = None


def safe_model_dump(value: Any) -> Any:
    """Return JSON-compatible data for MCP result objects."""
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", by_alias=True)
    return value


def collect_keys(value: Any) -> set[str]:
    """Collect keys recursively from dict/list values and JSON text blocks."""
    keys: set[str] = set()
    if isinstance(value, dict):
        keys.update(str(key) for key in value)
        for item in value.values():
            keys.update(collect_keys(item))
        if value.get("type") == "text" and isinstance(value.get("text"), str):
            keys.update(collect_json_text_keys(value["text"]))
    elif isinstance(value, list):
        for item in value:
            keys.update(collect_keys(item))
    return keys


def collect_json_text_keys(raw_value: str) -> set[str]:
    """Collect keys from text content when the server returns JSON as text."""
    text = raw_value.strip()
    if not text or text[0] not in "[{":
        return set()
    try:
        return collect_keys(json.loads(text))
    except json.JSONDecodeError:
        return set()


def describe_result_shape(result: Any) -> dict[str, Any]:
    """Summarize an MCP tool result without dumping full email bodies."""
    data = safe_model_dump(result)
    if not isinstance(data, dict):
        return {"python_type": type(result).__name__}

    content = data.get("content") or []
    content_shapes = []
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict):
                content_shapes.append(
                    {
                        "type": item.get("type"),
                        "keys": sorted(str(key) for key in item),
                    }
                )
            else:
                content_shapes.append({"python_type": type(item).__name__})

    structured = data.get("structuredContent")
    structured_keys = sorted(str(key) for key in structured) if isinstance(structured, dict) else []
    return {
        "isError": data.get("isError", False),
        "content_items": len(content) if isinstance(content, list) else 0,
        "content_shapes": content_shapes,
        "structuredContent_keys": structured_keys,
    }


async def call_and_record(session: Any, tool_name: str, arguments: dict[str, Any]) -> ToolTestResult:
    """Call a tool and return a compact pass/fail record."""
    print(f"\nTesting {tool_name} with arguments: {json.dumps(arguments, sort_keys=True)}")
    try:
        result = await session.call_tool(tool_name, arguments)
    except Exception as exc:
        print(f"FAIL {tool_name}: {exc}")
        return ToolTestResult(tool_name=tool_name, arguments=arguments, status="fail", error=str(exc))

    shape = describe_result_shape(result)
    observed_fields = sorted(collect_keys(safe_model_dump(result)))
    status = "fail" if shape.get("isError") else "pass"
    print(f"{status.upper()} {tool_name}: {json.dumps(shape, sort_keys=True)}")
    return ToolTestResult(
        tool_name=tool_name,
        arguments=arguments,
        status=status,
        result_shape=shape,
        observed_fields=observed_fields,
    )


def input_schema_properties(tool_catalog: dict[str, dict[str, Any]], tool_name: str) -> set[str]:
    """Return top-level input schema property names for a listed MCP tool."""
    schema = tool_catalog.get(tool_name, {}).get("inputSchema", {})
    if not isinstance(schema, dict):
        return set()
    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        return set()
    return {str(key) for key in properties}


def yes_no(value: bool) -> str:
    """Format booleans for the report."""
    return "yes" if value else "no"


def build_report(
    config: GmailDockerMcpEnvironment,
    tool_catalog: dict[str, dict[str, Any]],
    results: list[ToolTestResult],
) -> str:
    """Build the Markdown report requested by the implementation plan."""
    result_by_tool = {result.tool_name: result for result in results}
    list_fields = set(result_by_tool.get("listMessages", ToolTestResult("", {}, "")).observed_fields)
    find_fields = set(result_by_tool.get("findMessage", ToolTestResult("", {}, "")).observed_fields)
    send_fields = set(result_by_tool.get("sendMessage", ToolTestResult("", {}, "")).observed_fields)
    all_message_fields = list_fields | find_fields

    body_fields = {"body", "text", "html", "content"}
    sender_fields = {"from", "sender", "senderEmail", "sender_email"}
    subject_fields = {"subject"}
    date_fields = {"date", "receivedAt", "received_at", "timestamp"}
    snippet_fields = {"snippet", "preview"}
    id_fields = {"id", "messageId", "message_id", "uid"}
    send_schema_properties = input_schema_properties(tool_catalog, "sendMessage")

    lines = [
        "# Gmail Docker MCP Test Report",
        "",
        f"- Executed at: {datetime.now(UTC).isoformat()}",
        f"- MCP image: `{config.gmail_mcp_image}`",
        f"- Email address configured: `{config.email_address}`",
        f"- IMAP: `{config.imap_host}:{config.imap_port}`",
        f"- SMTP: `{config.smtp_host}:{config.smtp_port}`",
        "",
        "## Tool Results",
        "",
        "| Tool | Input arguments | Result status | Returned schema/shape | Observed limitations |",
        "| --- | --- | --- | --- | --- |",
    ]

    for result in results:
        observed = ", ".join(result.observed_fields[:20]) or "none observed"
        if result.error:
            limitation = result.error.replace("|", "\\|")
        else:
            limitation = f"Observed fields: {observed}"
        lines.append(
            "| "
            + " | ".join(
                [
                    result.tool_name,
                    f"`{json.dumps(result.arguments, sort_keys=True)}`",
                    result.status,
                    f"`{json.dumps(result.result_shape, sort_keys=True)}`",
                    limitation,
                ]
            )
            + " |"
        )

    lines.extend(
        [
            "",
            "## Plan Questions",
            "",
            "- Does listMessages return full body, snippet, sender, subject, and date? "
            + (
                f"body={yes_no(bool(list_fields & body_fields))}, "
                f"snippet={yes_no(bool(list_fields & snippet_fields))}, "
                f"sender={yes_no(bool(list_fields & sender_fields))}, "
                f"subject={yes_no(bool(list_fields & subject_fields))}, "
                f"date={yes_no(bool(list_fields & date_fields))}."
            ),
            "- Does findMessage support Gmail search syntax reliably? "
            + (
                "The smoke test passed for `in:inbox`; run additional queries before relying on broader Gmail syntax."
                if result_by_tool.get("findMessage") and result_by_tool["findMessage"].status == "pass"
                else "Not proven because the smoke test did not pass."
            ),
            "- Does sendMessage support cc and bcc? "
            + f"cc={yes_no('cc' in send_schema_properties)}, bcc={yes_no('bcc' in send_schema_properties)} based on the MCP tool schema.",
            "- Does the MCP return message IDs or only message summaries? "
            + (
                "Message IDs were observed in returned fields."
                if all_message_fields & id_fields
                else "No obvious message ID field was observed in the smoke-test result shape."
            ),
            "- Did sendMessage return delivery metadata? "
            + (
                "Some send metadata was observed."
                if send_fields
                else "No structured send metadata was observed."
            ),
        ]
    )
    return "\n".join(lines) + "\n"


async def run() -> int:
    """Run all three Docker Gmail MCP smoke tests."""
    load_dotenv()
    print("\n=== Gmail Docker MCP Tool Test ===")

    try:
        config = run_preflight()
    except GmailDockerMcpPreflightError as exc:
        print(f"\nPREFLIGHT FAILED: {exc}")
        print("Required: Docker running, Gmail IMAP enabled, and Gmail App Password env vars configured.")
        return 2

    results: list[ToolTestResult] = []
    tool_catalog: dict[str, dict[str, Any]] = {}
    async with gmail_docker_mcp_session(config) as session:
        listed_tools = await session.list_tools()
        tool_catalog = {
            tool.name: tool.model_dump(mode="json", by_alias=True)
            for tool in listed_tools.tools
        }
        missing_tools = [tool_name for tool_name in REQUIRED_TOOLS if tool_name not in tool_catalog]
        if missing_tools:
            print(f"\nPREFLIGHT FAILED: Docker MCP server did not expose: {', '.join(missing_tools)}")
            return 2

        results.append(await call_and_record(session, "listMessages", {"count": 5}))
        results.append(await call_and_record(session, "findMessage", {"query": "in:inbox"}))
        results.append(
            await call_and_record(
                session,
                "sendMessage",
                {
                    "to": config.test_send_to,
                    "subject": "Gmail Docker MCP test",
                    "body": "This is a test email sent through the Docker Gmail MCP server. Kindly ignore or delete it. Sent at " + datetime.now(UTC).isoformat(),
                },
            )
        )

    report = build_report(config, tool_catalog, results)
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(f"\nWrote test report: {REPORT_PATH}")

    if all(result.status == "pass" for result in results):
        print("\nALL GMAIL DOCKER MCP TOOL TESTS COMPLETED")
        return 0

    print("\nGMAIL DOCKER MCP TOOL TESTS FAILED")
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
