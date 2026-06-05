"""Opt-in Docker Gmail MCP connection smoke tests."""

from __future__ import annotations

import os

import pytest
from dotenv import load_dotenv

from email_assistant_app.integrations.mcp.gmail_docker_client import (
    gmail_docker_mcp_session,
    run_preflight,
)

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def live_gmail_docker_mcp_tests_enabled() -> bool:
    return os.getenv("RUN_GMAIL_DOCKER_MCP_TESTS", "").lower() in {"1", "true", "yes", "on"}


@pytest.mark.skipif(
    not live_gmail_docker_mcp_tests_enabled(),
    reason="Set RUN_GMAIL_DOCKER_MCP_TESTS=true to run live Docker Gmail MCP tests.",
)
async def test_gmail_docker_mcp_connection_lists_required_tools() -> None:
    load_dotenv()
    config = run_preflight()

    async with gmail_docker_mcp_session(config) as session:
        result = await session.list_tools()

    tool_names = {tool.name for tool in result.tools}
    assert {"listMessages", "findMessage", "sendMessage"}.issubset(tool_names)
