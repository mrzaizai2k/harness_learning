import os
import uuid

import httpx
from typing import TypedDict, Annotated

from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langchain_core.messages import AIMessage

from a2a.client import A2ACardResolver, ClientFactory, ClientConfig
from a2a.helpers import new_text_message, get_stream_response_text
from a2a.types import Role

INFOTAINMENT_URL = os.environ.get("INFOTAINMENT_URL", "http://localhost:8004/")


class InfotainmentState(TypedDict):
    messages: Annotated[list, add_messages]


def _last_human_text(messages: list) -> str:
    for msg in reversed(messages):
        content = getattr(msg, "content", None)
        if content and getattr(msg, "type", "human") == "human":
            return content if isinstance(content, str) else str(content)
    return ""


async def _call_infotainment(state: InfotainmentState) -> dict:
    text = _last_human_text(state["messages"])

    async with httpx.AsyncClient(timeout=60) as httpx_client:
        card_resolver = A2ACardResolver(httpx_client, INFOTAINMENT_URL)
        card = await card_resolver.get_agent_card()

        factory = ClientFactory(ClientConfig(httpx_client=httpx_client))
        client = factory.create(card)

        # v1.0: no more TextPart wrapper — use the helper to build the message directly
        message = new_text_message(text, role=Role.ROLE_USER)

        collected = []
        # v1.0: send_message now yields StreamResponse objects (task / message /
        # status_update / artifact_update), not bare Message or (Task, Update) tuples
        async for chunk in client.send_message(message):
            piece = get_stream_response_text(chunk)
            if piece:
                collected.append(piece)

    return {"messages": [AIMessage(content=" ".join(collected) or "(no response)")]}


def build_infotainment_graph():
    graph = StateGraph(InfotainmentState)
    graph.add_node("call_infotainment", _call_infotainment)
    graph.set_entry_point("call_infotainment")
    graph.add_edge("call_infotainment", END)
    return graph.compile()