"""Intent names supported by the email agent."""

from __future__ import annotations

from enum import StrEnum


class AgentIntent(StrEnum):
    """Supported agent intents."""

    SUMMARIZE_INBOX = "summarize_inbox"
    SEARCH_EMAIL = "search_email"
    DRAFT_REPLY = "draft_reply"
    REVISE_DRAFT = "revise_draft"
    SEND_EMAIL = "send_email"
    CONFIRM_SEND = "confirm_send"
    CANCEL_SEND = "cancel_send"
    EXTRACT_TASKS = "extract_tasks"
    GENERAL_CHAT = "general_chat"


VALID_INTENTS = {intent.value for intent in AgentIntent}
