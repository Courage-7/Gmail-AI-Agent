import json

import pytest

from email_assistant_app.application.approval_service import ApprovalService
from email_assistant_app.application.gmail_mcp_service import (
    GmailMcpService,
    parse_mcp_json_payload,
    parse_mcp_message,
    parse_message_list,
)
from email_assistant_app.domain.action import ActionType, ResumeApprovalRequest
from email_assistant_app.domain.email import (
    GmailListMessagesRequest,
    GmailSearchMessagesRequest,
    GmailSendMessageRequest,
)
from email_assistant_app.errors import ApprovalRequiredError, ExternalServiceError

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def mcp_result(payload: dict, is_error: bool = False) -> dict:
    return {
        "isError": is_error,
        "content": [{"type": "text", "text": json.dumps(payload)}],
        "structuredContent": None,
    }


class FakeToolClient:
    def __init__(self) -> None:
        self.sent_calls: list[dict] = []

    async def list_messages(self, count: int):
        return mcp_result(
            {
                "success": True,
                "messages": [
                    {
                        "id": "m1",
                        "from": "Sender <sender@example.com>",
                        "subject": "Hello",
                        "snippet": "Snippet",
                        "date": "Fri, 01 May 2026 12:00:00 +0000",
                    }
                ],
            }
        )

    async def find_message(self, query: str):
        return mcp_result(
            {
                "success": True,
                "foundMessages": [
                    {
                        "id": "m2",
                        "from": "Other <other@example.com>",
                        "subject": "Search hit",
                        "snippet": "Found",
                        "date": "2026-05-01T12:00:00+00:00",
                    }
                ],
            }
        )

    async def send_message(self, to: str, subject: str, body: str, cc: str | None = None, bcc: str | None = None):
        self.sent_calls.append({"to": to, "subject": subject, "body": body, "cc": cc, "bcc": bcc})
        return mcp_result({"success": True, "message": "sent", "messageId": "sent-1"})


async def test_list_messages_parses_mcp_payload() -> None:
    service = GmailMcpService(ApprovalService(), FakeToolClient())

    messages = await service.list_messages(GmailListMessagesRequest(count=5))

    assert len(messages) == 1
    assert messages[0].message_id == "m1"
    assert messages[0].thread_id == "m1"
    assert messages[0].sender == "Sender <sender@example.com>"
    assert messages[0].subject == "Hello"
    assert messages[0].snippet == "Snippet"
    assert messages[0].received_at is not None


async def test_search_messages_parses_found_messages_payload() -> None:
    service = GmailMcpService(ApprovalService(), FakeToolClient())

    messages = await service.search_messages(GmailSearchMessagesRequest(query="in:inbox"))

    assert len(messages) == 1
    assert messages[0].message_id == "m2"
    assert messages[0].subject == "Search hit"


def test_parse_message_list_accepts_single_message_object() -> None:
    messages = parse_message_list(
        {
            "foundMessages": {
                "id": "m3",
                "from": "Other <other@example.com>",
                "subject": "Single hit",
            }
        },
        primary_key="foundMessages",
    )

    assert len(messages) == 1
    assert messages[0].message_id == "m3"
    assert messages[0].subject == "Single hit"


async def test_send_message_requires_approval_before_provider_call() -> None:
    approval_service = ApprovalService()
    tool_client = FakeToolClient()
    service = GmailMcpService(approval_service, tool_client)
    request = GmailSendMessageRequest(to="to@example.com", subject="Hello", body="Body")

    with pytest.raises(ApprovalRequiredError):
        await service.send_message(request)

    assert tool_client.sent_calls == []


async def test_send_message_calls_provider_after_approval() -> None:
    approval_service = ApprovalService()
    tool_client = FakeToolClient()
    service = GmailMcpService(approval_service, tool_client)
    request = GmailSendMessageRequest(
        to="to@example.com",
        subject="Hello",
        body="Body",
        cc=["cc@example.com"],
        bcc=["bcc@example.com"],
    )
    payload = request.model_dump(mode="json", exclude={"approval_id"})
    approval = approval_service.create(ActionType.SEND_EMAIL, payload)
    approval_service.resume(ResumeApprovalRequest(approval_id=approval.approval_id, approved=True))

    response = await service.send_message(request.model_copy(update={"approval_id": approval.approval_id}))

    assert response.provider_message_id == "sent-1"
    assert response.status == "sent"
    assert tool_client.sent_calls == [
        {
            "to": "to@example.com",
            "subject": "Hello",
            "body": "Body",
            "cc": "cc@example.com",
            "bcc": "bcc@example.com",
        }
    ]


def test_parse_mcp_json_payload_rejects_invalid_json() -> None:
    with pytest.raises(ExternalServiceError):
        parse_mcp_json_payload({"isError": False, "content": [{"type": "text", "text": "not-json"}]})


def test_parse_message_list_rejects_non_list_payload() -> None:
    with pytest.raises(ExternalServiceError):
        parse_message_list({"messages": "not-a-message-list"}, primary_key="messages")


def test_parse_mcp_message_requires_id() -> None:
    with pytest.raises(ExternalServiceError):
        parse_mcp_message({"subject": "missing id"})
