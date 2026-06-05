"""Live-service LangGraph Studio graph for credential-backed testing."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from email_assistant_app.agent.graph import build_email_agent_graph
from email_assistant_app.agent.llm import EmailAgentLlm
from email_assistant_app.agent.nodes import EmailAgentRuntime
from email_assistant_app.application.approval_service import ApprovalService
from email_assistant_app.application.gmail_mcp_service import DockerGmailMcpToolClient, GmailMcpService
from email_assistant_app.errors import ConfigurationError
from email_assistant_app.integrations.mcp.gmail_docker_client import GmailDockerMcpEnvironment
from email_assistant_app.memory.supabase_store import SupabaseMemoryStore
from email_assistant_app.settings import get_settings


def make_graph(config: dict[str, Any] | None = None) -> Any:
    """Build the real graph from `.env` settings for Studio."""
    settings = get_settings()
    approval_service = ApprovalService()
    runtime = EmailAgentRuntime(
        gmail_service=GmailMcpService(
            approval_service=approval_service,
            tool_client=DockerGmailMcpToolClient(
                GmailDockerMcpEnvironment(
                    email_address=_required(settings.email_address, "EMAIL_ADDRESS"),
                    email_password=_required(settings.email_password, "EMAIL_PASSWORD"),
                    imap_host=settings.imap_host,
                    imap_port=str(settings.imap_port),
                    smtp_host=settings.smtp_host,
                    smtp_port=str(settings.smtp_port),
                    gmail_mcp_image=settings.gmail_mcp_image,
                    test_send_to=_required(settings.test_send_to, "TEST_SEND_TO"),
                )
            ),
        ),
        memory_store=SupabaseMemoryStore(
            _required(settings.supabase_url, "SUPABASE_URL"),
            _required(settings.supabase_service_role_key, "SUPABASE_SERVICE_ROLE_KEY"),
        ),
        llm=EmailAgentLlm(
            api_key=_required(settings.groq_api_key, "GROQ_API_KEY"),
            model=settings.groq_model,
            base_url=settings.groq_base_url,
        ),
        approval_service=approval_service,
    )
    return build_email_agent_graph(runtime)


def _required(value: str | None, env_name: str) -> str:
    if not value:
        raise ConfigurationError("Studio real graph is missing required environment.", {"required_env": [env_name]})
    return value
