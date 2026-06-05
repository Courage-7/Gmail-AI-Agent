"""Health endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from email_assistant_app.application.dependencies import get_app_settings
from email_assistant_app.settings import Settings

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(settings: Settings = Depends(get_app_settings)) -> dict[str, str]:
    """Return service health."""
    return {"status": "ok", "service": settings.app_name, "environment": settings.environment}
