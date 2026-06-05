"""Agent API domain models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AgentSessionCreateRequest(BaseModel):
    """Request to create a persisted agent conversation session."""

    user_id: str = Field(default="local-user", min_length=1)
    title: str | None = None


class AgentSessionCreateResponse(BaseModel):
    """Created agent conversation session."""

    session_id: str
    user_id: str
    title: str | None = None


class AgentSessionSummary(BaseModel):
    """Conversation session listed for a user."""

    session_id: str
    user_id: str
    title: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class AgentSessionListResponse(BaseModel):
    """List of conversation sessions available to continue."""

    sessions: list[AgentSessionSummary] = Field(default_factory=list)


class AgentChatRequest(BaseModel):
    """One user message sent to the email agent."""

    session_id: str | None = Field(default=None, min_length=1)
    user_id: str = Field(default="local-user", min_length=1)
    message: str = Field(min_length=1)


class AgentChatResponse(BaseModel):
    """Agent response returned by the chat endpoint."""

    session_id: str
    intent: str
    message: str
    data: dict[str, Any] = Field(default_factory=dict)
    pending_send: bool = False
    draft: dict[str, Any] | None = None
