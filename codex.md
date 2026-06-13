You are helping me add a visual workflow builder to this existing AI project.

Context:
This project already uses some combination of LangGraph, FastAPI, LLMs, MCP servers/tools, internal tools, and possibly reusable skills. The goal is to add a separate React Flow-based workflow builder page where users can visually create workflows from nodes and edges, configure tools/LLMs/MCPs, run the workflow, and see real execution results on the page.

Important:
Do not implement code yet. First, study the codebase and produce a real implementation plan based on this project’s actual structure, frameworks, files, and conventions.

Your first task is codebase discovery.

Please inspect:
1. Frontend framework and routing structure.
2. Whether React is already used.
3. Whether React Flow or @xyflow/react is installed.
4. Backend framework structure, especially FastAPI routers/services.
5. Existing LangGraph graphs, agents, nodes, state models, persistence, streaming, and run logic.
6. Existing LLM client wrappers or model abstraction.
7. Existing MCP client/server integrations.
8. Existing tool registry, tool calling, skills, or plugin systems.
9. Existing auth, permissions, workspace/project/user model.
10. Existing database/storage patterns.
11. Existing real-time communication patterns: SSE, WebSockets, polling, background jobs.
12. Existing tests and preferred test style.

Target feature:
Add a separate workflow builder page, likely something like:

- `/workflow-builder`
- `/workflows`
- `/projects/:id/workflows`

The page should eventually support:
- A React Flow canvas.
- A node palette.
- Custom workflow nodes.
- Node configuration panel.
- Save/load workflow JSON.
- Backend node registry.
- Server-side workflow validation.
- Running workflows through the existing backend runtime.
- Streaming node status, logs, outputs, and final results back to the page.
- Support for LLM nodes, MCP tool nodes, internal tool nodes, condition/router nodes, and skill/subgraph nodes where appropriate.

Architecture goal:

Frontend:
React Flow should be used only as the visual editor and live run viewer.

Backend:
FastAPI should own workflow validation, permissions, execution, secrets, tool access, MCP access, and LangGraph compilation/execution.

Runtime:
Visual workflows should be translated into existing LangGraph/runtime concepts where possible. Do not duplicate existing agent logic unless necessary.

Security:
Treat workflow JSON from the browser as untrusted. Validate all node types, tool permissions, schemas, edges, execution limits, secrets, and user access on the backend.

Please produce a plan with these sections:

## 1. Codebase Findings
Summarize what you found in the actual project.

Include:
- Frontend location/framework.
- Backend location/framework.
- Existing LangGraph/runtime code.
- Existing tool/MCP/LLM abstractions.
- Existing auth/storage/realtime patterns.
- Relevant files and directories.

Do not invent files. Only mention files that exist.

## 2. Best Integration Strategy
Explain how React Flow should fit into this specific project.

Answer:
- Should this be a new page or integrated into an existing area?
- Where should frontend components live?
- Where should backend workflow APIs live?
- Should execution use existing LangGraph code directly or a new adapter layer?
- Should live updates use SSE, WebSockets, or polling based on the project’s current patterns?

## 3. Proposed Data Model
Design the workflow JSON shape for this project.

Include:
- Workflow object.
- Node object.
- Edge object.
- Node config.
- Run object.
- Run event object.
- Output/result shape.

Keep it compatible with React Flow but backend-friendly.

## 4. Backend API Plan
Propose exact endpoints, for example:

- `GET /api/workflow-node-types`
- `GET /api/workflows`
- `POST /api/workflows`
- `GET /api/workflows/{id}`
- `PUT /api/workflows/{id}`
- `POST /api/workflows/{id}/run`
- `GET /api/workflows/{id}/runs/{run_id}/events`

Adjust names to match this project’s route conventions.

For each endpoint, include:
- Purpose.
- Request shape.
- Response shape.
- Files likely to change.

## 5. Node Registry Plan
Design how this project should expose approved node types.

Include node types for:
- LLM calls.
- MCP tools.
- Existing internal tools.
- Existing skills/subgraphs if present.
- Conditions/routers.
- Input/output nodes.

Explain how node schemas should be discovered or defined.

## 6. LangGraph/Runtime Adapter Plan
Explain how visual workflow JSON should become an executable workflow.

Include:
- How to find entry and exit nodes.
- How to map visual nodes to existing executors.
- How to pass state between nodes.
- How to handle branching.
- How to handle errors.
- How to emit run events.
- What should be MVP versus later.

## 7. Frontend Component Plan
Propose components and their responsibilities.

Likely components:
- `WorkflowBuilderPage`
- `WorkflowCanvas`
- `NodePalette`
- `NodeConfigPanel`
- `RunPanel`
- `WorkflowToolbar`
- custom React Flow nodes

Include where these should live based on the repo structure.

## 8. MVP Implementation Phases
Give a phased implementation plan.

Phase 1 should be small and runnable:
- Display React Flow builder page.
- Hardcoded node types.
- Save/load JSON if possible.

Then:
- Backend registry.
- Validation.
- One executable internal tool node.
- One LLM node.
- Streaming run events.
- MCP nodes.
- Skills/subgraphs.
- Permissions/audit/history.

For each phase, include:
- Files to modify.
- Expected outcome.
- How to test it.

## 9. Risks And Decisions
Call out risks specific to this codebase.

Include:
- Security risks.
- Execution safety.
- Secrets handling.
- Long-running jobs.
- Cycles/loops.
- Permissions.
- MCP trust boundaries.
- Cost/token limits.
- Observability.

## 10. Open Questions
Ask only the questions that truly block implementation.

Do not ask generic questions if the codebase answers them.

## 11. Recommended First PR
Recommend the smallest first pull request that creates momentum without overcommitting.

Include:
- Scope.
- Files.
- Tests.
- Definition of done.

Rules:
- Do not edit code yet.
- Do not add dependencies yet unless you are only reporting that they are needed.
- Prefer existing project patterns.
- Do not introduce a new state management library unless the project already uses it or there is a strong reason.
- Do not expose raw MCP/tool execution from the browser.
- Do not hardcode secrets.
- Do not assume React Flow execution happens in the frontend.
- Be concrete and file-specific.