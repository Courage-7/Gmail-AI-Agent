"""Memory store protocol used by the email agent."""

from __future__ import annotations

from typing import Any, Protocol


class MemoryStore(Protocol):
    """Persistence contract for conversation and email-agent audit events."""

    async def create_session(self, user_id: str, title: str | None = None) -> str: ...

    async def list_sessions(self, user_id: str, limit: int = 20) -> list[dict[str, Any]]: ...

    async def get_recent_messages(self, session_id: str, limit: int = 20) -> list[dict[str, Any]]: ...

    async def save_message(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> None: ...

    async def save_tool_event(
        self,
        session_id: str,
        tool_name: str,
        tool_args: dict[str, Any],
        result_summary: dict[str, Any],
        success: bool,
        error: str | None = None,
    ) -> None: ...

    async def save_draft_event(self, session_id: str, draft: dict[str, Any], status: str) -> None: ...

    async def save_send_event(
        self,
        session_id: str,
        draft: dict[str, Any],
        confirmed: bool,
        sent: bool,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None: ...
