"""MCP integrations."""

from email_assistant_app.integrations.mcp.gmail_docker_client import (
    GmailDockerMcpEnvironment,
    GmailDockerMcpPreflightError,
    check_docker_runtime,
    find_message,
    get_gmail_docker_server_params,
    gmail_docker_mcp_session,
    list_available_tools,
    list_messages,
    load_gmail_docker_mcp_environment,
    run_preflight,
    send_message,
)

__all__ = [
    "GmailDockerMcpEnvironment",
    "GmailDockerMcpPreflightError",
    "check_docker_runtime",
    "find_message",
    "get_gmail_docker_server_params",
    "gmail_docker_mcp_session",
    "list_available_tools",
    "list_messages",
    "load_gmail_docker_mcp_environment",
    "run_preflight",
    "send_message",
]
