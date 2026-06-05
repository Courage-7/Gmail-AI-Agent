import json
from pathlib import Path

import pytest

from email_assistant_app.agent.studio.studio_graph_fake import graph

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def test_studio_fake_graph_runs_search_flow() -> None:
    result = await graph.ainvoke(
        {
            "session_id": "studio-test-session",
            "user_id": "local-user",
            "user_message": "Find emails from Derek",
            "pending_send": False,
            "confirmation_required": False,
            "email_results": [],
            "selected_email": None,
            "draft": None,
            "data": {},
        }
    )

    assert result["intent"] == "search_email"
    assert "Derek result" in result["response"]
    assert result["selected_email"]["sender"] == "Derek <derek@example.com>"


async def test_studio_fake_graph_creates_session_when_missing() -> None:
    result = await graph.ainvoke({"user_message": "Find emails from Derek"})

    assert result["session_id"].startswith("studio-")
    assert result["user_id"] == "local-user"
    assert result["intent"] == "search_email"


def test_langgraph_config_points_to_studio_real_graph() -> None:
    config = json.loads(Path("langgraph.json").read_text())

    assert config["graphs"]["email_agent_real"] == (
        "./src/email_assistant_app/agent/studio/studio_graph_real.py:make_graph"
    )
