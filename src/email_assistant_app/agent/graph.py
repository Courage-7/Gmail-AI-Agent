"""LangGraph assembly for the email agent."""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from email_assistant_app.agent.intents import AgentIntent
from email_assistant_app.agent.nodes import EmailAgentRuntime
from email_assistant_app.agent.state import EmailAgentState


def build_email_agent_graph(runtime: EmailAgentRuntime) -> Any:
    """Build and compile the email-agent graph."""
    graph = StateGraph(EmailAgentState)
    graph.add_node("load_conversation_context", runtime.load_conversation_context)
    graph.add_node("classify_intent", runtime.classify_intent)
    graph.add_node("summarize_inbox", runtime.summarize_inbox_node)
    graph.add_node("search_email", runtime.search_email_node)
    graph.add_node("draft_reply", runtime.draft_reply_node)
    graph.add_node("revise_draft", runtime.revise_draft_node)
    graph.add_node("confirm_send", runtime.confirm_send_node)
    graph.add_node("cancel_send", runtime.cancel_send_node)
    graph.add_node("extract_tasks", runtime.extract_tasks_node)
    graph.add_node("general_chat", runtime.general_chat_node)
    graph.add_node("save_memory", runtime.save_memory)

    graph.add_edge(START, "load_conversation_context")
    graph.add_edge("load_conversation_context", "classify_intent")
    graph.add_conditional_edges(
        "classify_intent",
        route_by_intent,
        {
            AgentIntent.SUMMARIZE_INBOX.value: "summarize_inbox",
            AgentIntent.SEARCH_EMAIL.value: "search_email",
            AgentIntent.DRAFT_REPLY.value: "draft_reply",
            AgentIntent.REVISE_DRAFT.value: "revise_draft",
            AgentIntent.SEND_EMAIL.value: "draft_reply",
            AgentIntent.CONFIRM_SEND.value: "confirm_send",
            AgentIntent.CANCEL_SEND.value: "cancel_send",
            AgentIntent.EXTRACT_TASKS.value: "extract_tasks",
            AgentIntent.GENERAL_CHAT.value: "general_chat",
        },
    )
    for node_name in (
        "summarize_inbox",
        "search_email",
        "draft_reply",
        "revise_draft",
        "confirm_send",
        "cancel_send",
        "extract_tasks",
        "general_chat",
    ):
        graph.add_edge(node_name, "save_memory")
    graph.add_edge("save_memory", END)
    return graph.compile()


async def route_by_intent(state: EmailAgentState) -> str:
    """Return a supported conditional edge key for the current intent."""
    return state.get("intent") or AgentIntent.GENERAL_CHAT.value
