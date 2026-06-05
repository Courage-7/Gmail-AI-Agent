"""LangGraph state for the email agent."""

from __future__ import annotations

from typing import Any

from typing_extensions import TypedDict


class EmailAgentState(TypedDict, total=False):
    """Mutable session state carried through the email-agent graph."""

    session_id: str
    user_id: str
    user_message: str
    messages: list[Any]
    intent: str
    query: str | None
    email_results: list[dict[str, Any]]
    selected_email: dict[str, Any] | None
    email_style_profile: dict[str, Any] | None
    awaiting_style_preference: bool
    style_preference_request: dict[str, Any] | None
    draft: dict[str, Any] | None
    pending_send: bool
    confirmation_required: bool
    memory_context: list[dict[str, Any]]
    tool_name: str | None
    tool_args: dict[str, Any] | None
    tool_result: Any
    tool_events: list[dict[str, Any]]
    draft_events: list[dict[str, Any]]
    send_events: list[dict[str, Any]]
    response: str
    data: dict[str, Any]
    error: str | None
