"""Structured logging setup."""

from __future__ import annotations

import json
import logging
import time
import uuid
from contextvars import ContextVar
from typing import Any

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

request_id_context: ContextVar[str | None] = ContextVar("request_id", default=None)


class JsonFormatter(logging.Formatter):
    """JSON log formatter with support for structured extras."""

    reserved = {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "message",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "thread",
        "threadName",
    }

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", None) or request_id_context.get(),
        }
        for key, value in record.__dict__.items():
            if key not in self.reserved and key not in payload:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(log_level: str) -> None:
    """Configure root logging with JSON output."""
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(log_level.upper())


class RequestIdMiddleware:
    """Attach and propagate request IDs for all HTTP calls."""

    def __init__(self, app: ASGIApp, header_name: str = "x-request-id") -> None:
        self.app = app
        self.header_name = header_name
        self.logger = logging.getLogger("email_assistant_app.requests")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = Headers(scope=scope).get(self.header_name) or str(uuid.uuid4())
        scope.setdefault("state", {})["request_id"] = request_id
        token = request_id_context.set(request_id)
        started_at = time.perf_counter()
        status_code = 500

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                MutableHeaders(scope=message)[self.header_name] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
            self.logger.info(
                "http_request",
                extra={
                    "request_id": request_id,
                    "method": scope["method"],
                    "path": scope["path"],
                    "status_code": status_code,
                    "duration_ms": duration_ms,
                },
            )
            request_id_context.reset(token)
