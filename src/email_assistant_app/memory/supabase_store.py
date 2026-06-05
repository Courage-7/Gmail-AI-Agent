"""Supabase-backed conversation memory store."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Callable, TypeVar

import anyio
from supabase import Client, create_client

from email_assistant_app.errors import ExternalServiceError

T = TypeVar("T")


class SupabaseMemoryStore:
    """Persist email-agent memory and audit events in Supabase tables."""

    def __init__(self, supabase_url: str, service_role_key: str) -> None:
        self._client: Client = create_client(supabase_url, service_role_key)

    async def create_session(self, user_id: str, title: str | None = None) -> str:
        """Create a new conversation session and return its UUID."""
        response = await self._run(
            lambda: self._client.table("conversation_sessions")
            .insert({"user_id": user_id, "title": title})
            .execute()
        )
        row = _first_row(response)
        session_id = row.get("id")
        if not session_id:
            raise ExternalServiceError("Supabase did not return a conversation session id.")
        return str(session_id)

    async def list_sessions(self, user_id: str, limit: int = 20) -> list[dict[str, Any]]:
        """Return recent conversation sessions for a user."""
        response = await self._run(
            lambda: self._client.table("conversation_sessions")
            .select("id, user_id, title, created_at, updated_at")
            .eq("user_id", user_id)
            .order("updated_at", desc=True)
            .limit(limit)
            .execute()
        )
        sessions = []
        for row in list(getattr(response, "data", None) or []):
            if not isinstance(row, dict):
                continue
            sessions.append(
                {
                    "session_id": str(row.get("id") or ""),
                    "user_id": str(row.get("user_id") or ""),
                    "title": row.get("title"),
                    "created_at": _optional_str(row.get("created_at")),
                    "updated_at": _optional_str(row.get("updated_at")),
                }
            )
        return [session for session in sessions if session["session_id"]]

    async def get_recent_messages(self, session_id: str, limit: int = 20) -> list[dict[str, Any]]:
        """Return recent conversation messages in chronological order."""
        response = await self._run(
            lambda: self._client.table("conversation_messages")
            .select("role, content, metadata, created_at")
            .eq("session_id", session_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        rows = list(getattr(response, "data", None) or [])
        rows.reverse()
        return rows

    async def save_message(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Persist a user, assistant, tool, or system message."""
        await self._run(
            lambda: self._client.table("conversation_messages")
            .insert(
                {
                    "session_id": session_id,
                    "role": role,
                    "content": content,
                    "metadata": metadata or {},
                }
            )
            .execute()
        )
        await self._touch_session(session_id)

    async def save_tool_event(
        self,
        session_id: str,
        tool_name: str,
        tool_args: dict[str, Any],
        result_summary: dict[str, Any],
        success: bool,
        error: str | None = None,
    ) -> None:
        """Persist a summarized Gmail tool call event."""
        await self._run(
            lambda: self._client.table("email_tool_events")
            .insert(
                {
                    "session_id": session_id,
                    "tool_name": tool_name,
                    "tool_args": tool_args,
                    "tool_result_summary": result_summary,
                    "success": success,
                    "error": error,
                }
            )
            .execute()
        )
        await self._touch_session(session_id)

    async def save_draft_event(self, session_id: str, draft: dict[str, Any], status: str) -> None:
        """Persist a draft lifecycle event."""
        await self._run(
            lambda: self._client.table("draft_events")
            .insert(
                {
                    "session_id": session_id,
                    "recipient": draft.get("to"),
                    "subject": draft.get("subject"),
                    "body": draft.get("body"),
                    "status": status,
                    "metadata": _draft_metadata(draft),
                }
            )
            .execute()
        )
        await self._touch_session(session_id)

    async def save_send_event(
        self,
        session_id: str,
        draft: dict[str, Any],
        confirmed: bool,
        sent: bool,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        """Persist a send audit event."""
        await self._run(
            lambda: self._client.table("send_events")
            .insert(
                {
                    "session_id": session_id,
                    "recipient": draft.get("to") or "",
                    "subject": draft.get("subject") or "",
                    "confirmed_by_user": confirmed,
                    "sent": sent,
                    "send_result": result or {},
                    "error": error,
                }
            )
            .execute()
        )
        await self._touch_session(session_id)

    async def _touch_session(self, session_id: str) -> None:
        await self._run(
            lambda: self._client.table("conversation_sessions")
            .update({"updated_at": datetime.now(UTC).isoformat()})
            .eq("id", session_id)
            .execute()
        )

    async def _run(self, operation: Callable[[], T]) -> T:
        try:
            return await anyio.to_thread.run_sync(operation)
        except Exception as exc:  # pragma: no cover - exercised only by live Supabase.
            raise ExternalServiceError("Supabase memory operation failed.", details={"error": str(exc)}) from exc


def _first_row(response: Any) -> dict[str, Any]:
    data = getattr(response, "data", None)
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return data[0]
    raise ExternalServiceError("Supabase did not return the expected row data.")


def _draft_metadata(draft: dict[str, Any]) -> dict[str, Any]:
    return {
        "cc": draft.get("cc") or [],
        "bcc": draft.get("bcc") or [],
        "missing_fields": draft.get("missing_fields") or [],
    }


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)
