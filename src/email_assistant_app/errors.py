"""Application error types and HTTP exception handling."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class AppError(Exception):
    """Base application error with an HTTP representation."""

    status_code = 500
    code = "application_error"

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class ConfigurationError(AppError):
    """Raised when required runtime configuration is missing or invalid."""

    status_code = 503
    code = "configuration_error"


class ExternalServiceError(AppError):
    """Raised when an external provider request fails."""

    status_code = 502
    code = "external_service_error"


class NotFoundError(AppError):
    """Raised when a requested resource does not exist."""

    status_code = 404
    code = "not_found"


class ValidationAppError(AppError):
    """Raised when validated input is semantically invalid."""

    status_code = 422
    code = "validation_error"


class ApprovalRequiredError(AppError):
    """Raised when an external action requires explicit approval."""

    status_code = 409
    code = "approval_required"


class InvalidApprovalError(AppError):
    """Raised when an approval is missing, rejected, or invalid."""

    status_code = 409
    code = "invalid_approval"


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    """Convert application errors to structured HTTP responses."""
    request_id = getattr(request.state, "request_id", None)
    logger.warning(
        "application_error",
        extra={
            "request_id": request_id,
            "error_code": exc.code,
            "status_code": exc.status_code,
            "path": str(request.url.path),
        },
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
                "request_id": request_id,
            }
        },
    )
