"""Email domain models."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class EmailMessage(BaseModel):
    """Normalized email message used by the application."""

    message_id: str
    thread_id: str
    sender: str
    recipients: list[str] = Field(default_factory=list)
    subject: str
    body: str
    received_at: datetime | None = None
    snippet: str | None = None


class GmailListMessagesRequest(BaseModel):
    """Request for recent Gmail messages from Docker MCP."""

    count: int = Field(default=5, ge=1, le=100)


class GmailSearchMessagesRequest(BaseModel):
    """Request for Gmail MCP message search."""

    query: str = Field(min_length=1)


class GmailSendMessageRequest(BaseModel):
    """Request to send a simple email through Docker Gmail MCP."""

    to: str = Field(min_length=1)
    subject: str = Field(min_length=1)
    body: str = Field(min_length=1)
    cc: list[str] = Field(default_factory=list)
    bcc: list[str] = Field(default_factory=list)
    approval_id: str | None = None


class GmailSendMessageResponse(BaseModel):
    """Result of a Docker Gmail MCP sendMessage call."""

    provider_message_id: str | None = None
    message: str | None = None
    status: str
