"""Language model helpers for the email agent."""

from __future__ import annotations

import json
from typing import Any

import httpx
from langchain_core.messages import HumanMessage, SystemMessage

from email_assistant_app.agent.intents import AgentIntent, VALID_INTENTS
from email_assistant_app.agent.prompts import (
    EMAIL_AGENT_SYSTEM_PROMPT,
    EMAIL_DRAFT_PROMPT,
    EMAIL_STRUCTURED_SUMMARY_PROMPT,
    EMAIL_STYLE_ANALYSIS_PROMPT,
    EMAIL_SUMMARY_PROMPT,
    INTENT_CLASSIFICATION_PROMPT,
)
from email_assistant_app.errors import ExternalServiceError


class EmailAgentLlm:
    """LLM operations used by the graph nodes."""

    def __init__(self, api_key: str, model: str, *, base_url: str) -> None:
        self.provider = "groq"
        self.model = model
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key

    async def classify_intent(
        self,
        user_message: str,
        memory_context: list[dict[str, Any]],
        pending_send: bool,
        has_draft: bool,
    ) -> dict[str, str]:
        """Classify the current user message into one supported intent."""
        content = await self._invoke_text(
            [
                SystemMessage(content=EMAIL_AGENT_SYSTEM_PROMPT),
                HumanMessage(
                    content="\n\n".join(
                        [
                            INTENT_CLASSIFICATION_PROMPT,
                            f"Pending send: {pending_send}",
                            f"Draft exists: {has_draft}",
                            f"Recent conversation: {json.dumps(memory_context[-8:], default=str)}",
                            f"User message: {user_message}",
                        ]
                    )
                ),
            ],
            json_mode=True,
        )
        payload = _json_object(content)
        intent = str(payload.get("intent") or AgentIntent.GENERAL_CHAT.value)
        if intent not in VALID_INTENTS:
            intent = AgentIntent.GENERAL_CHAT.value
        return {
            "intent": intent,
            "query": str(payload.get("query") or user_message).strip(),
            "reason": str(payload.get("reason") or ""),
        }

    async def summarize_emails(
        self,
        user_message: str,
        emails: list[dict[str, Any]],
        memory_context: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Summarize email result data for the user."""
        content = await self._invoke_text(
            [
                SystemMessage(content=EMAIL_AGENT_SYSTEM_PROMPT),
                HumanMessage(
                    content="\n\n".join(
                        [
                            EMAIL_SUMMARY_PROMPT,
                            EMAIL_STRUCTURED_SUMMARY_PROMPT,
                            f"User request: {user_message}",
                            f"Recent conversation: {json.dumps(memory_context[-8:], default=str)}",
                            f"Emails: {json.dumps(emails, default=str)}",
                        ]
                    )
                ),
            ],
            json_mode=True,
        )
        return _summary_payload(content)

    async def draft_email(
        self,
        user_message: str,
        selected_email: dict[str, Any] | None,
        email_results: list[dict[str, Any]],
        memory_context: list[dict[str, Any]],
        email_style_profile: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Generate an email draft JSON object."""
        content = await self._invoke_text(
            [
                SystemMessage(content=EMAIL_AGENT_SYSTEM_PROMPT),
                HumanMessage(
                    content="\n\n".join(
                        [
                            EMAIL_DRAFT_PROMPT,
                            f"User request: {user_message}",
                            f"Selected email: {json.dumps(selected_email or {}, default=str)}",
                            f"Recent email results: {json.dumps(email_results[:5], default=str)}",
                            f"Recent conversation: {json.dumps(memory_context[-8:], default=str)}",
                            f"Email style profile: {json.dumps(email_style_profile or {}, default=str)}",
                        ]
                    )
                ),
            ],
            json_mode=True,
        )
        return _draft_payload(content)

    async def revise_draft(
        self,
        user_message: str,
        draft: dict[str, Any],
        memory_context: list[dict[str, Any]],
        email_style_profile: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Revise an existing draft and return the full draft JSON object."""
        content = await self._invoke_text(
            [
                SystemMessage(content=EMAIL_AGENT_SYSTEM_PROMPT),
                HumanMessage(
                    content="\n\n".join(
                        [
                            EMAIL_DRAFT_PROMPT,
                            "Revise the existing draft. Return the complete revised JSON draft.",
                            f"User revision request: {user_message}",
                            f"Existing draft: {json.dumps(draft, default=str)}",
                            f"Recent conversation: {json.dumps(memory_context[-8:], default=str)}",
                            f"Email style profile: {json.dumps(email_style_profile or {}, default=str)}",
                        ]
                    )
                ),
            ],
            json_mode=True,
        )
        return _draft_payload(content)

    async def analyze_email_style(self, sent_emails: list[dict[str, Any]]) -> dict[str, Any]:
        """Analyze recent sent emails and return only a compact style profile."""
        content = await self._invoke_text(
            [
                SystemMessage(content=EMAIL_AGENT_SYSTEM_PROMPT),
                HumanMessage(
                    content="\n\n".join(
                        [
                            EMAIL_STYLE_ANALYSIS_PROMPT,
                            f"Recent sent emails: {json.dumps(sent_emails, default=str)}",
                        ]
                    )
                ),
            ],
            json_mode=True,
        )
        return _style_payload(content)

    async def extract_tasks(
        self,
        user_message: str,
        emails: list[dict[str, Any]],
        memory_context: list[dict[str, Any]],
    ) -> str:
        """Extract likely tasks from email results."""
        return await self._invoke_text(
            [
                SystemMessage(content=EMAIL_AGENT_SYSTEM_PROMPT),
                HumanMessage(
                    content="\n\n".join(
                        [
                            "Extract possible tasks and action items from these emails. Do not invent details.",
                            f"User request: {user_message}",
                            f"Recent conversation: {json.dumps(memory_context[-8:], default=str)}",
                            f"Emails: {json.dumps(emails, default=str)}",
                        ]
                    )
                ),
            ]
        )

    async def general_chat(self, user_message: str, memory_context: list[dict[str, Any]]) -> str:
        """Respond to a non-tool email-agent message."""
        return await self._invoke_text(
            [
                SystemMessage(content=EMAIL_AGENT_SYSTEM_PROMPT),
                HumanMessage(
                    content="\n\n".join(
                        [
                            "Answer briefly. If the user asks for an unavailable email action, say it is unsupported.",
                            f"Recent conversation: {json.dumps(memory_context[-8:], default=str)}",
                            f"User message: {user_message}",
                        ]
                    )
                ),
            ]
        )

    async def _invoke_text(self, messages: list[Any], *, json_mode: bool = False) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [_message_to_payload(message) for message in messages],
            "temperature": 0,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "authorization": f"Bearer {self._api_key}",
                        "content-type": "application/json",
                    },
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPStatusError as exc:  # pragma: no cover - exercised only with live Groq.
            raise ExternalServiceError(
                "LLM request failed.",
                details={
                    "provider": "groq",
                    "status_code": exc.response.status_code,
                    "error": _response_error(exc.response),
                },
            ) from exc
        except httpx.HTTPError as exc:  # pragma: no cover - exercised only with live Groq.
            raise ExternalServiceError(
                "LLM request failed.",
                details={"provider": "groq", "error": str(exc)},
            ) from exc
        return _groq_chat_content(data)


def _message_to_payload(message: Any) -> dict[str, str]:
    if isinstance(message, SystemMessage):
        role = "system"
    elif isinstance(message, HumanMessage):
        role = "user"
    else:
        role = "user"
    return {"role": role, "content": _message_content_to_text(message.content)}


def _groq_chat_content(data: dict[str, Any]) -> str:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ExternalServiceError("LLM response did not include choices.", details={"provider": "groq"})
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict):
        raise ExternalServiceError("LLM response did not include a message.", details={"provider": "groq"})
    return _message_content_to_text(message.get("content", ""))


def _response_error(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return response.text[:500]


def _message_content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(parts).strip()
    return str(content).strip()


def _json_object(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:].strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ExternalServiceError("LLM returned invalid JSON.", details={"content": content[:500]}) from exc
    if not isinstance(value, dict):
        raise ExternalServiceError("LLM JSON response must be an object.")
    return value


def _draft_payload(content: str) -> dict[str, Any]:
    payload = _json_object(content)
    missing_fields = payload.get("missing_fields") or []
    if not isinstance(missing_fields, list):
        missing_fields = [str(missing_fields)]
    return {
        "to": str(payload.get("to") or "").strip(),
        "subject": str(payload.get("subject") or "").strip(),
        "body": str(payload.get("body") or "").strip(),
        "cc": _string_list(payload.get("cc")),
        "bcc": _string_list(payload.get("bcc")),
        "missing_fields": [str(item) for item in missing_fields if str(item).strip()],
    }


def _summary_payload(content: str) -> dict[str, Any]:
    try:
        payload = _json_object(content)
    except ExternalServiceError:
        return {"message": content, "summary": None}
    if not isinstance(payload.get("summary"), dict):
        payload["summary"] = None
    return payload


def _style_payload(content: str) -> dict[str, Any]:
    payload = _json_object(content)
    confidence = str(payload.get("confidence") or "low").strip().lower()
    if confidence not in {"low", "medium", "high"}:
        confidence = "low"
    return {
        "tone": str(payload.get("tone") or "").strip(),
        "greeting_style": str(payload.get("greeting_style") or "").strip(),
        "signoff_style": str(payload.get("signoff_style") or "").strip(),
        "typical_length": str(payload.get("typical_length") or "").strip(),
        "structure": _string_list(payload.get("structure")),
        "common_phrasing": _string_list(payload.get("common_phrasing")),
        "confidence": confidence,
    }


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []
