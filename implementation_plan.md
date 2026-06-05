Real LangGraph Studio Testing Plan

Goal
Expose the email agent graph to LangGraph Studio in two modes:

1. Fake mode for quick graph/state debugging.
2. Real mode for actual Gmail MCP, sent-mail style learning, LLM drafting, and session continuity testing.

Do not over-engineer this. Keep it simple and local-first.

Implementation Tasks

1. Keep fake Studio graph

Create or keep:

src/email_assistant_app/agent/studio_graph_fake.py

Purpose:

* load the graph in Studio
* test routing
* inspect state transitions
* verify draft lifecycle
* avoid Gmail/MCP/LLM failures during first setup

Use fake services:

* FakeGmailMcpService
* FakeMemoryStore
* FakeAgentLlm

2. Add real Studio graph

Create:

src/email_assistant_app/agent/studio_graph_real.py

This should use the real app dependencies:

* real Gmail MCP service
* real memory/session store
* real LLM wrapper
* real approval service

Example shape:

from email_assistant_app.agent.graph import build_email_agent_graph
from email_assistant_app.agent.nodes import EmailAgentRuntime
from email_assistant_app.application.approval_service import ApprovalService

# import the real service classes used by the FastAPI app

# GmailMcpService

# SupabaseMemoryStore or real session memory store

# real LLM implementation

approval_service = ApprovalService()

runtime = EmailAgentRuntime(
gmail_service=real_gmail_service,
memory_store=real_memory_store,
llm=real_llm,
approval_service=approval_service,
)

graph = build_email_agent_graph(runtime)

3. Support switching between fake and real Studio graphs

Option A: edit langgraph.json manually.

Fake mode:

{
"graphs": {
"email_agent": "./src/email_assistant_app/agent/studio_graph_fake.py:graph"
}
}

Real mode:

{
"graphs": {
"email_agent": "./src/email_assistant_app/agent/studio_graph_real.py:graph"
}
}

Option B: expose both graphs:

{
"graphs": {
"email_agent_fake": "./src/email_assistant_app/agent/studio_graph_fake.py:graph",
"email_agent_real": "./src/email_assistant_app/agent/studio_graph_real.py:graph"
},
"env": ".env",
"dependencies": ["."]
}

Prefer Option B so both are available in Studio.

4. Real-mode validation tests in Studio

Test 1: Gmail inbox search

Input:
Show me emails from Derek

Expected:

* real Gmail MCP search runs
* matching inbox emails are returned
* state includes email_results
* message output is clean and readable

Test 2: Draft from selected email

Input:
Draft a reply

Expected:

* agent uses the selected email from session state
* source email analysis runs
* draft includes To, Subject, Body, and missing_fields
* reply subject uses Re: Original Subject

Test 3: Sent-mail style learning

Expected:

* real Gmail MCP queries: in:sent newer_than:180d
* compact style profile is generated
* raw sent email bodies are not persisted
* draft uses learned greeting/sign-off/tone

Test 4: Revision continuity

Input:
Make it shorter

Expected:

* existing draft is updated
* agent does not start a new draft
* previous To and Subject are preserved

Test 5: Send safety

Input:
Send it

Expected:

* send is blocked unless draft is complete and confirmation is explicit
* missing to/subject/body keeps pending_send=false
* no email is sent accidentally

5. Keep pytest coverage

Studio is for graph and state inspection.

Keep pytest for:

* individual node behavior
* cleanup functions
* draft validation
* style learning fallback
* no raw sent-body persistence
* session continuity logic

Run:

PYTHONDONTWRITEBYTECODE=1 uv run pytest -p no:cacheprovider

Acceptance Criteria

* langgraph dev starts successfully.
* Studio shows both fake and real graphs.
* Fake graph works without external services.
* Real graph can query actual Gmail through MCP.
* Real graph can learn style from sent mail.
* Drafts preserve context across follow-up turns.
* Agent output is clean and readable.
* Sending still requires explicit confirmation.

use the structure below as the agent package is so packed
src/email_assistant_app/agent/studio/
├── __init__.py
├── studio_graph_fake.py
├── studio_graph_real.py
└── README.md

update langgraph.json accordingly. That is probably the cleanest structure for the project as it grows.

That way, nobody wonders why Studio-specific files are mixed with production agent code.