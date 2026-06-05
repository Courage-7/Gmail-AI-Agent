# Handoff

## Current Goal

The project is now focused on the Docker Gmail MCP server `yashtekwani/gmail-mcp`.
The active app supports only:

- `listMessages`
- `findMessage`
- `sendMessage`

Phase 1 now adds a FastAPI-first email agent on top of those three tools. There is no CLI.
The default LLM provider is Groq using `openai/gpt-oss-120b`.

## Current Architecture

- FastAPI app shell with health, capabilities, approvals, Gmail message routes, and agent chat routes.
- LangGraph email agent in `src/email_assistant_app/agent/`.
- Supabase conversation memory store in `src/email_assistant_app/memory/`.
- Supabase schema in `db/supabase_memory_schema.sql`.
- Docker stdio MCP client in `src/email_assistant_app/integrations/mcp/gmail_docker_client.py`.
- Application-level Gmail MCP normalization and approval enforcement in `src/email_assistant_app/application/gmail_mcp_service.py`.
- Standalone live smoke test in `test_gmail_docker_mcp_tools.py`.

## Removed Scope

The previous Google OAuth Gmail API, Google Calendar API, LangSmith tracing, labels, digest, triage, threaded replies, and raw MCP tool routes remain removed from the active app.

Calendar is intentionally out of scope because the selected Docker Gmail MCP server does not expose calendar tools.

## Required Environment

```text
GROQ_API_KEY=
GROQ_MODEL=openai/gpt-oss-120b
GROQ_BASE_URL=https://api.groq.com/openai/v1
SUPABASE_URL=
SUPABASE_SERVICE_ROLE_KEY=
SUPABASE_ANON_KEY=
DEFAULT_USER_ID=local-user
EMAIL_ADDRESS=
EMAIL_PASSWORD=
IMAP_HOST=imap.gmail.com
IMAP_PORT=993
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
GMAIL_MCP_IMAGE=yashtekwani/gmail-mcp
TEST_SEND_TO=
```

`EMAIL_PASSWORD` must be a Gmail App Password.
`SUPABASE_SERVICE_ROLE_KEY` must stay server-side.

## Commands

```bash
uv sync
docker pull yashtekwani/gmail-mcp
uv run uvicorn email_assistant_app.main:app --reload
uv run pytest
uv run python test_gmail_docker_mcp_tools.py
```

Apply `db/supabase_memory_schema.sql` in Supabase before using `/agent/sessions` or `/agent/chat` with real memory.

## Verification

- Automated tests cover MCP response parsing, approval-gated sending, active API routes, LangGraph agent workflows, and removal of unsupported routes.
- The live Docker/Gmail smoke test sends a real email and should only be run with valid `.env` credentials.

## Agent Endpoints

- `POST /agent/sessions`
- `POST /agent/chat`

The agent persists conversation messages and audit events to Supabase, keeps transient follow-up state in process, and requires fresh confirmation before sending if the app restarts.
