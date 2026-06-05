"""Capabilities endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from email_assistant_app.application.dependencies import get_app_settings
from email_assistant_app.settings import Settings

router = APIRouter(tags=["capabilities"])


@router.get("/capabilities")
async def capabilities(settings: Settings = Depends(get_app_settings)) -> dict:
    """Return configured and supported service capabilities."""
    docker_mcp_configured = bool(
        settings.email_address
        and settings.email_password
        and settings.imap_host
        and settings.imap_port
        and settings.smtp_host
        and settings.smtp_port
        and settings.gmail_mcp_image
    )
    supabase_configured = bool(settings.supabase_url and settings.supabase_service_role_key)
    agent_configured = bool(settings.llm_configured and supabase_configured)
    return {
        "service": settings.app_name,
        "features": [
            "fastapi_email_agent_chat",
            "supabase_conversation_memory",
            "docker_gmail_mcp_list_messages",
            "docker_gmail_mcp_find_message",
            "approved_docker_gmail_mcp_send_message",
        ],
        "configuration": {
            "agent_configured": agent_configured,
            "llm_provider": settings.llm_provider,
            "llm_model": settings.llm_model,
            "llm_configured": settings.llm_configured,
            "supabase_configured": supabase_configured,
            "gmail_docker_mcp_configured": docker_mcp_configured,
            "gmail_mcp_image": settings.gmail_mcp_image,
            "imap_host": settings.imap_host,
            "imap_port": settings.imap_port,
            "smtp_host": settings.smtp_host,
            "smtp_port": settings.smtp_port,
            "test_send_to_configured": bool(settings.test_send_to),
        },
    }
