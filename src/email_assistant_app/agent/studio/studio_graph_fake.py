"""Credential-free LangGraph Studio graph for local node testing."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from email_assistant_app.agent.graph import build_email_agent_graph
from email_assistant_app.agent.nodes import EmailAgentRuntime
from email_assistant_app.domain.email import EmailMessage, GmailSendMessageResponse


@dataclass(frozen=True)
class StudioApproval:
    approval_id: str


class StudioApprovalService:
    """Minimal approval service for the fake Studio graph."""

    def __init__(self) -> None:
        self._count = 0

    def create(self, action_type: Any, payload: dict[str, Any]) -> StudioApproval:
        self._count += 1
        return StudioApproval(approval_id=f"studio-approval-{self._count}")

    def resume(self, request: Any) -> None:
        return None

    def require_approved(self, action_type: Any, payload: dict[str, Any], approval_id: str | None) -> None:
        return None


class StudioMemoryStore:
    """In-memory store scoped to the Studio dev server process."""

    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []
        self.tool_events: list[dict[str, Any]] = []
        self.draft_events: list[dict[str, Any]] = []
        self.send_events: list[dict[str, Any]] = []

    async def create_session(self, user_id: str, title: str | None = None) -> str:
        return f"studio-{len(self.messages) + 1}"

    async def get_recent_messages(self, session_id: str, limit: int = 20) -> list[dict[str, Any]]:
        rows = [row for row in self.messages if row["session_id"] == session_id]
        return rows[-limit:]

    async def save_message(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.messages.append(
            {
                "session_id": session_id,
                "role": role,
                "content": content,
                "metadata": metadata or {},
            }
        )

    async def save_tool_event(
        self,
        session_id: str,
        tool_name: str,
        tool_args: dict[str, Any],
        result_summary: dict[str, Any],
        success: bool,
        error: str | None = None,
    ) -> None:
        self.tool_events.append(
            {
                "session_id": session_id,
                "tool_name": tool_name,
                "tool_args": tool_args,
                "result_summary": result_summary,
                "success": success,
                "error": error,
            }
        )

    async def save_draft_event(self, session_id: str, draft: dict[str, Any], status: str) -> None:
        self.draft_events.append({"session_id": session_id, "draft": draft, "status": status})

    async def save_send_event(
        self,
        session_id: str,
        draft: dict[str, Any],
        confirmed: bool,
        sent: bool,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        self.send_events.append(
            {
                "session_id": session_id,
                "draft": draft,
                "confirmed": confirmed,
                "sent": sent,
                "result": result or {},
                "error": error,
            }
        )


class StudioAgentLlm:
    """Deterministic LLM double for Studio graph exploration."""

    async def classify_intent(
        self,
        user_message: str,
        memory_context: list[dict[str, Any]],
        pending_send: bool,
        has_draft: bool,
    ) -> dict[str, str]:
        return {"intent": "general_chat", "query": user_message, "reason": "studio fallback"}

    async def summarize_emails(
        self,
        user_message: str,
        emails: list[dict[str, Any]],
        memory_context: list[dict[str, Any]],
    ) -> dict[str, Any]:
        subjects = ", ".join(str(email.get("subject") or "") for email in emails)
        return {
            "message": f"Summary: {subjects}",
            "summary": {
                "items": [
                    {
                        "rank": index,
                        "main_point": email.get("subject") or "No subject",
                        "action_required": "Review and respond if needed.",
                        "urgency": "medium" if "Exam.net" in str(email.get("subject") or "") else "unknown",
                    }
                    for index, email in enumerate(emails, start=1)
                ],
                "notes": ["Studio fake data."],
            },
        }

    async def draft_email(
        self,
        user_message: str,
        selected_email: dict[str, Any] | None,
        email_results: list[dict[str, Any]],
        memory_context: list[dict[str, Any]],
        email_style_profile: dict[str, Any] | None,
    ) -> dict[str, Any]:
        signoff = ""
        if email_style_profile and email_style_profile.get("confidence") in {"medium", "high"}:
            signoff = str(email_style_profile.get("signoff_style") or "")
        body = "Thanks for the update. I will take care of it."
        if signoff:
            body = f"{body}\n\n{signoff}"
        return {
            "to": "",
            "subject": "",
            "body": body,
            "missing_fields": [],
        }

    async def revise_draft(
        self,
        user_message: str,
        draft: dict[str, Any],
        memory_context: list[dict[str, Any]],
        email_style_profile: dict[str, Any] | None,
    ) -> dict[str, Any]:
        revised = dict(draft)
        revised["body"] = "Dear recipient,\n\nThank you for the update. I will take care of it.\n\nBest regards,"
        return revised

    async def analyze_email_style(self, sent_emails: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "tone": "warm professional",
            "greeting_style": "Hi FirstName,",
            "signoff_style": "Best regards,",
            "typical_length": "concise",
            "structure": ["acknowledge", "answer", "next step"],
            "common_phrasing": ["Thanks for the update."],
            "confidence": "medium" if sent_emails else "low",
        }

    async def extract_tasks(
        self,
        user_message: str,
        emails: list[dict[str, Any]],
        memory_context: list[dict[str, Any]],
    ) -> str:
        return "Tasks: follow up on Exam.net."

    async def general_chat(self, user_message: str, memory_context: list[dict[str, Any]]) -> str:
        return "I can help summarize, search, draft, revise, and send confirmed emails."


class StudioGmailService:
    """Deterministic Gmail double for Studio graph exploration."""

    def __init__(self, approval_service: StudioApprovalService) -> None:
        self.approval_service = approval_service

    async def list_messages(self, request: Any) -> list[EmailMessage]:
        return [
            EmailMessage(
                message_id="m1",
                thread_id="t1",
                sender="Joana <joana@example.com>",
                subject="Exam.net setup",
                body="Please finish the Exam.net setup today.",
                snippet="Please finish the setup",
            ),
            EmailMessage(
                message_id="m2",
                thread_id="t2",
                sender="Derek <derek@example.com>",
                subject="Project update",
                body="Can you send the final note?",
                snippet="Final note",
            ),
        ]

    async def search_messages(self, request: Any) -> list[EmailMessage]:
        if request.query == "in:sent newer_than:180d":
            return [
                EmailMessage(
                    message_id="s1",
                    thread_id="st1",
                    sender="Me <me@example.com>",
                    subject="Re: Project update",
                    body="Hi Derek,\n\nThanks for the update. I will take care of it.\n\nBest regards,",
                    snippet="Thanks for the update.",
                )
            ]
        return [
            EmailMessage(
                message_id="m3",
                thread_id="t3",
                sender="Derek <derek@example.com>",
                subject=f"Derek result for {request.query}",
                body="Please reply when complete.",
                snippet="Reply when complete",
            )
        ]

    async def send_message(self, request: Any) -> GmailSendMessageResponse:
        return GmailSendMessageResponse(provider_message_id="studio-sent-1", message="sent", status="sent")


approval_service = StudioApprovalService()

runtime = EmailAgentRuntime(
    gmail_service=StudioGmailService(approval_service),
    memory_store=StudioMemoryStore(),
    llm=StudioAgentLlm(),
    approval_service=approval_service,
)

graph = build_email_agent_graph(runtime)
