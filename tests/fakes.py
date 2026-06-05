from __future__ import annotations

from typing import Any

from email_assistant_app.application.approval_service import ApprovalService
from email_assistant_app.domain.action import ActionType
from email_assistant_app.domain.email import EmailMessage, GmailSendMessageResponse


class FakeMemoryStore:
    def __init__(self) -> None:
        self.session_count = 0
        self.sessions: list[dict[str, Any]] = []
        self.messages: list[dict[str, Any]] = []
        self.tool_events: list[dict[str, Any]] = []
        self.draft_events: list[dict[str, Any]] = []
        self.send_events: list[dict[str, Any]] = []

    async def create_session(self, user_id: str, title: str | None = None) -> str:
        self.session_count += 1
        session_id = f"session-{self.session_count}"
        self.sessions.append(
            {
                "session_id": session_id,
                "user_id": user_id,
                "title": title,
                "created_at": f"2026-06-03T00:00:0{self.session_count}Z",
                "updated_at": f"2026-06-03T00:00:0{self.session_count}Z",
            }
        )
        return session_id

    async def list_sessions(self, user_id: str, limit: int = 20) -> list[dict[str, Any]]:
        rows = [session for session in self.sessions if session["user_id"] == user_id]
        return list(reversed(rows))[:limit]

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


class FakeAgentLlm:
    async def classify_intent(
        self,
        user_message: str,
        memory_context: list[dict[str, Any]],
        pending_send: bool,
        has_draft: bool,
    ) -> dict[str, str]:
        return {"intent": "general_chat", "query": user_message, "reason": "fallback"}

    async def summarize_emails(
        self,
        user_message: str,
        emails: list[dict[str, Any]],
        memory_context: list[dict[str, Any]],
    ) -> dict[str, Any]:
        subjects = ", ".join(email.get("subject", "") for email in emails)
        return {
            "message": f"Summary: {subjects}",
            "summary": {
                "items": [
                    {
                        "rank": index,
                        "main_point": email.get("subject", ""),
                        "action_required": "Review and respond if needed.",
                        "urgency": "medium" if "Exam.net" in str(email.get("subject", "")) else "unknown",
                    }
                    for index, email in enumerate(emails, start=1)
                ],
                "notes": ["Fake summary data."],
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
        if "derek" in user_message.lower() and not selected_email:
            return {
                "to": "Derek",
                "subject": "Hello",
                "body": _with_signoff("Hi Derek, thanks for the update.", signoff),
                "missing_fields": [],
            }
        return {
            "to": "",
            "subject": "",
            "body": _with_signoff("Thanks for the update. I will take care of it.", signoff),
            "missing_fields": [],
        }

    async def revise_draft(
        self,
        user_message: str,
        draft: dict[str, Any],
        memory_context: list[dict[str, Any]],
        email_style_profile: dict[str, Any] | None,
    ) -> dict[str, Any]:
        updated = dict(draft)
        updated["body"] = "Dear recipient,\n\nThank you for the update. I will take care of it.\n\nBest regards,"
        return updated

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
        return "I can help summarize, search, draft, and send confirmed emails."


class FakeGmailMcpService:
    def __init__(self, approval_service: ApprovalService) -> None:
        self.approval_service = approval_service
        self.sent_payloads: list[dict[str, Any]] = []
        self.list_calls = 0
        self.search_calls: list[str] = []

    async def list_messages(self, request) -> list[EmailMessage]:
        self.list_calls += 1
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

    async def search_messages(self, request) -> list[EmailMessage]:
        self.search_calls.append(request.query)
        if request.query == "in:sent newer_than:180d":
            return [
                EmailMessage(
                    message_id="s1",
                    thread_id="st1",
                    sender="Me <me@example.com>",
                    subject="Re: Project update",
                    body="Hi Derek,\n\nThanks for the update. I will take care of it.\n\nBest regards,",
                    snippet="Thanks for the update.",
                ),
                EmailMessage(
                    message_id="s2",
                    thread_id="st2",
                    sender="Me <me@example.com>",
                    subject="Re: Exam.net setup",
                    body="Hi Joana,\n\nI completed the setup and will follow up if anything changes.\n\nBest regards,",
                    snippet="I completed the setup.",
                ),
            ]
        return [
            EmailMessage(
                message_id="m3",
                thread_id="t3",
                sender="Joana <joana@example.com>",
                subject=f"Exam.net result for {request.query}",
                body="Exam.net is ready.",
                snippet="Ready",
            ),
            EmailMessage(
                message_id="m4",
                thread_id="t4",
                sender="Derek <derek@example.com>",
                subject="Derek result",
                body="Please reply when complete.",
                snippet="Reply when complete",
            ),
        ]

    async def send_message(self, request) -> GmailSendMessageResponse:
        payload = request.model_dump(mode="json", exclude={"approval_id"})
        self.approval_service.require_approved(ActionType.SEND_EMAIL, payload, request.approval_id)
        self.sent_payloads.append(payload)
        return GmailSendMessageResponse(provider_message_id="sent-1", message="sent", status="sent")


def _with_signoff(body: str, signoff: str) -> str:
    if not signoff:
        return body
    return f"{body}\n\n{signoff}"
