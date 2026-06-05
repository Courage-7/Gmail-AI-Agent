"""LangGraph node implementations for the email agent."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from email.utils import parseaddr
from typing import TYPE_CHECKING, Any, Protocol

from email_assistant_app.agent.intents import AgentIntent, VALID_INTENTS
from email_assistant_app.agent.state import EmailAgentState
from email_assistant_app.domain.action import ActionType, ResumeApprovalRequest
from email_assistant_app.domain.email import (
    EmailMessage,
    GmailListMessagesRequest,
    GmailSearchMessagesRequest,
    GmailSendMessageRequest,
)
from email_assistant_app.memory.store import MemoryStore

if TYPE_CHECKING:
    from email_assistant_app.application.approval_service import ApprovalService
    from email_assistant_app.application.gmail_mcp_service import GmailMcpService

SENT_MAIL_STYLE_QUERY = "in:sent newer_than:180d"


class AgentLlm(Protocol):
    """LLM operations required by the agent nodes."""

    async def classify_intent(
        self,
        user_message: str,
        memory_context: list[dict[str, Any]],
        pending_send: bool,
        has_draft: bool,
    ) -> dict[str, str]: ...

    async def summarize_emails(
        self,
        user_message: str,
        emails: list[dict[str, Any]],
        memory_context: list[dict[str, Any]],
    ) -> dict[str, Any]: ...

    async def draft_email(
        self,
        user_message: str,
        selected_email: dict[str, Any] | None,
        email_results: list[dict[str, Any]],
        memory_context: list[dict[str, Any]],
        email_style_profile: dict[str, Any] | None,
    ) -> dict[str, Any]: ...

    async def revise_draft(
        self,
        user_message: str,
        draft: dict[str, Any],
        memory_context: list[dict[str, Any]],
        email_style_profile: dict[str, Any] | None,
    ) -> dict[str, Any]: ...

    async def analyze_email_style(self, sent_emails: list[dict[str, Any]]) -> dict[str, Any]: ...

    async def extract_tasks(
        self,
        user_message: str,
        emails: list[dict[str, Any]],
        memory_context: list[dict[str, Any]],
    ) -> str: ...

    async def general_chat(self, user_message: str, memory_context: list[dict[str, Any]]) -> str: ...


class EmailAgentRuntime:
    """Dependency bundle and node methods for the email-agent graph."""

    def __init__(
        self,
        gmail_service: GmailMcpService,
        memory_store: MemoryStore,
        llm: AgentLlm,
        approval_service: ApprovalService,
    ) -> None:
        self.gmail_service = gmail_service
        self.memory_store = memory_store
        self.llm = llm
        self.approval_service = approval_service

    async def load_conversation_context(self, state: EmailAgentState) -> dict[str, Any]:
        """Load recent persisted conversation memory."""
        session_id = state.get("session_id")
        user_id = state.get("user_id") or "local-user"
        if not session_id:
            session_id = await self.memory_store.create_session(user_id, "LangGraph Studio")
        memory_context = await self.memory_store.get_recent_messages(session_id, limit=20)
        return {
            "session_id": session_id,
            "user_id": user_id,
            "user_message": state.get("user_message") or _latest_message_text(state),
            "memory_context": memory_context,
        }

    async def classify_intent(self, state: EmailAgentState) -> dict[str, Any]:
        """Classify the message, with deterministic safety shortcuts for confirmation/cancel flows."""
        user_message = state["user_message"]
        pending_send = bool(state.get("pending_send"))
        has_draft = bool(state.get("draft"))
        if state.get("awaiting_style_preference") and state.get("style_preference_request"):
            text = _simple_text(user_message)
            if re.search(r"\b(cancel|do not send|don't send|never mind|nevermind|stop)\b", text):
                return {"intent": AgentIntent.CANCEL_SEND.value, "query": user_message}
            request = state.get("style_preference_request") or {}
            intent = str(request.get("intent") or AgentIntent.DRAFT_REPLY.value)
            if intent in {AgentIntent.DRAFT_REPLY.value, AgentIntent.REVISE_DRAFT.value}:
                return {"intent": intent, "query": str(request.get("user_message") or user_message)}

        shortcut = _classify_shortcut(user_message, pending_send=pending_send, has_draft=has_draft)
        if shortcut:
            return shortcut

        classification = await self.llm.classify_intent(
            user_message=user_message,
            memory_context=state.get("memory_context", []),
            pending_send=pending_send,
            has_draft=has_draft,
        )
        intent = classification.get("intent") or AgentIntent.GENERAL_CHAT.value
        if intent not in VALID_INTENTS:
            intent = AgentIntent.GENERAL_CHAT.value
        return {
            "intent": intent,
            "query": _normalize_query(classification.get("query") or user_message),
        }

    async def resolve_email_style(
        self,
        state: EmailAgentState,
        *,
        request_intent: str,
        request_message: str,
    ) -> dict[str, Any]:
        """Return a usable compact email style profile or a preference question response."""
        if state.get("awaiting_style_preference"):
            profile = _style_profile_from_preference(state["user_message"])
            return {
                "profile": profile,
                "updates": {
                    "email_style_profile": profile,
                    "awaiting_style_preference": False,
                    "style_preference_request": None,
                },
            }

        existing_profile = _normalize_style_profile(state.get("email_style_profile"))
        if _style_profile_is_usable(existing_profile):
            return {"profile": existing_profile, "updates": {}}

        try:
            messages = await self.gmail_service.search_messages(GmailSearchMessagesRequest(query=SENT_MAIL_STYLE_QUERY))
        except Exception as exc:
            error = getattr(exc, "message", str(exc))
            profile = _low_confidence_style_profile("sent-mail lookup failed")
            updates = {
                "email_style_profile": profile,
                "awaiting_style_preference": True,
                "style_preference_request": {"intent": request_intent, "user_message": request_message},
                "tool_events": _append_tool_event(
                    state,
                    "find_message",
                    {"query": SENT_MAIL_STYLE_QUERY},
                    {"count": 0, "messages": []},
                    success=False,
                    error=error,
                ),
            }
            return {
                "profile": profile,
                "updates": updates,
                "response": _style_preference_question(),
                "data": _style_preference_data(profile),
            }

        sent_emails = [_email_to_dict(message) for message in messages]
        tool_events = _append_tool_event(
            state,
            "find_message",
            {"query": SENT_MAIL_STYLE_QUERY},
            _summarize_email_results(sent_emails),
        )
        if not sent_emails:
            profile = _low_confidence_style_profile("no recent sent emails found")
        else:
            try:
                profile = _normalize_style_profile(
                    await self.llm.analyze_email_style(_style_analysis_samples(sent_emails)),
                    sample_count=len(sent_emails),
                )
            except Exception:
                profile = _low_confidence_style_profile("sent-mail analysis failed", sample_count=len(sent_emails))

        updates = {
            "email_style_profile": profile,
            "tool_events": tool_events,
        }
        if not _style_profile_is_usable(profile):
            updates.update(
                {
                    "awaiting_style_preference": True,
                    "style_preference_request": {"intent": request_intent, "user_message": request_message},
                }
            )
            return {
                "profile": profile,
                "updates": updates,
                "response": _style_preference_question(),
                "data": _style_preference_data(profile),
            }

        return {"profile": profile, "updates": updates}

    async def summarize_inbox_node(self, state: EmailAgentState) -> dict[str, Any]:
        """Summarize recent inbox emails or a referenced previous result."""
        selected = _resolve_referenced_email(state)
        if selected:
            summary_payload = await self.llm.summarize_emails(
                state["user_message"],
                [selected],
                state.get("memory_context", []),
            )
            response, data = _summary_response(summary_payload, [selected])
            return {"selected_email": selected, "response": response, "data": data}

        messages = await self.gmail_service.list_messages(GmailListMessagesRequest(count=10))
        emails = [_email_to_dict(message) for message in messages]
        summary_payload = await self.llm.summarize_emails(
            state["user_message"],
            emails,
            state.get("memory_context", []),
        )
        response, data = _summary_response(summary_payload, emails)
        return {
            "email_results": emails,
            "selected_email": emails[0] if emails else None,
            "tool_events": _append_tool_event(
                state,
                "list_messages",
                {"count": 10},
                _summarize_email_results(emails),
            ),
            "response": response,
            "data": data,
        }

    async def search_email_node(self, state: EmailAgentState) -> dict[str, Any]:
        """Search Gmail through Docker MCP and summarize the returned results."""
        query = _normalize_query(state.get("query") or state["user_message"])
        try:
            messages = await self.gmail_service.search_messages(GmailSearchMessagesRequest(query=query))
        except Exception as exc:
            error = _tool_error_payload(exc)
            return {
                "query": query,
                "email_results": [],
                "selected_email": None,
                "tool_events": _append_tool_event(
                    state,
                    "find_message",
                    {"query": query},
                    {"count": 0, "error": error},
                    success=False,
                    error=error["message"],
                ),
                "response": f"I could not search Gmail for: {query}. {error['message']}",
                "data": {"error": {"tool": "find_message", "query": query, **error}},
            }
        emails = [_email_to_dict(message) for message in messages]
        if not emails:
            response = f"I did not find emails matching: {query}"
            data = {"summary": {"items": [], "notes": [f"No email results for query: {query}"]}}
        else:
            summary_payload = await self.llm.summarize_emails(
                state["user_message"],
                emails,
                state.get("memory_context", []),
            )
            response, data = _summary_response(summary_payload, emails)
        return {
            "query": query,
            "email_results": emails,
            "selected_email": emails[0] if emails else None,
            "tool_events": _append_tool_event(
                state,
                "find_message",
                {"query": query},
                _summarize_email_results(emails),
            ),
            "response": response,
            "data": data,
        }

    async def draft_reply_node(self, state: EmailAgentState) -> dict[str, Any]:
        """Create a draft and ask for explicit confirmation."""
        draft_request_message = _pending_style_request_message(state) or state["user_message"]
        reference_state = {**state, "user_message": draft_request_message}
        selected = _resolve_referenced_email(reference_state) or _find_email_for_message(
            draft_request_message,
            state.get("email_results", []),
        )
        style_resolution = await self.resolve_email_style(
            state,
            request_intent=AgentIntent.DRAFT_REPLY.value,
            request_message=draft_request_message,
        )
        style_updates = style_resolution.get("updates") or {}
        if style_resolution.get("response"):
            return {
                **style_updates,
                "selected_email": selected,
                "pending_send": False,
                "confirmation_required": False,
                "response": style_resolution["response"],
                "data": style_resolution.get("data") or {},
            }
        email_style_profile = style_resolution.get("profile")
        draft = await self.llm.draft_email(
            draft_request_message,
            selected,
            state.get("email_results", []),
            state.get("memory_context", []),
            email_style_profile,
        )
        draft = _complete_draft_from_context(draft, selected)
        draft = _apply_email_style_to_draft(draft, email_style_profile, selected)
        missing = _missing_draft_fields(draft)
        draft["missing_fields"] = sorted(set(missing + list(draft.get("missing_fields") or [])))

        if draft["missing_fields"]:
            response = _missing_fields_response(draft)
            return {
                **style_updates,
                "selected_email": selected,
                "draft": draft,
                "pending_send": False,
                "confirmation_required": False,
                "draft_events": _append_draft_event(state, draft, "drafted"),
                "response": response,
                "data": _draft_data("missing_fields", draft, email_style_profile),
            }

        response = _confirmation_response(draft)
        return {
            **style_updates,
            "selected_email": selected,
            "draft": draft,
            "pending_send": True,
            "confirmation_required": True,
            "draft_events": _append_draft_event(state, draft, "pending_confirmation"),
            "response": response,
            "data": _draft_data("pending_confirmation", draft, email_style_profile),
        }

    async def revise_draft_node(self, state: EmailAgentState) -> dict[str, Any]:
        """Revise the current draft and keep it pending confirmation."""
        current_draft = state.get("draft")
        if not current_draft:
            return {
                "pending_send": False,
                "confirmation_required": False,
                "response": "There is no draft to revise yet. Tell me what you want to draft.",
                "data": {"draft_status": "missing_fields", "missing_fields": ["draft"]},
            }

        draft_request_message = _pending_style_request_message(state) or state["user_message"]
        style_resolution = await self.resolve_email_style(
            state,
            request_intent=AgentIntent.REVISE_DRAFT.value,
            request_message=draft_request_message,
        )
        style_updates = style_resolution.get("updates") or {}
        if style_resolution.get("response"):
            return {
                **style_updates,
                "draft": current_draft,
                "pending_send": False,
                "confirmation_required": False,
                "response": style_resolution["response"],
                "data": style_resolution.get("data") or {},
            }
        email_style_profile = style_resolution.get("profile")
        draft = await self.llm.revise_draft(
            draft_request_message,
            current_draft,
            state.get("memory_context", []),
            email_style_profile,
        )
        draft = _merge_draft(current_draft, draft)
        draft = _apply_email_style_to_draft(draft, email_style_profile, state.get("selected_email"))
        missing = _missing_draft_fields(draft)
        draft["missing_fields"] = sorted(set(missing + list(draft.get("missing_fields") or [])))

        if draft["missing_fields"]:
            return {
                **style_updates,
                "draft": draft,
                "pending_send": False,
                "confirmation_required": False,
                "draft_events": _append_draft_event(state, draft, "revised"),
                "response": _missing_fields_response(draft),
                "data": _draft_data("missing_fields", draft, email_style_profile),
            }

        return {
            **style_updates,
            "draft": draft,
            "pending_send": True,
            "confirmation_required": True,
            "draft_events": _append_draft_event(state, draft, "revised"),
            "response": _confirmation_response(draft),
            "data": _draft_data("revised", draft, email_style_profile),
        }

    async def confirm_send_node(self, state: EmailAgentState) -> dict[str, Any]:
        """Send only after a pending draft receives explicit confirmation."""
        draft = state.get("draft")
        if not state.get("pending_send") or not state.get("confirmation_required") or not draft:
            return {
                "pending_send": False,
                "confirmation_required": False,
                "response": "There is no pending draft ready to send.",
                "data": {"draft_status": "missing_fields", "missing_fields": ["draft"]},
            }

        missing = _missing_draft_fields(draft)
        if missing:
            draft = dict(draft)
            draft["missing_fields"] = missing
            return {
                "draft": draft,
                "pending_send": False,
                "confirmation_required": False,
                "response": _missing_fields_response(draft),
                "data": _draft_data("missing_fields", draft),
            }

        payload = {
            "to": draft["to"],
            "subject": draft["subject"],
            "body": draft["body"],
            "cc": draft.get("cc") or [],
            "bcc": draft.get("bcc") or [],
        }
        approval = self.approval_service.create(ActionType.SEND_EMAIL, payload)
        self.approval_service.resume(ResumeApprovalRequest(approval_id=approval.approval_id, approved=True))
        try:
            send_response = await self.gmail_service.send_message(
                GmailSendMessageRequest(**payload, approval_id=approval.approval_id)
            )
        except Exception as exc:
            error = getattr(exc, "message", str(exc))
            return {
                "pending_send": True,
                "confirmation_required": True,
                "send_events": _append_send_event(state, draft, confirmed=True, sent=False, error=error),
                "tool_events": _append_tool_event(
                    state,
                    "send_message",
                    _redact_send_args(payload),
                    {"status": "failed"},
                    success=False,
                    error=error,
                ),
                "response": f"I could not send the email: {error}",
                "data": _send_data("failed", draft, sent=False, error=error),
            }
        result = send_response.model_dump(mode="json")
        response = "Sent the email."
        return {
            "pending_send": False,
            "confirmation_required": False,
            "draft_events": _append_draft_event(state, draft, "sent"),
            "send_events": _append_send_event(state, draft, confirmed=True, sent=True, result=result),
            "tool_events": _append_tool_event(
                state,
                "send_message",
                _redact_send_args(payload),
                result,
            ),
            "response": response,
            "data": _send_data("sent", draft, sent=True, result=result),
        }

    async def cancel_send_node(self, state: EmailAgentState) -> dict[str, Any]:
        """Cancel the current pending send."""
        draft = state.get("draft") or {}
        return {
            "pending_send": False,
            "confirmation_required": False,
            "draft_events": _append_draft_event(state, draft, "cancelled") if draft else state.get("draft_events", []),
            "response": "Cancelled the pending send.",
            "data": _draft_data("cancelled", draft) if draft else {"draft_status": "cancelled"},
        }

    async def extract_tasks_node(self, state: EmailAgentState) -> dict[str, Any]:
        """Extract likely action items from recent emails."""
        messages = await self.gmail_service.list_messages(GmailListMessagesRequest(count=10))
        emails = [_email_to_dict(message) for message in messages]
        response = _clean_agent_response(
            await self.llm.extract_tasks(
                state["user_message"],
                emails,
                state.get("memory_context", []),
            )
        )
        return {
            "email_results": emails,
            "selected_email": emails[0] if emails else None,
            "tool_events": _append_tool_event(
                state,
                "list_messages",
                {"count": 10},
                _summarize_email_results(emails),
            ),
            "response": response,
            "data": _tasks_data(response, emails),
        }

    async def general_chat_node(self, state: EmailAgentState) -> dict[str, Any]:
        """Respond without calling Gmail tools."""
        response = _clean_agent_response(
            await self.llm.general_chat(state["user_message"], state.get("memory_context", []))
        )
        return {"response": response, "data": {}}

    async def save_memory(self, state: EmailAgentState) -> dict[str, Any]:
        """Persist conversation messages and summarized audit events."""
        user_id = state.get("user_id") or "local-user"
        session_id = state.get("session_id") or await self.memory_store.create_session(user_id, "LangGraph Studio")
        user_message = state.get("user_message") or _latest_message_text(state)
        await self.memory_store.save_message(
            session_id,
            "user",
            user_message,
            {"intent": state.get("intent"), "query": state.get("query")},
        )
        await self.memory_store.save_message(
            session_id,
            "assistant",
            state.get("response", ""),
            {
                "intent": state.get("intent"),
                "pending_send": bool(state.get("pending_send")),
                "has_draft": bool(state.get("draft")),
                "data": state.get("data") or {},
            },
        )
        for event in state.get("tool_events", []):
            await self.memory_store.save_tool_event(
                session_id=session_id,
                tool_name=event["tool_name"],
                tool_args=event["tool_args"],
                result_summary=event["result_summary"],
                success=event.get("success", True),
                error=event.get("error"),
            )
        for event in state.get("draft_events", []):
            await self.memory_store.save_draft_event(session_id, event["draft"], event["status"])
        for event in state.get("send_events", []):
            await self.memory_store.save_send_event(
                session_id=session_id,
                draft=event["draft"],
                confirmed=event["confirmed"],
                sent=event["sent"],
                result=event.get("result"),
                error=event.get("error"),
            )
        return {"session_id": session_id, "user_id": user_id, "user_message": user_message}


def _pending_style_request_message(state: EmailAgentState) -> str | None:
    request = state.get("style_preference_request") if state.get("awaiting_style_preference") else None
    if isinstance(request, dict):
        message = str(request.get("user_message") or "").strip()
        return message or None
    return None


def _latest_message_text(state: EmailAgentState) -> str:
    messages = state.get("messages")
    if not isinstance(messages, list):
        return ""
    for message in reversed(messages):
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str):
                return content.strip()
            if isinstance(content, list):
                parts = [
                    str(item.get("text") or "")
                    for item in content
                    if isinstance(item, dict) and item.get("text")
                ]
                return "\n".join(parts).strip()
        content = getattr(message, "content", None)
        if isinstance(content, str):
            return content.strip()
    return ""


def _style_analysis_samples(emails: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "subject": email.get("subject") or "",
            "body": str(email.get("body") or "")[:3000],
            "snippet": email.get("snippet") or "",
        }
        for email in emails[:12]
    ]


def _normalize_style_profile(
    value: Any,
    *,
    sample_count: int | None = None,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        value = {}
    confidence = _simple_text(str(value.get("confidence") or "low"))
    if confidence not in {"low", "medium", "high"}:
        confidence = "low"

    profile = {
        "tone": _compact_style_text(value.get("tone")) or "professional",
        "greeting_style": _compact_style_text(value.get("greeting_style")) or "",
        "signoff_style": _compact_style_text(value.get("signoff_style")) or "",
        "typical_length": _compact_style_text(value.get("typical_length"), max_length=40) or "unknown",
        "structure": _clean_string_list(value.get("structure")),
        "common_phrasing": _clean_string_list(value.get("common_phrasing")),
        "confidence": confidence,
    }
    if sample_count is not None:
        profile["sample_count"] = sample_count
    elif isinstance(value.get("sample_count"), int):
        profile["sample_count"] = value["sample_count"]
    if value.get("source"):
        profile["source"] = _compact_style_text(value.get("source"), max_length=40)
    if value.get("note"):
        profile["note"] = _compact_style_text(value.get("note"), max_length=160)
    return profile


def _low_confidence_style_profile(note: str, *, sample_count: int = 0) -> dict[str, Any]:
    return {
        "tone": "professional",
        "greeting_style": "",
        "signoff_style": "",
        "typical_length": "unknown",
        "structure": [],
        "common_phrasing": [],
        "confidence": "low",
        "sample_count": sample_count,
        "source": "sent_mail",
        "note": note,
    }


def _style_profile_from_preference(user_message: str) -> dict[str, Any]:
    signoff = _clean_text(user_message).strip(" \"'")
    if _simple_text(signoff) in {"none", "no signoff", "no sign-off", "dont use one", "don't use one"}:
        signoff = ""
    elif signoff and len(signoff.split()) <= 5 and not signoff.endswith(","):
        signoff = f"{signoff},"
    return {
        "tone": "professional",
        "greeting_style": "Hi FirstName,",
        "signoff_style": signoff,
        "typical_length": "concise",
        "structure": ["acknowledge", "answer", "next step"],
        "common_phrasing": [],
        "confidence": "medium",
        "sample_count": 0,
        "source": "user_preference",
    }


def _style_profile_is_usable(profile: dict[str, Any] | None) -> bool:
    return bool(profile and profile.get("confidence") in {"medium", "high"})


def _style_preference_question() -> str:
    return "What sign-off should I use for your emails?"


def _style_preference_data(profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "email_style_profile": _public_style_profile(profile),
        "suggested_actions": ["Reply with the sign-off you want me to use."],
    }


def _public_style_profile(profile: dict[str, Any]) -> dict[str, Any]:
    return _normalize_style_profile(profile)


def _apply_email_style_to_draft(
    draft: dict[str, Any],
    email_style_profile: dict[str, Any] | None,
    selected_email: dict[str, Any] | None,
) -> dict[str, Any]:
    resolved = _merge_draft({}, draft)
    profile = _normalize_style_profile(email_style_profile)
    if not _style_profile_is_usable(profile):
        return resolved

    body = _clean_email_body(resolved.get("body"))
    greeting = _resolved_greeting(profile.get("greeting_style"), selected_email)
    if greeting and body and not _starts_with_greeting(body):
        body = f"{greeting}\n\n{body}"

    signoff = str(profile.get("signoff_style") or "").strip()
    if signoff and body and not _ends_with_signoff(body):
        body = f"{body.rstrip()}\n\n{signoff}"

    resolved["body"] = _clean_email_body(body)
    return resolved


def _resolved_greeting(greeting_style: Any, selected_email: dict[str, Any] | None) -> str:
    greeting = _clean_email_body(greeting_style)
    if not greeting:
        return ""
    name = ""
    if selected_email:
        parsed_name, address = parseaddr(str(selected_email.get("sender") or ""))
        name = parsed_name.split()[0] if parsed_name else address.split("@", 1)[0]
    if not name:
        return ""
    return (
        greeting.replace("FirstName", name)
        .replace("First Name", name)
        .replace("[Name]", name)
        .replace("{name}", name)
    )


def _starts_with_greeting(body: str) -> bool:
    first_line = _first_nonempty_line(body)
    return bool(re.match(r"^(hi|hello|hey|dear)\b[^,\n]*,?$", first_line, flags=re.IGNORECASE))


def _ends_with_signoff(body: str) -> bool:
    for line in reversed([line.strip() for line in body.splitlines() if line.strip()]):
        if re.match(r"^(best|best regards|regards|thanks|thank you|sincerely|cheers|respectfully),?$", line, re.I):
            return True
        return False
    return False


def _first_nonempty_line(value: str) -> str:
    for line in value.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def _clean_email_body(value: Any) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return ""

    lines = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("```"):
            continue
        line = re.sub(r"^#{1,6}\s+", "", line)
        line = re.sub(r"^\s*>\s?", "", line)
        line = re.sub(r"\*\*([^*]+)\*\*", r"\1", line)
        line = re.sub(r"__([^_]+)__", r"\1", line)
        lines.append(line)

    cleaned = "\n".join(lines).strip()
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = _remove_duplicate_boundary_lines(cleaned, _starts_with_greeting, from_start=True)
    cleaned = _remove_duplicate_boundary_lines(cleaned, _ends_with_signoff, from_start=False)
    return cleaned.strip()


def _remove_duplicate_boundary_lines(text: str, matcher: Any, *, from_start: bool) -> str:
    lines = text.splitlines()
    indexed = range(len(lines)) if from_start else range(len(lines) - 1, -1, -1)
    matched_indices: list[int] = []
    for index in indexed:
        if not lines[index].strip():
            continue
        if matcher(lines[index]):
            matched_indices.append(index)
            continue
        break
    if len(matched_indices) <= 1:
        return text
    for index in matched_indices[1:]:
        lines[index] = ""
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _clean_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_compact_style_text(item) for item in value[:8] if _compact_style_text(item)]


def _compact_style_text(value: Any, *, max_length: int = 120) -> str:
    text = _clean_text(value)
    if len(text) <= max_length:
        return text
    return text[:max_length].rstrip()


def _classify_shortcut(user_message: str, pending_send: bool, has_draft: bool) -> dict[str, Any] | None:
    text = _simple_text(user_message)
    if pending_send and re.search(r"\b(cancel|do not send|don't send|never mind|nevermind|stop)\b", text):
        return {"intent": AgentIntent.CANCEL_SEND.value, "query": user_message}
    if pending_send and re.search(r"\b(send it|send this|yes send|confirm|approved|go ahead|send now)\b", text):
        return {"intent": AgentIntent.CONFIRM_SEND.value, "query": user_message}
    if has_draft and re.search(r"\b(make|revise|change|shorter|longer|formal|casual|warmer|polite)\b", text):
        return {"intent": AgentIntent.REVISE_DRAFT.value, "query": user_message}
    if re.search(r"\b(cancel|do not send|don't send)\b", text):
        return {"intent": AgentIntent.CANCEL_SEND.value, "query": user_message}
    if re.search(r"\b(task|tasks|action item|action items|todo|to-do)\b", text):
        return {"intent": AgentIntent.EXTRACT_TASKS.value, "query": user_message}
    if re.search(r"\b(summarize|summary|latest|recent|inbox)\b", text):
        return {"intent": AgentIntent.SUMMARIZE_INBOX.value, "query": user_message}
    if re.search(r"\b(find|search|look for|what did|show me)\b", text):
        return {"intent": AgentIntent.SEARCH_EMAIL.value, "query": _normalize_query(user_message)}
    if re.search(r"\b(draft|reply|respond|write|send an email|send email)\b", text):
        return {"intent": AgentIntent.DRAFT_REPLY.value, "query": user_message}
    return None


def _normalize_query(value: str) -> str:
    query = value.strip()
    replacements = [
        r"^find emails? (about|from|with|for)\s+",
        r"^search emails? (about|from|with|for)\s+",
        r"^look for emails? (about|from|with|for)\s+",
        r"^show me emails? (about|from|with|for)\s+",
    ]
    lowered = query.lower()
    for pattern in replacements:
        match = re.match(pattern, lowered)
        if match:
            return query[match.end() :].strip(" .?") or query
    return query


def _email_to_dict(message: EmailMessage) -> dict[str, Any]:
    return message.model_dump(mode="json")


def _resolve_referenced_email(state: EmailAgentState) -> dict[str, Any] | None:
    emails = state.get("email_results") or []
    if not emails:
        return None
    text = _simple_text(state["user_message"])
    ordinal_index = [
        ("second", 1),
        ("2nd", 1),
        ("third", 2),
        ("3rd", 2),
        ("first", 0),
        ("1st", 0),
        ("two", 1),
        ("three", 2),
        ("one", 0),
    ]
    for word, index in ordinal_index:
        if re.search(rf"\b{word}\b", text) and index < len(emails):
            return emails[index]
    if re.search(r"\b(that email|this email|it)\b", text):
        return state.get("selected_email") or emails[0]
    return None


def _find_email_for_message(user_message: str, emails: list[dict[str, Any]]) -> dict[str, Any] | None:
    text = _simple_text(user_message)
    for email in emails:
        sender = _simple_text(str(email.get("sender") or ""))
        name, address = parseaddr(str(email.get("sender") or ""))
        if sender and sender in text:
            return email
        if name and _simple_text(name) in text:
            return email
        if address and _simple_text(address) in text:
            return email
    return emails[0] if emails else None


def _complete_draft_from_context(draft: dict[str, Any], selected_email: dict[str, Any] | None) -> dict[str, Any]:
    resolved = _merge_draft({}, draft)
    if selected_email:
        _, sender_email = parseaddr(str(selected_email.get("sender") or ""))
        if not resolved.get("to") and sender_email:
            resolved["to"] = sender_email
        if not resolved.get("subject") and selected_email.get("subject"):
            subject = str(selected_email["subject"])
            resolved["subject"] = subject if subject.lower().startswith("re:") else f"Re: {subject}"
    return resolved


def _merge_draft(base: dict[str, Any], update: dict[str, Any]) -> dict[str, Any]:
    return {
        "to": str(update.get("to") or base.get("to") or "").strip(),
        "subject": str(update.get("subject") or base.get("subject") or "").strip(),
        "body": _clean_email_body(update.get("body") or base.get("body") or ""),
        "cc": _list_value(update.get("cc") if update.get("cc") is not None else base.get("cc")),
        "bcc": _list_value(update.get("bcc") if update.get("bcc") is not None else base.get("bcc")),
        "missing_fields": _list_value(update.get("missing_fields")),
    }


def _missing_draft_fields(draft: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    recipient = str(draft.get("to") or "").strip()
    if not recipient or "@" not in parseaddr(recipient)[1]:
        missing.append("to")
    if not str(draft.get("subject") or "").strip():
        missing.append("subject")
    if not str(draft.get("body") or "").strip():
        missing.append("body")
    return missing


def _confirmation_response(draft: dict[str, Any]) -> str:
    return "\n".join(
        [
            "Draft ready. Please confirm before I send it.",
            "",
            f"To: {draft.get('to', '')}",
            f"Subject: {draft.get('subject', '')}",
            "Body:",
            str(draft.get("body") or ""),
        ]
    )


def _missing_fields_response(draft: dict[str, Any]) -> str:
    fields = ", ".join(draft.get("missing_fields") or _missing_draft_fields(draft))
    return f"I need the following before I can prepare this for sending: {fields}."


def _summary_response(payload: Any, emails: list[dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    source = payload if isinstance(payload, dict) else {"message": str(payload or ""), "summary": None}
    summary = _structured_summary_from_emails(emails, source.get("summary"))
    message = _clean_agent_response(source.get("message")) or _fallback_summary_message(emails)
    return message, {"summary": summary}


def _structured_summary_from_emails(
    emails: list[dict[str, Any]],
    llm_summary: Any = None,
) -> dict[str, Any]:
    source_items = llm_summary.get("items") if isinstance(llm_summary, dict) else []
    if not isinstance(source_items, list):
        source_items = []

    items: list[dict[str, Any]] = []
    for index, email in enumerate(emails[:10]):
        source_item = source_items[index] if index < len(source_items) and isinstance(source_items[index], dict) else {}
        items.append(
            {
                "rank": index + 1,
                "message_id": email.get("message_id"),
                "thread_id": email.get("thread_id"),
                "sender": email.get("sender") or "",
                "subject": email.get("subject") or "",
                "date_utc": _date_utc(email.get("received_at")),
                "snippet": email.get("snippet"),
                "main_point": _clean_text(source_item.get("main_point"))
                or _fallback_main_point(email),
                "action_required": _nullable_clean_text(source_item.get("action_required"))
                or _fallback_action_required(email),
                "urgency": _urgency(source_item.get("urgency"), email),
            }
        )

    notes = []
    if isinstance(llm_summary, dict) and isinstance(llm_summary.get("notes"), list):
        notes = [_clean_text(note) for note in llm_summary["notes"] if _clean_text(note)]
    if not notes:
        notes = ["Only metadata/snippets were included in the structured response."]
    return {"items": items, "notes": notes}


def _fallback_summary_message(emails: list[dict[str, Any]]) -> str:
    if not emails:
        return "I did not find any matching emails."
    subjects = [str(email.get("subject") or "").strip() for email in emails[:3]]
    subjects = [subject for subject in subjects if subject]
    if not subjects:
        return f"I found {len(emails)} email{'s' if len(emails) != 1 else ''}."
    return f"I found {len(emails)} email{'s' if len(emails) != 1 else ''}: {', '.join(subjects)}."


def _fallback_main_point(email: dict[str, Any]) -> str:
    return _clean_text(email.get("snippet")) or _clean_text(email.get("subject")) or "No summary available."


def _fallback_action_required(email: dict[str, Any]) -> str | None:
    text = _simple_text(" ".join([str(email.get("subject") or ""), str(email.get("snippet") or "")]))
    if re.search(r"\b(reply|respond|please|action|required|pending|incomplete|interview|security|alert)\b", text):
        return "Review and respond if needed."
    return None


def _urgency(value: Any, email: dict[str, Any]) -> str:
    urgency = _simple_text(str(value or ""))
    if urgency in {"low", "medium", "high", "unknown"}:
        return urgency
    text = _simple_text(" ".join([str(email.get("subject") or ""), str(email.get("snippet") or "")]))
    if re.search(r"\b(urgent|security|alert|pending|incomplete|interview|deadline|today)\b", text):
        return "medium"
    return "unknown"


def _date_utc(value: Any) -> str | None:
    if not value:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return str(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _draft_data(
    status: str,
    draft: dict[str, Any],
    email_style_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = {
        "draft_status": status,
        "missing_fields": draft.get("missing_fields") or [],
    }
    if email_style_profile:
        data["email_style_profile"] = _public_style_profile(email_style_profile)
    return data


def _send_data(
    status: str,
    draft: dict[str, Any],
    *,
    sent: bool,
    result: dict[str, Any] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    data = _draft_data(status, draft)
    data["send_result"] = {
        "sent": sent,
        "result": result or {},
        "error": error,
    }
    return data


def _tasks_data(response: str, emails: list[dict[str, Any]]) -> dict[str, Any]:
    items = _task_items(response)
    return {
        "tasks": {
            "items": items,
            "source_count": len(emails),
            "notes": ["Tasks are inferred from available email metadata/snippets."],
        }
    }


def _task_items(response: str) -> list[dict[str, Any]]:
    text = response.strip()
    if not text:
        return []
    candidates = [line.strip() for line in text.splitlines() if line.strip()]
    if len(candidates) == 1 and ":" in candidates[0]:
        candidates = [item.strip() for item in candidates[0].split(":", 1)[1].split(";") if item.strip()]
    items = []
    for index, item in enumerate(candidates, start=1):
        cleaned = re.sub(r"^[-*\d. )]+", "", item).strip()
        if cleaned:
            items.append({"rank": index, "task": cleaned})
    return items


def _clean_agent_response(value: Any) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return ""
    parsed_message = _message_from_json_dump(text)
    if parsed_message:
        text = parsed_message

    lines = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("```"):
            continue
        line = re.sub(r"^#{1,6}\s+", "", line)
        line = re.sub(r"\*\*([^*]+)\*\*", r"\1", line)
        line = re.sub(r"__([^_]+)__", r"\1", line)
        lines.append(line)
    cleaned = "\n".join(lines)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _message_from_json_dump(text: str) -> str | None:
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = "\n".join(line for line in candidate.splitlines() if not line.strip().startswith("```")).strip()
    if not (candidate.startswith("{") and candidate.endswith("}")):
        return None
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    for key in ("message", "response", "answer"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _nullable_clean_text(value: Any) -> str | None:
    text = _clean_text(value)
    if not text or text.lower() in {"none", "null", "n/a"}:
        return None
    return text


def _append_tool_event(
    state: EmailAgentState,
    tool_name: str,
    tool_args: dict[str, Any],
    result_summary: dict[str, Any],
    success: bool = True,
    error: str | None = None,
) -> list[dict[str, Any]]:
    return [
        *state.get("tool_events", []),
        {
            "tool_name": tool_name,
            "tool_args": tool_args,
            "result_summary": result_summary,
            "success": success,
            "error": error,
        },
    ]


def _append_draft_event(state: EmailAgentState, draft: dict[str, Any], status: str) -> list[dict[str, Any]]:
    return [*state.get("draft_events", []), {"draft": draft, "status": status}]


def _append_send_event(
    state: EmailAgentState,
    draft: dict[str, Any],
    confirmed: bool,
    sent: bool,
    result: dict[str, Any] | None = None,
    error: str | None = None,
) -> list[dict[str, Any]]:
    return [
        *state.get("send_events", []),
        {
            "draft": draft,
            "confirmed": confirmed,
            "sent": sent,
            "result": result or {},
            "error": error,
        },
    ]


def _tool_error_payload(exc: Exception) -> dict[str, Any]:
    message = str(getattr(exc, "message", "") or exc).strip() or "Unknown tool failure."
    details = getattr(exc, "details", None)
    return {
        "type": exc.__class__.__name__,
        "message": message,
        "details": details if isinstance(details, dict) else {},
    }


def _summarize_email_results(emails: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "count": len(emails),
        "messages": [
            {
                "message_id": email.get("message_id"),
                "thread_id": email.get("thread_id"),
                "sender": email.get("sender"),
                "subject": email.get("subject"),
                "received_at": email.get("received_at"),
                "snippet": email.get("snippet"),
                "body_length": len(str(email.get("body") or "")),
            }
            for email in emails[:10]
        ],
    }


def _redact_send_args(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "to": payload.get("to"),
        "subject": payload.get("subject"),
        "cc": payload.get("cc") or [],
        "bcc": payload.get("bcc") or [],
        "body_length": len(str(payload.get("body") or "")),
    }


def _list_value(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _simple_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.lower()).strip()
