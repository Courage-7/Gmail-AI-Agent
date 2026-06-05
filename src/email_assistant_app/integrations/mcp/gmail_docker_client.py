"""Docker stdio client for the Gmail IMAP/SMTP MCP server."""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

DEFAULT_GMAIL_MCP_IMAGE = "yashtekwani/gmail-mcp"

REQUIRED_ENV_VARS = (
    "EMAIL_ADDRESS",
    "EMAIL_PASSWORD",
    "IMAP_HOST",
    "IMAP_PORT",
    "SMTP_HOST",
    "SMTP_PORT",
    "GMAIL_MCP_IMAGE",
    "TEST_SEND_TO",
)


class GmailDockerMcpPreflightError(RuntimeError):
    """Raised when Docker Gmail MCP configuration cannot run."""


@dataclass(frozen=True)
class GmailDockerMcpEnvironment:
    """Environment required to launch the Docker Gmail MCP server."""

    email_address: str
    email_password: str
    imap_host: str
    imap_port: str
    smtp_host: str
    smtp_port: str
    gmail_mcp_image: str
    test_send_to: str

    def server_env(self) -> dict[str, str]:
        """Return environment variables passed to the Docker CLI process."""
        return {
            "EMAIL_ADDRESS": self.email_address,
            "EMAIL_PASSWORD": self.email_password,
            "IMAP_HOST": self.imap_host,
            "IMAP_PORT": self.imap_port,
            "SMTP_HOST": self.smtp_host,
            "SMTP_PORT": self.smtp_port,
        }


def load_gmail_docker_mcp_environment(env: Mapping[str, str] | None = None) -> GmailDockerMcpEnvironment:
    """Read and validate Docker Gmail MCP environment variables."""
    source = os.environ if env is None else env
    values = {
        "EMAIL_ADDRESS": source.get("EMAIL_ADDRESS", "").strip(),
        "EMAIL_PASSWORD": source.get("EMAIL_PASSWORD", "").strip(),
        "IMAP_HOST": source.get("IMAP_HOST", "imap.gmail.com").strip(),
        "IMAP_PORT": source.get("IMAP_PORT", "993").strip(),
        "SMTP_HOST": source.get("SMTP_HOST", "smtp.gmail.com").strip(),
        "SMTP_PORT": source.get("SMTP_PORT", "587").strip(),
        "GMAIL_MCP_IMAGE": source.get("GMAIL_MCP_IMAGE", DEFAULT_GMAIL_MCP_IMAGE).strip(),
        "TEST_SEND_TO": source.get("TEST_SEND_TO", "").strip(),
    }
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise GmailDockerMcpPreflightError(
            "Missing required Docker Gmail MCP environment variables: " + ", ".join(missing)
        )

    for port_name in ("IMAP_PORT", "SMTP_PORT"):
        try:
            int(values[port_name])
        except ValueError as exc:
            raise GmailDockerMcpPreflightError(f"{port_name} must be an integer.") from exc

    return GmailDockerMcpEnvironment(
        email_address=values["EMAIL_ADDRESS"],
        email_password=values["EMAIL_PASSWORD"],
        imap_host=values["IMAP_HOST"],
        imap_port=values["IMAP_PORT"],
        smtp_host=values["SMTP_HOST"],
        smtp_port=values["SMTP_PORT"],
        gmail_mcp_image=values["GMAIL_MCP_IMAGE"],
        test_send_to=values["TEST_SEND_TO"],
    )


def check_docker_runtime(timeout_seconds: int = 15) -> None:
    """Validate that Docker is installed and the daemon is reachable."""
    if shutil.which("docker") is None:
        raise GmailDockerMcpPreflightError("Docker is not installed or is not on PATH.")

    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise GmailDockerMcpPreflightError("Docker daemon check timed out.") from exc

    if result.returncode != 0:
        message = (result.stderr or result.stdout or "Docker daemon is not reachable.").strip()
        raise GmailDockerMcpPreflightError(f"Docker daemon is not running or is unreachable: {message}")


def run_preflight(env: Mapping[str, str] | None = None, check_docker: bool = True) -> GmailDockerMcpEnvironment:
    """Validate environment and, optionally, Docker runtime availability."""
    config = load_gmail_docker_mcp_environment(env)
    if check_docker:
        check_docker_runtime()
    return config


def get_gmail_docker_server_params(
    config: GmailDockerMcpEnvironment | None = None,
) -> StdioServerParameters:
    """Build stdio launch parameters for the Docker Gmail MCP server."""
    resolved_config = config or load_gmail_docker_mcp_environment()
    return StdioServerParameters(
        command="docker",
        args=[
            "run",
            "-i",
            "--rm",
            "-e",
            "EMAIL_ADDRESS",
            "-e",
            "IMAP_HOST",
            "-e",
            "IMAP_PORT",
            "-e",
            "SMTP_HOST",
            "-e",
            "SMTP_PORT",
            "-e",
            "EMAIL_PASSWORD",
            resolved_config.gmail_mcp_image,
        ],
        env=resolved_config.server_env(),
    )


@asynccontextmanager
async def gmail_docker_mcp_session(config: GmailDockerMcpEnvironment | None = None):
    """Open an initialized MCP session against the Docker Gmail MCP server."""
    server_params = get_gmail_docker_server_params(config)
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


async def list_available_tools(config: GmailDockerMcpEnvironment | None = None) -> list[dict[str, Any]]:
    """Return tool metadata exposed by the Docker Gmail MCP server."""
    async with gmail_docker_mcp_session(config) as session:
        result = await session.list_tools()
    return [tool.model_dump(mode="json", by_alias=True) for tool in result.tools]


async def list_messages(count: int = 5, config: GmailDockerMcpEnvironment | None = None):
    """Call the Docker Gmail MCP listMessages tool."""
    async with gmail_docker_mcp_session(config) as session:
        return await session.call_tool("listMessages", {"count": count})


async def find_message(query: str, config: GmailDockerMcpEnvironment | None = None):
    """Call the Docker Gmail MCP findMessage tool."""
    async with gmail_docker_mcp_session(config) as session:
        return await session.call_tool("findMessage", {"query": query})


async def send_message(
    to: str,
    subject: str,
    body: str,
    cc: str | None = None,
    bcc: str | None = None,
    config: GmailDockerMcpEnvironment | None = None,
):
    """Call the Docker Gmail MCP sendMessage tool."""
    arguments = {
        "to": to,
        "subject": subject,
        "body": body,
    }
    if cc:
        arguments["cc"] = cc
    if bcc:
        arguments["bcc"] = bcc

    async with gmail_docker_mcp_session(config) as session:
        return await session.call_tool("sendMessage", arguments)
