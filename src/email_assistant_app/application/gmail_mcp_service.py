"""Application service for Docker Gmail MCP operations."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any, Protocol

from email_assistant_app.application.approval_service import ApprovalService
from email_assistant_app.domain.action import ActionType
from email_assistant_app.domain.email import (
    EmailMessage,
    GmailListMessagesRequest,
    GmailSearchMessagesRequest,
    GmailSendMessageRequest,
    GmailSendMessageResponse,
)
from email_assistant_app.errors import ExternalServiceError
from email_assistant_app.integrations.mcp import gmail_docker_client
from email_assistant_app.integrations.mcp.gmail_docker_client import GmailDockerMcpEnvironment


class GmailMcpToolClient(Protocol):
    """Low-level Docker Gmail MCP calls used by the application service."""

    async def list_messages(self, count: int) -> Any: ...

    async def find_message(self, query: str) -> Any: ...

    async def send_message(
        self,
        to: str,
        subject: str,
        body: str,
        cc: str | None = None,
        bcc: str | None = None,
    ) -> Any: ...


class DockerGmailMcpToolClient:
    """Default tool client backed by the Docker stdio MCP server."""

    def __init__(self, config: GmailDockerMcpEnvironment | None = None) -> None:
        self.config = config

    async def list_messages(self, count: int) -> Any:
        """Call the Docker MCP listMessages tool."""
        return await gmail_docker_client.list_messages(count, config=self.config)

    async def find_message(self, query: str) -> Any:
        """Call the Docker MCP findMessage tool."""
        return await gmail_docker_client.find_message(query, config=self.config)

    async def send_message(
        self,
        to: str,
        subject: str,
        body: str,
        cc: str | None = None,
        bcc: str | None = None,
    ) -> Any:
        """Call the Docker MCP sendMessage tool."""
        return await gmail_docker_client.send_message(
            to=to,
            subject=subject,
            body=body,
            cc=cc,
            bcc=bcc,
            config=self.config,
        )


class GmailMcpService:
    """Normalize Docker Gmail MCP responses for the FastAPI app."""

    def __init__(
        self,
        approval_service: ApprovalService,
        tool_client: GmailMcpToolClient | None = None,
    ) -> None:
        self.approval_service = approval_service
        self.tool_client = tool_client or DockerGmailMcpToolClient()

    async def list_messages(self, request: GmailListMessagesRequest) -> list[EmailMessage]:
        """Return recent Gmail messages through Docker MCP."""
        result = await self.tool_client.list_messages(request.count)
        payload = parse_mcp_json_payload(result)
        return parse_message_list(payload, primary_key="messages")

    async def search_messages(self, request: GmailSearchMessagesRequest) -> list[EmailMessage]:
        """Search Gmail messages through Docker MCP."""
        result = await self.tool_client.find_message(request.query)
        payload = parse_mcp_json_payload(result)
        return parse_message_list(payload, primary_key="foundMessages", fallback_key="messages")

    async def send_message(self, request: GmailSendMessageRequest) -> GmailSendMessageResponse:
        """Send a simple email through Docker MCP after approval."""
        payload = request.model_dump(mode="json", exclude={"approval_id"})
        self.approval_service.require_approved(ActionType.SEND_EMAIL, payload, request.approval_id)

        result = await self.tool_client.send_message(
            to=request.to,
            subject=request.subject,
            body=request.body,
            cc=_join_optional_recipients(request.cc),
            bcc=_join_optional_recipients(request.bcc),
        )
        response_payload = parse_mcp_json_payload(result)
        return GmailSendMessageResponse(
            provider_message_id=_optional_str(response_payload.get("messageId")),
            message=_optional_str(response_payload.get("message")),
            status="sent" if response_payload.get("success") is True else "unknown",
        )


def parse_mcp_json_payload(result: Any) -> dict[str, Any]:
    """Extract the JSON object returned as text by the Docker Gmail MCP tools."""
    data = _dump_model(result)
    if not isinstance(data, dict):
        raise ExternalServiceError("Gmail MCP returned an unexpected response type.")
    if data.get("isError"):
        raise ExternalServiceError("Gmail MCP returned an error response.", details={"response": _safe_response(data)})

    for item in data.get("content") or []:
        item_data = _dump_model(item)
        text = item_data.get("text") if isinstance(item_data, dict) else getattr(item, "text", None)
        if not text:
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ExternalServiceError("Gmail MCP returned non-JSON text content.") from exc
        if not isinstance(payload, dict):
            raise ExternalServiceError("Gmail MCP JSON payload must be an object.")
        return payload

    raise ExternalServiceError("Gmail MCP response did not include text JSON content.")


def parse_message_list(payload: dict[str, Any], primary_key: str, fallback_key: str | None = None) -> list[EmailMessage]:
    """Parse a Docker MCP message list payload."""
    raw_messages = payload.get(primary_key)
    if raw_messages is None and fallback_key:
        raw_messages = payload.get(fallback_key)
    if raw_messages is None:
        raw_messages = []
    if isinstance(raw_messages, dict):
        raw_messages = [raw_messages]
    if not isinstance(raw_messages, list):
        raise ExternalServiceError(
            "Gmail MCP message payload must be a list or object.",
            details={"key": primary_key, "payload_type": type(raw_messages).__name__},
        )
    return [parse_mcp_message(message) for message in raw_messages]


def parse_mcp_message(message: Any) -> EmailMessage:
    """Normalize one Docker MCP message object."""
    if not isinstance(message, dict):
        raise ExternalServiceError("Gmail MCP message item must be an object.")

    message_id = _required_str(message.get("id") or message.get("messageId"), "id")
    thread_id = _optional_str(message.get("threadId")) or message_id
    return EmailMessage(
        message_id=message_id,
        thread_id=thread_id,
        sender=_optional_str(message.get("from") or message.get("sender")) or "",
        recipients=[],
        subject=_optional_str(message.get("subject")) or "",
        body=_optional_str(message.get("body") or message.get("content") or message.get("text")) or "",
        received_at=_parse_datetime(message.get("date")),
        snippet=_optional_str(message.get("snippet")),
    )


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    raw_value = str(value)
    try:
        parsed = parsedate_to_datetime(raw_value)
    except (TypeError, ValueError):
        try:
            parsed = datetime.fromisoformat(raw_value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo:
        return parsed
    return parsed.replace(tzinfo=UTC)


def _join_optional_recipients(values: list[str]) -> str | None:
    recipients = [value.strip() for value in values if value.strip()]
    if not recipients:
        return None
    return ", ".join(recipients)


def _required_str(value: Any, field_name: str) -> str:
    raw_value = _optional_str(value)
    if not raw_value:
        raise ExternalServiceError("Gmail MCP message is missing a required field.", details={"field": field_name})
    return raw_value


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _dump_model(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", by_alias=True)
    return value


def _safe_response(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "isError": data.get("isError"),
        "content_count": len(data.get("content") or []),
    }
