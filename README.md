# Email Assistant App

FastAPI email agent backed by Groq, Supabase conversation memory, and the Docker Gmail MCP server `yashtekwani/gmail-mcp`.

The active Gmail surface is intentionally limited to the three validated MCP tools:

```text
listMessages
findMessage
sendMessage
```

Calendar, Gmail draft sync, labels, threaded replies, and Google OAuth are not part of this version.
Gmail draft sync is still out of scope; the agent creates in-app drafts and sends only after explicit confirmation.

## Setup

```bash
uv sync
cp .env.example .env
```

Configure Groq, Supabase, and Gmail App Password credentials in `.env`:

```text
GROQ_API_KEY=your_groq_api_key
GROQ_MODEL=openai/gpt-oss-120b
GROQ_BASE_URL=https://api.groq.com/openai/v1
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your_server_side_service_role_key
SUPABASE_ANON_KEY=your_anon_key_if_needed_else_blank
DEFAULT_USER_ID=local-user

EMAIL_ADDRESS=your-email@gmail.com
EMAIL_PASSWORD=your_16_character_gmail_app_password
IMAP_HOST=imap.gmail.com
IMAP_PORT=993
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
GMAIL_MCP_IMAGE=yashtekwani/gmail-mcp
TEST_SEND_TO=your-email@gmail.com
```

`EMAIL_PASSWORD` must be a Gmail App Password, not the normal Gmail account password.
Use `SUPABASE_SERVICE_ROLE_KEY` only server-side.

Apply the Supabase memory schema before using the agent endpoints:

```text
db/supabase_memory_schema.sql
```

Pull the MCP server image:

```bash
docker pull yashtekwani/gmail-mcp
```

## Verification

Run the standalone live MCP smoke test:

```bash
uv run python test_gmail_docker_mcp_tools.py
```

The script performs Docker/env preflight checks, calls all three MCP tools, sends a test email to `TEST_SEND_TO`, and writes `gmail_docker_mcp_test_report.md`.

Run automated tests:

```bash
uv run pytest
```

The live Docker MCP integration test is opt-in:

```bash
RUN_GMAIL_DOCKER_MCP_TESTS=true uv run pytest tests/integration/test_gmail_docker_mcp_connection.py -s
```

## Run API

```bash
uv run uvicorn email_assistant_app.main:app --reload
```

Swagger UI:

```text
http://127.0.0.1:8000/docs
```

## API

- `GET /health`
- `GET /capabilities`
- `POST /agent/sessions`
- `POST /agent/chat`
- `POST /gmail/messages/list`
- `POST /gmail/messages/search`
- `POST /gmail/messages/send`
- `POST /approvals/resume`

Sending email is approval-gated. First call `POST /gmail/messages/send` without `approval_id` to create an approval request, approve it with `/approvals/resume`, then retry the send with the approved `approval_id`.

The agent endpoint uses the same safety rule internally. It drafts first, shows `To`, `Subject`, and `Body`, and only calls Gmail after a clear confirmation such as "send it".

Create a session:

```bash
curl -X POST http://127.0.0.1:8000/agent/sessions \
  -H "content-type: application/json" \
  -d '{"user_id":"local-user","title":"Inbox"}'
```

Chat with the agent:

```bash
curl -X POST http://127.0.0.1:8000/agent/chat \
  -H "content-type: application/json" \
  -d '{"session_id":"SESSION_ID","user_id":"local-user","message":"Summarize my latest emails"}'
```

Response shape:

```json
{
  "session_id": "SESSION_ID",
  "intent": "summarize_inbox",
  "message": "I found 10 recent emails...",
  "data": {
    "summary": {
      "items": [
        {
          "rank": 1,
          "message_id": "string",
          "thread_id": "string",
          "sender": "Sender <sender@example.com>",
          "subject": "Subject",
          "date_utc": "2026-06-01T10:28:27Z",
          "snippet": "Short snippet",
          "main_point": "Main point",
          "action_required": "Review and respond if needed.",
          "urgency": "medium"
        }
      ],
      "notes": ["Only metadata/snippets were included in the structured response."]
    }
  },
  "pending_send": false,
  "draft": null
}
```

Example conversation:

```text
User: Summarize my latest emails
Agent: Summary of recent messages...

User: Find emails about Exam.net
Agent: Summary of matching messages...

User: Draft a reply to Derek
Agent: Draft ready. Please confirm before I send it.
To: derek@example.com
Subject: Re: ...
Body:
...

User: Make it more formal
Agent: Draft ready. Please confirm before I send it.

User: Send it
Agent: Sent the email.
```

Known limitations:

```text
No long-term user profile memory yet
No contact alias memory yet
No Gmail labels
No Gmail draft sync
No thread management
No delete/archive
No multi-user OAuth
No raw email body persistence by default
```
