"""FastAPI dependency factories."""

from __future__ import annotations

from functools import lru_cache

from email_assistant_app.agent.llm import EmailAgentLlm
from email_assistant_app.agent.service import EmailAgentService, InMemoryAgentStateStore
from email_assistant_app.application.approval_service import ApprovalService
from email_assistant_app.application.gmail_mcp_service import DockerGmailMcpToolClient, GmailMcpService
from email_assistant_app.application.workflow_execution import WorkflowPreviewRunner
from email_assistant_app.application.workflow_registry import WorkflowNodeRegistry
from email_assistant_app.application.workflow_validation import WorkflowValidator
from email_assistant_app.errors import ConfigurationError
from email_assistant_app.integrations.mcp.gmail_docker_client import GmailDockerMcpEnvironment
from email_assistant_app.memory.supabase_store import SupabaseMemoryStore
from email_assistant_app.settings import Settings, get_settings


@lru_cache
def _approval_service() -> ApprovalService:
    """Return the shared approval service."""
    return ApprovalService()


@lru_cache
def _agent_state_store() -> InMemoryAgentStateStore:
    """Return the shared transient agent state store."""
    return InMemoryAgentStateStore()


@lru_cache
def _workflow_node_registry() -> WorkflowNodeRegistry:
    """Return the shared workflow builder node registry."""
    return WorkflowNodeRegistry()


@lru_cache
def _workflow_validator() -> WorkflowValidator:
    """Return the shared workflow builder validator."""
    return WorkflowValidator(_workflow_node_registry())


@lru_cache
def _workflow_preview_runner() -> WorkflowPreviewRunner:
    """Return the shared workflow preview runner."""
    return WorkflowPreviewRunner(_workflow_validator())


def _supabase_memory_store(settings: Settings) -> SupabaseMemoryStore:
    """Build the Supabase memory store from runtime settings."""
    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise ConfigurationError(
            "Supabase memory is not configured.",
            details={"required_env": ["SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"]},
        )
    return SupabaseMemoryStore(settings.supabase_url, settings.supabase_service_role_key)


def _email_agent_llm(settings: Settings) -> EmailAgentLlm:
    """Build the LLM helper from runtime settings."""
    missing = [
        name
        for name, value in {
            "GROQ_API_KEY": settings.groq_api_key,
            "GROQ_MODEL": settings.groq_model,
            "GROQ_BASE_URL": settings.groq_base_url,
        }.items()
        if not value
    ]
    if missing:
        raise ConfigurationError(
            "LLM provider is not configured.",
            details={"provider": "groq", "required_env": missing},
        )
    return EmailAgentLlm(
        api_key=settings.groq_api_key,
        model=settings.groq_model,
        base_url=settings.groq_base_url,
    )


def _gmail_docker_config(settings: Settings) -> GmailDockerMcpEnvironment:
    """Build Docker Gmail MCP config from Settings-loaded environment values."""
    values = {
        "EMAIL_ADDRESS": settings.email_address,
        "EMAIL_PASSWORD": settings.email_password,
        "IMAP_HOST": settings.imap_host,
        "IMAP_PORT": str(settings.imap_port),
        "SMTP_HOST": settings.smtp_host,
        "SMTP_PORT": str(settings.smtp_port),
        "GMAIL_MCP_IMAGE": settings.gmail_mcp_image,
        "TEST_SEND_TO": settings.test_send_to,
    }
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise ConfigurationError(
            "Docker Gmail MCP is not configured.",
            details={"required_env": missing},
        )
    return GmailDockerMcpEnvironment(
        email_address=str(values["EMAIL_ADDRESS"]),
        email_password=str(values["EMAIL_PASSWORD"]),
        imap_host=str(values["IMAP_HOST"]),
        imap_port=str(values["IMAP_PORT"]),
        smtp_host=str(values["SMTP_HOST"]),
        smtp_port=str(values["SMTP_PORT"]),
        gmail_mcp_image=str(values["GMAIL_MCP_IMAGE"]),
        test_send_to=str(values["TEST_SEND_TO"]),
    )


async def get_app_settings() -> Settings:
    """Return application settings without using FastAPI's sync dependency runner."""
    return get_settings()


async def get_approval_service() -> ApprovalService:
    """Return the shared approval service."""
    return _approval_service()


async def get_workflow_node_registry() -> WorkflowNodeRegistry:
    """Return the workflow builder node registry."""
    return _workflow_node_registry()


async def get_workflow_validator() -> WorkflowValidator:
    """Return the workflow builder validator."""
    return _workflow_validator()


async def get_workflow_preview_runner() -> WorkflowPreviewRunner:
    """Return the workflow preview runner."""
    return _workflow_preview_runner()


async def get_gmail_mcp_service() -> GmailMcpService:
    """Return the Docker Gmail MCP application service."""
    settings = get_settings()
    return GmailMcpService(
        approval_service=_approval_service(),
        tool_client=DockerGmailMcpToolClient(_gmail_docker_config(settings)),
    )


async def get_email_agent_service() -> EmailAgentService:
    """Return the FastAPI email-agent service."""
    settings = get_settings()
    approval_service = _approval_service()
    gmail_service = GmailMcpService(
        approval_service=approval_service,
        tool_client=DockerGmailMcpToolClient(_gmail_docker_config(settings)),
    )
    return EmailAgentService(
        gmail_service=gmail_service,
        memory_store=_supabase_memory_store(settings),
        llm=_email_agent_llm(settings),
        approval_service=approval_service,
        state_store=_agent_state_store(),
    )
