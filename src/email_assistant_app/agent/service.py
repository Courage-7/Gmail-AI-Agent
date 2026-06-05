"""Application service for the FastAPI email-agent endpoints."""

from __future__ import annotations

from copy import deepcopy
from threading import Lock
from typing import Any

from email_assistant_app.agent.graph import build_email_agent_graph
from email_assistant_app.agent.nodes import AgentLlm, EmailAgentRuntime
from email_assistant_app.agent.state import EmailAgentState
from email_assistant_app.application.approval_service import ApprovalService
from email_assistant_app.application.gmail_mcp_service import GmailMcpService
from email_assistant_app.domain.agent import (
    AgentChatRequest,
    AgentChatResponse,
    AgentSessionCreateRequest,
    AgentSessionCreateResponse,
    AgentSessionListResponse,
    AgentSessionSummary,
)
from email_assistant_app.memory.store import MemoryStore


class InMemoryAgentStateStore:
    """Process-local transient LangGraph state keyed by session id."""

    def __init__(self) -> None:
        self._states: dict[str, EmailAgentState] = {}
        self._lock = Lock()

    def get(self, session_id: str) -> EmailAgentState | None:
        """Return a copy of the stored session state, if any."""
        with self._lock:
            state = self._states.get(session_id)
            return deepcopy(state) if state else None

    def save(self, session_id: str, state: EmailAgentState) -> None:
        """Store the transient state needed for follow-up references."""
        retained: EmailAgentState = {
            "session_id": state["session_id"],
            "user_id": state["user_id"],
            "intent": state.get("intent", ""),
            "query": state.get("query"),
            "email_results": state.get("email_results", []),
            "selected_email": state.get("selected_email"),
            "email_style_profile": state.get("email_style_profile"),
            "awaiting_style_preference": bool(state.get("awaiting_style_preference")),
            "style_preference_request": state.get("style_preference_request"),
            "draft": state.get("draft"),
            "pending_send": bool(state.get("pending_send")),
            "confirmation_required": bool(state.get("confirmation_required")),
            "response": state.get("response", ""),
            "data": state.get("data") or {},
            "error": state.get("error"),
        }
        with self._lock:
            self._states[session_id] = deepcopy(retained)


class EmailAgentService:
    """Run the LangGraph email agent and map results to API models."""

    def __init__(
        self,
        gmail_service: GmailMcpService,
        memory_store: MemoryStore,
        llm: AgentLlm,
        approval_service: ApprovalService,
        state_store: InMemoryAgentStateStore | None = None,
    ) -> None:
        self.memory_store = memory_store
        self.state_store = state_store or InMemoryAgentStateStore()
        runtime = EmailAgentRuntime(
            gmail_service=gmail_service,
            memory_store=memory_store,
            llm=llm,
            approval_service=approval_service,
        )
        self.graph = build_email_agent_graph(runtime)

    async def create_session(self, request: AgentSessionCreateRequest) -> AgentSessionCreateResponse:
        """Create a new persisted conversation session."""
        session_id = await self.memory_store.create_session(request.user_id, request.title)
        self.state_store.save(
            session_id,
            {
                "session_id": session_id,
                "user_id": request.user_id,
                "pending_send": False,
                "confirmation_required": False,
                "email_results": [],
                "selected_email": None,
                "email_style_profile": None,
                "awaiting_style_preference": False,
                "style_preference_request": None,
                "draft": None,
                "response": "",
                "data": {},
            },
        )
        return AgentSessionCreateResponse(session_id=session_id, user_id=request.user_id, title=request.title)

    async def list_sessions(self, user_id: str, limit: int = 20) -> AgentSessionListResponse:
        """List persisted sessions for a user so clients can continue them."""
        rows = await self.memory_store.list_sessions(user_id, limit)
        return AgentSessionListResponse(
            sessions=[
                AgentSessionSummary(
                    session_id=str(row.get("session_id") or row.get("id") or ""),
                    user_id=str(row.get("user_id") or user_id),
                    title=row.get("title"),
                    created_at=_optional_str(row.get("created_at")),
                    updated_at=_optional_str(row.get("updated_at")),
                )
                for row in rows
                if row.get("session_id") or row.get("id")
            ]
        )

    async def chat(self, request: AgentChatRequest) -> AgentChatResponse:
        """Run one user message through the graph."""
        session_id = request.session_id
        previous_state: dict[str, Any] = {}
        if session_id:
            previous_state = self.state_store.get(session_id) or {}
        else:
            session_id = await self.memory_store.create_session(request.user_id, "Swagger Chat")
            self.state_store.save(
                session_id,
                {
                    "session_id": session_id,
                    "user_id": request.user_id,
                    "pending_send": False,
                    "confirmation_required": False,
                    "email_results": [],
                    "selected_email": None,
                    "email_style_profile": None,
                    "awaiting_style_preference": False,
                    "style_preference_request": None,
                    "draft": None,
                    "response": "",
                    "data": {},
                },
            )
        initial_state = _new_turn_state(previous_state, request)
        initial_state["session_id"] = session_id
        result = await self.graph.ainvoke(initial_state)
        result_session_id = str(result.get("session_id") or session_id)
        self.state_store.save(result_session_id, result)
        return AgentChatResponse(
            session_id=result_session_id,
            intent=result.get("intent", "general_chat"),
            message=result.get("response", ""),
            data=_public_data(result.get("data")),
            pending_send=bool(result.get("pending_send")),
            draft=_public_draft(result.get("draft")),
        )


def _new_turn_state(previous_state: dict[str, Any], request: AgentChatRequest) -> EmailAgentState:
    return {
        **previous_state,
        "user_id": request.user_id,
        "user_message": request.message,
        "tool_events": [],
        "draft_events": [],
        "send_events": [],
        "tool_name": None,
        "tool_args": None,
        "tool_result": None,
        "data": {},
        "error": None,
    }


def _public_draft(draft: dict[str, Any] | None) -> dict[str, Any] | None:
    if not draft:
        return None
    return {
        "to": draft.get("to") or "",
        "subject": draft.get("subject") or "",
        "body": draft.get("body") or "",
        "cc": draft.get("cc") or [],
        "bcc": draft.get("bcc") or [],
        "missing_fields": draft.get("missing_fields") or [],
    }


def _public_data(data: Any) -> dict[str, Any]:
    if isinstance(data, dict):
        return data
    return {}


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)
