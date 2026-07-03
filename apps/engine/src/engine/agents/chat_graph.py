"""Minimal LangGraph chat graph — the Phase 0 walking skeleton.

Phase 1 replaces this with the supervisor + specialist-team graphs (ADR-0005);
the streaming contract (custom writer events consumed as SSE) stays the same.
"""

import operator
from typing import Annotated, Any, TypedDict

from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph

from engine.llm.router import model_router

SYSTEM_PROMPT = (
    "You are ASEP, an AI software engineering platform. You help developers "
    "plan, implement, review, test, and document software. Answer clearly and "
    "concretely; when discussing code, prefer specific examples."
)


class ChatState(TypedDict):
    messages: Annotated[list[dict[str, Any]], operator.add]


async def respond(state: ChatState) -> dict[str, Any]:
    writer = get_stream_writer()
    llm_messages = [{"role": "system", "content": SYSTEM_PROMPT}, *state["messages"]]
    parts: list[str] = []
    async for token in model_router.stream("coder", llm_messages):
        writer({"type": "token", "text": token})
        parts.append(token)
    return {"messages": [{"role": "assistant", "content": "".join(parts)}]}


def build_chat_graph():
    graph = StateGraph(ChatState)
    graph.add_node("respond", respond)
    graph.add_edge(START, "respond")
    graph.add_edge("respond", END)
    return graph.compile()


chat_graph = build_chat_graph()
