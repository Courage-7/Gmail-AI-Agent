"""FastAPI endpoints for the session-aware email agent."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from email_assistant_app.agent.service import EmailAgentService
from email_assistant_app.application.dependencies import get_email_agent_service
from email_assistant_app.domain.agent import (
    AgentChatRequest,
    AgentChatResponse,
    AgentSessionCreateRequest,
    AgentSessionCreateResponse,
    AgentSessionListResponse,
)

router = APIRouter(prefix="/agent", tags=["agent"])


@router.post("/sessions", response_model=AgentSessionCreateResponse)
async def create_agent_session(
    body: AgentSessionCreateRequest,
    service: EmailAgentService = Depends(get_email_agent_service),
) -> AgentSessionCreateResponse:
    """Create a persisted email-agent conversation session."""
    return await service.create_session(body)


@router.get("/sessions", response_model=AgentSessionListResponse)
async def list_agent_sessions(
    user_id: str = Query(default="local-user", min_length=1),
    limit: int = Query(default=20, ge=1, le=100),
    service: EmailAgentService = Depends(get_email_agent_service),
) -> AgentSessionListResponse:
    """List persisted email-agent sessions for a user."""
    return await service.list_sessions(user_id=user_id, limit=limit)


@router.post("/chat", response_model=AgentChatResponse)
async def chat_with_agent(
    body: AgentChatRequest,
    service: EmailAgentService = Depends(get_email_agent_service),
) -> AgentChatResponse:
    """Run one user message through the email agent."""
    return await service.chat(body)
