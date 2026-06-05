# LangGraph Studio

This folder keeps LangGraph Studio-only entrypoints separate from the production agent code.

## Fake Graph

`studio_graph_fake.py` uses deterministic fake Gmail, memory, and LLM services. It is the default graph in `langgraph.json` and does not need credentials.

Run it from the repo root:

```bash
uvx --from "langgraph-cli[inmem]" langgraph dev
```

Open the Studio URL printed by the command and select `email_agent_fake`.

Starter input:

```json
{
  "session_id": "studio-session-1",
  "user_id": "local-user",
  "user_message": "Find emails from Derek",
  "pending_send": false,
  "confirmation_required": false,
  "email_results": [],
  "selected_email": null,
  "draft": null,
  "data": {}
}
```

Follow-up input for the same session:

```json
{
  "session_id": "studio-session-1",
  "user_id": "local-user",
  "user_message": "Draft a reply to Derek"
}
```

## Real Graph

`studio_graph_real.py` wires the same graph to real Gmail MCP, Supabase memory, and Groq.

To test the real graph, point `langgraph.json` at:

```json
"email_agent_real": "./src/email_assistant_app/agent/studio/studio_graph_real.py:make_graph"
```

Only enable it when `.env` has the required Gmail, Supabase, and Groq settings.
