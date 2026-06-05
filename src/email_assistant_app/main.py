"""FastAPI application entrypoint."""

from __future__ import annotations

from fastapi import FastAPI

from email_assistant_app.api import agent, approvals, capabilities, gmail, health
from email_assistant_app.errors import AppError, app_error_handler
from email_assistant_app.observability.logging import RequestIdMiddleware, configure_logging
from email_assistant_app.settings import get_settings

settings = get_settings()
configure_logging(settings.log_level)

app = FastAPI(
    title=settings.app_name,
    description="Docker Gmail MCP-backed API and session-aware email agent.",
    version="0.1.0",
)
app.add_middleware(RequestIdMiddleware, header_name=settings.request_id_header)
app.add_exception_handler(AppError, app_error_handler)
app.include_router(health.router)
app.include_router(capabilities.router)
app.include_router(agent.router)
app.include_router(gmail.router)
app.include_router(approvals.router)
