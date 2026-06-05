"""Docker Gmail MCP endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from email_assistant_app.application.dependencies import get_gmail_mcp_service
from email_assistant_app.application.gmail_mcp_service import GmailMcpService
from email_assistant_app.domain.email import (
    EmailMessage,
    GmailListMessagesRequest,
    GmailSearchMessagesRequest,
    GmailSendMessageRequest,
    GmailSendMessageResponse,
)

router = APIRouter(prefix="/gmail/messages", tags=["gmail"])


@router.post("/list", response_model=list[EmailMessage])
async def list_messages(
    body: GmailListMessagesRequest,
    service: GmailMcpService = Depends(get_gmail_mcp_service),
) -> list[EmailMessage]:
    """List recent Gmail messages through Docker MCP."""
    return await service.list_messages(body)


@router.post("/search", response_model=list[EmailMessage])
async def search_messages(
    body: GmailSearchMessagesRequest,
    service: GmailMcpService = Depends(get_gmail_mcp_service),
) -> list[EmailMessage]:
    """Search Gmail messages through Docker MCP."""
    return await service.search_messages(body)


@router.post("/send", response_model=GmailSendMessageResponse)
async def send_message(
    body: GmailSendMessageRequest,
    service: GmailMcpService = Depends(get_gmail_mcp_service),
) -> GmailSendMessageResponse:
    """Send a simple Gmail message through Docker MCP after approval."""
    return await service.send_message(body)
