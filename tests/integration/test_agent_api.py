import httpx
import pytest

from email_assistant_app.agent.service import EmailAgentService, InMemoryAgentStateStore
from email_assistant_app.application.approval_service import ApprovalService
from email_assistant_app.application.dependencies import get_email_agent_service
from email_assistant_app.settings import get_settings
from tests.fakes import FakeAgentLlm, FakeGmailMcpService, FakeMemoryStore

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def agent_client(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "")
    monkeypatch.setenv("GROQ_MODEL", "openai/gpt-oss-120b")
    monkeypatch.setenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
    monkeypatch.setenv("SUPABASE_URL", "")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "")
    get_settings.cache_clear()

    from email_assistant_app.main import app

    approval_service = ApprovalService()
    gmail_service = FakeGmailMcpService(approval_service)
    memory_store = FakeMemoryStore()
    agent_service = EmailAgentService(
        gmail_service=gmail_service,
        memory_store=memory_store,
        llm=FakeAgentLlm(),
        approval_service=approval_service,
        state_store=InMemoryAgentStateStore(),
    )

    async def override_agent_service() -> EmailAgentService:
        return agent_service

    app.dependency_overrides[get_email_agent_service] = override_agent_service
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client, memory_store, gmail_service
    app.dependency_overrides.clear()


async def test_create_agent_session_endpoint(agent_client) -> None:
    client, _, _ = agent_client

    response = await client.post("/agent/sessions", json={"user_id": "local-user", "title": "Inbox"})

    assert response.status_code == 200
    assert response.json() == {"session_id": "session-1", "user_id": "local-user", "title": "Inbox"}


async def test_list_agent_sessions_endpoint(agent_client) -> None:
    client, _, _ = agent_client
    await client.post("/agent/sessions", json={"user_id": "local-user", "title": "Inbox"})
    await client.post("/agent/sessions", json={"user_id": "local-user", "title": "Follow ups"})

    response = await client.get("/agent/sessions", params={"user_id": "local-user"})

    assert response.status_code == 200
    body = response.json()
    assert [session["session_id"] for session in body["sessions"]] == ["session-2", "session-1"]
    assert body["sessions"][0]["title"] == "Follow ups"


async def test_agent_chat_auto_creates_session_when_missing(agent_client) -> None:
    client, memory_store, _ = agent_client

    response = await client.post(
        "/agent/chat",
        json={"user_id": "local-user", "message": "hello"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["session_id"] == "session-1"
    assert body["intent"] == "general_chat"
    assert memory_store.sessions[0]["title"] == "Swagger Chat"


async def test_agent_chat_summarizes_inbox(agent_client) -> None:
    client, memory_store, _ = agent_client
    session = (await client.post("/agent/sessions", json={"user_id": "local-user"})).json()

    response = await client.post(
        "/agent/chat",
        json={
            "session_id": session["session_id"],
            "user_id": session["user_id"],
            "message": "Summarize my latest emails",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "summarize_inbox"
    assert body["pending_send"] is False
    assert "Exam.net setup" in body["message"]
    assert body["data"]["summary"]["items"][0]["subject"] == "Exam.net setup"
    assert memory_store.messages[-1]["metadata"]["data"] == body["data"]
    assert memory_store.tool_events[0]["tool_name"] == "list_messages"


async def test_agent_chat_search_draft_revise_send_cancel_and_missing_recipient(agent_client) -> None:
    client, memory_store, gmail_service = agent_client
    session = (await client.post("/agent/sessions", json={"user_id": "local-user"})).json()
    payload = {"session_id": session["session_id"], "user_id": session["user_id"]}

    search = await client.post("/agent/chat", json={**payload, "message": "Find emails about Exam.net"})
    followup = await client.post("/agent/chat", json={**payload, "message": "Summarize the second one"})
    draft = await client.post("/agent/chat", json={**payload, "message": "Draft a reply to Derek"})
    revise = await client.post("/agent/chat", json={**payload, "message": "Make it more formal"})
    send = await client.post("/agent/chat", json={**payload, "message": "Send it"})

    assert search.status_code == 200
    assert search.json()["intent"] == "search_email"
    assert search.json()["data"]["summary"]["items"][0]["message_id"] == "m3"
    assert followup.json()["intent"] == "summarize_inbox"
    assert "Derek result" in followup.json()["message"]
    assert draft.json()["pending_send"] is True
    assert draft.json()["draft"]["to"] == "derek@example.com"
    assert draft.json()["data"]["draft_status"] == "pending_confirmation"
    assert "Dear recipient" in revise.json()["draft"]["body"]
    assert revise.json()["data"]["draft_status"] == "revised"
    assert send.json()["message"] == "Sent the email."
    assert send.json()["data"]["draft_status"] == "sent"
    assert send.json()["data"]["send_result"]["sent"] is True
    assert gmail_service.sent_payloads[0]["to"] == "derek@example.com"
    assert memory_store.send_events[0]["sent"] is True

    await client.post("/agent/chat", json={**payload, "message": "Draft a reply to Derek"})
    cancel = await client.post("/agent/chat", json={**payload, "message": "Cancel sending"})
    assert cancel.json()["intent"] == "cancel_send"
    assert cancel.json()["pending_send"] is False
    assert cancel.json()["data"]["draft_status"] == "cancelled"

    new_session = (await client.post("/agent/sessions", json={"user_id": "local-user"})).json()
    missing = await client.post(
        "/agent/chat",
        json={
            "session_id": new_session["session_id"],
            "user_id": new_session["user_id"],
            "message": "Draft an email to Derek saying hello",
        },
    )
    assert missing.json()["pending_send"] is False
    assert missing.json()["draft"]["missing_fields"] == ["to"]
    assert missing.json()["data"]["draft_status"] == "missing_fields"
    assert missing.json()["data"]["missing_fields"] == ["to"]
