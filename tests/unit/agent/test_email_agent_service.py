import pytest

from email_assistant_app.agent.service import EmailAgentService, InMemoryAgentStateStore
from email_assistant_app.application.approval_service import ApprovalService
from email_assistant_app.domain.agent import AgentChatRequest, AgentSessionCreateRequest
from tests.fakes import FakeAgentLlm, FakeGmailMcpService, FakeMemoryStore

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def agent_stack():
    approval_service = ApprovalService()
    gmail_service = FakeGmailMcpService(approval_service)
    memory_store = FakeMemoryStore()
    service = EmailAgentService(
        gmail_service=gmail_service,
        memory_store=memory_store,
        llm=FakeAgentLlm(),
        approval_service=approval_service,
        state_store=InMemoryAgentStateStore(),
    )
    return service, memory_store, gmail_service


async def test_create_session_persists_session(agent_stack) -> None:
    service, _, _ = agent_stack

    response = await service.create_session(AgentSessionCreateRequest(user_id="local-user", title="Inbox"))

    assert response.session_id == "session-1"
    assert response.user_id == "local-user"
    assert response.title == "Inbox"


async def test_summarize_inbox_uses_list_messages_and_saves_memory(agent_stack) -> None:
    service, memory_store, gmail_service = agent_stack
    session = await service.create_session(AgentSessionCreateRequest())

    response = await service.chat(
        AgentChatRequest(
            session_id=session.session_id,
            user_id=session.user_id,
            message="Summarize my latest emails",
        )
    )

    assert response.intent == "summarize_inbox"
    assert response.pending_send is False
    assert "Exam.net setup" in response.message
    assert response.data["summary"]["items"][0]["rank"] == 1
    assert response.data["summary"]["items"][0]["subject"] == "Exam.net setup"
    assert "body" not in response.data["summary"]["items"][0]
    assert gmail_service.list_calls == 1
    assert [message["role"] for message in memory_store.messages] == ["user", "assistant"]
    assert memory_store.messages[-1]["metadata"]["data"] == response.data
    assert memory_store.tool_events[0]["tool_name"] == "list_messages"


async def test_search_followup_can_reference_second_result(agent_stack) -> None:
    service, _, gmail_service = agent_stack
    session = await service.create_session(AgentSessionCreateRequest())

    search_response = await service.chat(
        AgentChatRequest(session_id=session.session_id, user_id=session.user_id, message="Find emails about Exam.net")
    )
    followup_response = await service.chat(
        AgentChatRequest(session_id=session.session_id, user_id=session.user_id, message="Summarize the second one")
    )

    assert search_response.intent == "search_email"
    assert search_response.data["summary"]["items"][0]["subject"] == "Exam.net result for Exam.net"
    assert gmail_service.search_calls == ["Exam.net"]
    assert "Derek result" in followup_response.message
    assert followup_response.data["summary"]["items"][0]["rank"] == 1
    assert gmail_service.list_calls == 0


async def test_search_failure_returns_diagnostic_response() -> None:
    class FailingSearchGmailService(FakeGmailMcpService):
        async def search_messages(self, request):
            raise RuntimeError("Gmail MCP returned an error response.")

    approval_service = ApprovalService()
    memory_store = FakeMemoryStore()
    service = EmailAgentService(
        gmail_service=FailingSearchGmailService(approval_service),
        memory_store=memory_store,
        llm=FakeAgentLlm(),
        approval_service=approval_service,
        state_store=InMemoryAgentStateStore(),
    )
    session = await service.create_session(AgentSessionCreateRequest())

    response = await service.chat(
        AgentChatRequest(session_id=session.session_id, user_id=session.user_id, message="Find AWS Hackathon updates")
    )

    assert response.intent == "search_email"
    assert response.data["error"]["tool"] == "find_message"
    assert response.data["error"]["message"] == "Gmail MCP returned an error response."
    assert "I could not search Gmail" in response.message
    assert memory_store.tool_events[0]["success"] is False


async def test_draft_revision_confirmation_send_flow(agent_stack) -> None:
    service, memory_store, gmail_service = agent_stack
    session = await service.create_session(AgentSessionCreateRequest())
    await service.chat(
        AgentChatRequest(session_id=session.session_id, user_id=session.user_id, message="Find emails from Derek")
    )

    draft_response = await service.chat(
        AgentChatRequest(session_id=session.session_id, user_id=session.user_id, message="Draft a reply to Derek")
    )
    revise_response = await service.chat(
        AgentChatRequest(session_id=session.session_id, user_id=session.user_id, message="Make it more formal")
    )
    send_response = await service.chat(
        AgentChatRequest(session_id=session.session_id, user_id=session.user_id, message="Send it")
    )

    assert draft_response.intent == "draft_reply"
    assert draft_response.pending_send is True
    assert draft_response.draft["to"] == "derek@example.com"
    assert draft_response.data["draft_status"] == "pending_confirmation"
    assert "Please confirm" in draft_response.message
    assert revise_response.intent == "revise_draft"
    assert revise_response.data["draft_status"] == "revised"
    assert "Dear recipient" in revise_response.draft["body"]
    assert send_response.intent == "confirm_send"
    assert send_response.pending_send is False
    assert send_response.message == "Sent the email."
    assert send_response.data["draft_status"] == "sent"
    assert send_response.data["send_result"]["sent"] is True
    assert gmail_service.sent_payloads[0]["to"] == "derek@example.com"
    assert memory_store.send_events[0]["sent"] is True


async def test_cancel_pending_send(agent_stack) -> None:
    service, _, _ = agent_stack
    session = await service.create_session(AgentSessionCreateRequest())
    await service.chat(
        AgentChatRequest(session_id=session.session_id, user_id=session.user_id, message="Find emails from Derek")
    )
    await service.chat(
        AgentChatRequest(session_id=session.session_id, user_id=session.user_id, message="Draft a reply to Derek")
    )

    response = await service.chat(
        AgentChatRequest(session_id=session.session_id, user_id=session.user_id, message="Cancel sending")
    )

    assert response.intent == "cancel_send"
    assert response.pending_send is False
    assert response.message == "Cancelled the pending send."
    assert response.data["draft_status"] == "cancelled"


async def test_extract_tasks_returns_structured_data(agent_stack) -> None:
    service, _, gmail_service = agent_stack
    session = await service.create_session(AgentSessionCreateRequest())

    response = await service.chat(
        AgentChatRequest(session_id=session.session_id, user_id=session.user_id, message="Extract tasks from my inbox")
    )

    assert response.intent == "extract_tasks"
    assert response.data["tasks"]["source_count"] == 2
    assert response.data["tasks"]["items"][0]["task"] == "follow up on Exam.net."
    assert gmail_service.list_calls == 1


async def test_missing_recipient_email_is_not_pending(agent_stack) -> None:
    service, _, _ = agent_stack
    session = await service.create_session(AgentSessionCreateRequest())

    response = await service.chat(
        AgentChatRequest(
            session_id=session.session_id,
            user_id=session.user_id,
            message="Draft an email to Derek saying hello",
        )
    )

    assert response.intent == "draft_reply"
    assert response.pending_send is False
    assert response.draft["missing_fields"] == ["to"]
    assert response.data["draft_status"] == "missing_fields"
    assert response.data["missing_fields"] == ["to"]
    assert "to" in response.message


async def test_draft_uses_learned_style_and_does_not_persist_raw_sent_bodies(agent_stack) -> None:
    service, memory_store, gmail_service = agent_stack
    session = await service.create_session(AgentSessionCreateRequest())
    await service.chat(
        AgentChatRequest(session_id=session.session_id, user_id=session.user_id, message="Find emails from Derek")
    )

    response = await service.chat(
        AgentChatRequest(session_id=session.session_id, user_id=session.user_id, message="Draft a reply to Derek")
    )

    assert response.pending_send is True
    assert response.data["email_style_profile"]["signoff_style"] == "Best regards,"
    assert response.data["email_style_profile"]["confidence"] == "medium"
    assert response.draft["body"].startswith("Hi Derek,")
    assert response.draft["body"].endswith("Best regards,")
    assert "in:sent newer_than:180d" in gmail_service.search_calls
    sent_lookup_events = [
        event
        for event in memory_store.tool_events
        if event["tool_args"].get("query") == "in:sent newer_than:180d"
    ]
    assert sent_lookup_events
    assert "body" not in sent_lookup_events[0]["result_summary"]["messages"][0]
    assert "Thanks for the update. I will take care of it." not in str(response.data["email_style_profile"])


async def test_low_confidence_style_learning_asks_preference_then_resumes_draft() -> None:
    class LowConfidenceLlm(FakeAgentLlm):
        async def analyze_email_style(self, sent_emails):
            return {
                "tone": "unknown",
                "greeting_style": "",
                "signoff_style": "",
                "typical_length": "unknown",
                "structure": [],
                "common_phrasing": [],
                "confidence": "low",
            }

    approval_service = ApprovalService()
    gmail_service = FakeGmailMcpService(approval_service)
    memory_store = FakeMemoryStore()
    service = EmailAgentService(
        gmail_service=gmail_service,
        memory_store=memory_store,
        llm=LowConfidenceLlm(),
        approval_service=approval_service,
        state_store=InMemoryAgentStateStore(),
    )
    session = await service.create_session(AgentSessionCreateRequest())
    await service.chat(
        AgentChatRequest(session_id=session.session_id, user_id=session.user_id, message="Find emails from Derek")
    )

    preference_prompt = await service.chat(
        AgentChatRequest(session_id=session.session_id, user_id=session.user_id, message="Draft a reply to Derek")
    )
    resumed = await service.chat(
        AgentChatRequest(session_id=session.session_id, user_id=session.user_id, message="Cheers")
    )

    assert preference_prompt.pending_send is False
    assert preference_prompt.message == "What sign-off should I use for your emails?"
    assert preference_prompt.data["email_style_profile"]["confidence"] == "low"
    assert resumed.intent == "draft_reply"
    assert resumed.pending_send is True
    assert resumed.data["email_style_profile"]["source"] == "user_preference"
    assert resumed.draft["body"].endswith("Cheers,")


async def test_email_body_cleanup_removes_markdown_fences_and_duplicate_boundaries() -> None:
    class MessyDraftLlm(FakeAgentLlm):
        async def draft_email(
            self,
            user_message,
            selected_email,
            email_results,
            memory_context,
            email_style_profile,
        ):
            return {
                "to": "",
                "subject": "",
                "body": (
                    "```text\n"
                    "Hi Derek,\n\n"
                    "Hi Derek,\n\n"
                    "**Thanks** for the update.\n\n"
                    "Best regards,\n\n"
                    "Best regards,\n"
                    "```"
                ),
                "missing_fields": [],
            }

    approval_service = ApprovalService()
    gmail_service = FakeGmailMcpService(approval_service)
    memory_store = FakeMemoryStore()
    service = EmailAgentService(
        gmail_service=gmail_service,
        memory_store=memory_store,
        llm=MessyDraftLlm(),
        approval_service=approval_service,
        state_store=InMemoryAgentStateStore(),
    )
    session = await service.create_session(AgentSessionCreateRequest())
    await service.chat(
        AgentChatRequest(session_id=session.session_id, user_id=session.user_id, message="Find emails from Derek")
    )

    response = await service.chat(
        AgentChatRequest(session_id=session.session_id, user_id=session.user_id, message="Draft a reply to Derek")
    )

    assert "```" not in response.draft["body"]
    assert "**" not in response.draft["body"]
    assert response.draft["body"].count("Hi Derek,") == 1
    assert response.draft["body"].count("Best regards,") == 1


async def test_agent_message_cleanup_removes_json_fences_and_markdown() -> None:
    class MessyChatLlm(FakeAgentLlm):
        async def general_chat(self, user_message, memory_context):
            return '```json\n{"message": "**Clean** response"}\n```'

    approval_service = ApprovalService()
    gmail_service = FakeGmailMcpService(approval_service)
    memory_store = FakeMemoryStore()
    service = EmailAgentService(
        gmail_service=gmail_service,
        memory_store=memory_store,
        llm=MessyChatLlm(),
        approval_service=approval_service,
        state_store=InMemoryAgentStateStore(),
    )
    session = await service.create_session(AgentSessionCreateRequest())

    response = await service.chat(
        AgentChatRequest(session_id=session.session_id, user_id=session.user_id, message="hello")
    )

    assert response.message == "Clean response"


async def test_failed_send_is_logged_and_draft_stays_pending() -> None:
    class FailingGmailService(FakeGmailMcpService):
        async def send_message(self, request):
            raise RuntimeError("SMTP unavailable")

    approval_service = ApprovalService()
    memory_store = FakeMemoryStore()
    service = EmailAgentService(
        gmail_service=FailingGmailService(approval_service),
        memory_store=memory_store,
        llm=FakeAgentLlm(),
        approval_service=approval_service,
        state_store=InMemoryAgentStateStore(),
    )
    session = await service.create_session(AgentSessionCreateRequest())
    await service.chat(
        AgentChatRequest(session_id=session.session_id, user_id=session.user_id, message="Find emails from Derek")
    )
    await service.chat(
        AgentChatRequest(session_id=session.session_id, user_id=session.user_id, message="Draft a reply to Derek")
    )

    response = await service.chat(
        AgentChatRequest(session_id=session.session_id, user_id=session.user_id, message="Send it")
    )

    assert response.pending_send is True
    assert "SMTP unavailable" in response.message
    assert response.data["draft_status"] == "failed"
    assert response.data["send_result"]["sent"] is False
    assert response.data["send_result"]["error"] == "SMTP unavailable"
    assert memory_store.send_events[0]["confirmed"] is True
    assert memory_store.send_events[0]["sent"] is False
