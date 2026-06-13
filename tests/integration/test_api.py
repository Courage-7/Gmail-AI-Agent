import httpx
import pytest

from email_assistant_app.application.approval_service import ApprovalService
from email_assistant_app.application.dependencies import get_approval_service, get_gmail_mcp_service
from email_assistant_app.domain.action import ActionType
from email_assistant_app.domain.email import EmailMessage, GmailSendMessageResponse
from email_assistant_app.settings import get_settings

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class FakeGmailMcpService:
    def __init__(self, approval_service: ApprovalService) -> None:
        self.approval_service = approval_service
        self.sent_payloads: list[dict] = []

    async def list_messages(self, request) -> list[EmailMessage]:
        return [
            EmailMessage(
                message_id="m1",
                thread_id="m1",
                sender="Sender <sender@example.com>",
                subject="Hello",
                body="",
                snippet="Snippet",
            )
        ]

    async def search_messages(self, request) -> list[EmailMessage]:
        return [
            EmailMessage(
                message_id="m2",
                thread_id="m2",
                sender="Other <other@example.com>",
                subject=f"Query: {request.query}",
                body="",
                snippet="Found",
            )
        ]

    async def send_message(self, request) -> GmailSendMessageResponse:
        payload = request.model_dump(mode="json", exclude={"approval_id"})
        self.approval_service.require_approved(ActionType.SEND_EMAIL, payload, request.approval_id)
        self.sent_payloads.append(payload)
        return GmailSendMessageResponse(provider_message_id="sent-1", message="sent", status="sent")


@pytest.fixture
async def test_client(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "")
    monkeypatch.setenv("GROQ_MODEL", "openai/gpt-oss-120b")
    monkeypatch.setenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
    monkeypatch.setenv("SUPABASE_URL", "")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "")
    monkeypatch.setenv("EMAIL_ADDRESS", "")
    monkeypatch.setenv("EMAIL_PASSWORD", "")
    monkeypatch.setenv("IMAP_HOST", "imap.gmail.com")
    monkeypatch.setenv("IMAP_PORT", "993")
    monkeypatch.setenv("SMTP_HOST", "smtp.gmail.com")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("GMAIL_MCP_IMAGE", "yashtekwani/gmail-mcp")
    monkeypatch.setenv("TEST_SEND_TO", "")
    get_settings.cache_clear()

    from email_assistant_app.main import app

    approval_service = ApprovalService()
    gmail_service = FakeGmailMcpService(approval_service)

    async def override_approval_service() -> ApprovalService:
        return approval_service

    async def override_gmail_service() -> FakeGmailMcpService:
        return gmail_service

    app.dependency_overrides[get_approval_service] = override_approval_service
    app.dependency_overrides[get_gmail_mcp_service] = override_gmail_service
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client, gmail_service
    app.dependency_overrides.clear()


async def test_health_endpoint(test_client) -> None:
    client, _ = test_client

    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_capabilities_endpoint(test_client) -> None:
    client, _ = test_client

    response = await client.get("/capabilities")

    assert response.status_code == 200
    body = response.json()
    assert body["features"] == [
        "fastapi_email_agent_chat",
        "supabase_conversation_memory",
        "docker_gmail_mcp_list_messages",
        "docker_gmail_mcp_find_message",
        "approved_docker_gmail_mcp_send_message",
        "workflow_builder_node_registry",
        "workflow_builder_validation",
        "workflow_builder_preview_run",
    ]
    assert body["configuration"]["agent_configured"] is False
    assert body["configuration"]["llm_provider"] == "groq"
    assert body["configuration"]["llm_model"] == "openai/gpt-oss-120b"
    assert body["configuration"]["llm_configured"] is False
    assert body["configuration"]["gmail_docker_mcp_configured"] is False


async def test_list_messages_endpoint(test_client) -> None:
    client, _ = test_client

    response = await client.post("/gmail/messages/list", json={"count": 5})

    assert response.status_code == 200
    assert response.json()[0]["message_id"] == "m1"


async def test_search_messages_endpoint(test_client) -> None:
    client, _ = test_client

    response = await client.post("/gmail/messages/search", json={"query": "in:inbox"})

    assert response.status_code == 200
    assert response.json()[0]["subject"] == "Query: in:inbox"


async def test_send_message_requires_approval_then_sends(test_client) -> None:
    client, gmail_service = test_client
    payload = {
        "to": "to@example.com",
        "subject": "Hello",
        "body": "Body",
        "cc": [],
        "bcc": [],
    }

    first_response = await client.post("/gmail/messages/send", json=payload)

    assert first_response.status_code == 409
    first_body = first_response.json()
    assert first_body["error"]["code"] == "approval_required"
    assert first_body["error"]["details"]["approval"]["action_type"] == "send_email"
    assert gmail_service.sent_payloads == []

    approval_id = first_body["error"]["details"]["approval"]["approval_id"]
    approval_response = await client.post("/approvals/resume", json={"approval_id": approval_id, "approved": True})
    assert approval_response.status_code == 200

    second_response = await client.post("/gmail/messages/send", json={**payload, "approval_id": approval_id})

    assert second_response.status_code == 200
    assert second_response.json()["provider_message_id"] == "sent-1"
    assert gmail_service.sent_payloads == [payload]


async def test_workflow_node_types_endpoint(test_client) -> None:
    client, _ = test_client

    response = await client.get("/workflow-node-types")

    assert response.status_code == 200
    body = response.json()
    node_types = {item["type"]: item for item in body}
    assert set(node_types) == {
        "input.manual",
        "llm.chat",
        "gmail.search_messages",
        "condition.contains",
        "output.final",
    }
    assert node_types["gmail.search_messages"]["category"] == "mcp_tool"
    assert node_types["gmail.search_messages"]["configSchema"][0]["name"] == "query"
    assert node_types["llm.chat"]["defaultConfig"]["userPrompt"] == "{{input.manual.request}}"


async def test_workflow_validate_accepts_starter_graph(test_client) -> None:
    client, _ = test_client

    response = await client.post("/workflows/validate", json=_starter_workflow())

    assert response.status_code == 200
    body = response.json()
    assert body == {"valid": True, "errors": [], "warnings": []}


async def test_workflow_validate_rejects_unsupported_node_type(test_client) -> None:
    client, _ = test_client
    workflow = _starter_workflow()
    workflow["nodes"][1]["data"]["nodeType"] = "browser.exec"

    response = await client.post("/workflows/validate", json=workflow)

    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is False
    assert body["errors"][0]["code"] == "unsupported_node_type"
    assert body["errors"][0]["node_id"] == "starter-llm"


async def test_workflow_validate_rejects_cycles_and_frontend_secrets(test_client) -> None:
    client, _ = test_client
    workflow = _starter_workflow()
    workflow["nodes"][1]["data"]["config"]["apiKey"] = "not-allowed"
    workflow["edges"].append(
        {
            "id": "starter-output-starter-llm",
            "source": "starter-output",
            "target": "starter-llm",
        }
    )

    response = await client.post("/workflows/validate", json=workflow)

    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is False
    codes = {error["code"] for error in body["errors"]}
    assert "frontend_secret_config_not_allowed" in codes
    assert "output_node_has_outgoing_edge" in codes
    assert "workflow_cycle_detected" in codes


async def test_workflow_run_returns_preview_steps(test_client) -> None:
    client, _ = test_client

    response = await client.post("/workflows/run", json=_starter_workflow())

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["valid"] is True
    assert [step["node_type"] for step in body["steps"]] == ["input.manual", "llm.chat", "output.final"]
    assert body["steps"][1]["summary"] == "Generated preview LLM response"
    assert body["result"]["result"]["text"].startswith("Preview response for:")


async def test_workflow_run_returns_validation_errors(test_client) -> None:
    client, _ = test_client
    workflow = _starter_workflow()
    workflow["nodes"][1]["data"]["config"]["userPrompt"] = ""

    response = await client.post("/workflows/run", json=workflow)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "blocked"
    assert body["valid"] is False
    assert body["steps"] == []
    assert body["validation"]["errors"][0]["code"] == "missing_required_config"


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/skills"),
        ("GET", "/agent-capabilities"),
        ("GET", "/tools/gmail-mcp"),
        ("POST", "/inbox/triage/recent"),
        ("POST", "/inbox/labels/apply"),
        ("POST", "/digest/daily"),
        ("POST", "/actions/reply/send"),
        ("POST", "/actions/calendar/availability"),
    ],
)
async def test_unsupported_routes_are_removed(test_client, method: str, path: str) -> None:
    client, _ = test_client

    response = await client.request(method, path, json={})

    assert response.status_code == 404


def _starter_workflow() -> dict:
    return {
        "id": "starter",
        "name": "Starter workflow",
        "version": 1,
        "nodes": [
            {
                "id": "starter-input",
                "type": "workflowNode",
                "position": {"x": 80, "y": 120},
                "data": {
                    "label": "Manual Input",
                    "nodeType": "input.manual",
                    "config": {
                        "inputName": "request",
                        "sampleValue": "Summarize my latest important email.",
                    },
                },
            },
            {
                "id": "starter-llm",
                "type": "workflowNode",
                "position": {"x": 360, "y": 120},
                "data": {
                    "label": "LLM Chat",
                    "nodeType": "llm.chat",
                    "config": {
                        "systemPrompt": "You are a careful email workflow assistant.",
                        "userPrompt": "{{input.manual.request}}",
                    },
                },
            },
            {
                "id": "starter-output",
                "type": "workflowNode",
                "position": {"x": 660, "y": 120},
                "data": {
                    "label": "Final Output",
                    "nodeType": "output.final",
                    "config": {"outputName": "result"},
                },
            },
        ],
        "edges": [
            {
                "id": "starter-input-starter-llm",
                "source": "starter-input",
                "target": "starter-llm",
            },
            {
                "id": "starter-llm-starter-output",
                "source": "starter-llm",
                "target": "starter-output",
            },
        ],
    }
