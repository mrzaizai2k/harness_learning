import os
import uuid
import asyncio
import httpx
from typing import TypedDict, Annotated

from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langchain_core.messages import AIMessage

from a2a.client import A2ACardResolver, A2AClient
from a2a.types import MessageSendParams, SendMessageRequest

# Default to localhost for host machine access
TODO_AGENT_URL = os.environ.get(
    "TODO_AGENT_URL",
    "http://localhost:8005",
)


class TodoState(TypedDict):
    """State schema compatible with DeepAgents.

    Must include the `messages` key for subagent communication.
    """

    messages: Annotated[list, add_messages]


def _last_human_text(messages: list) -> str:
    """Return the latest user message."""
    for msg in reversed(messages):
        content = getattr(msg, "content", None)
        if content and getattr(msg, "type", "human") == "human":
            return content if isinstance(content, str) else str(content)
    return ""


def _extract_text_from_response(response) -> str:
    """Extract text content from an A2A response."""
    root = getattr(response, "root", response)
    result = getattr(root, "result", None)

    if not result:
        result = getattr(response, "result", None)

    if not result:
        return ""

    parts = getattr(result, "parts", None)
    if not parts:
        return ""

    collected = []

    for part in parts:
        part_root = getattr(part, "root", part)

        if getattr(part_root, "kind", None) == "text":
            text = getattr(part_root, "text", "")
            if text:
                collected.append(text)
        else:
            text = getattr(part_root, "text", None)
            if text:
                collected.append(text)

    return " ".join(collected)


async def _call_todo_async(state: TodoState) -> dict:
    """Call the Todo A2A agent."""
    text = _last_human_text(state["messages"])

    async with httpx.AsyncClient(timeout=300.0) as httpx_client:
        try:
            # Resolve the Todo agent card
            resolver = A2ACardResolver(
                httpx_client=httpx_client,
                base_url=TODO_AGENT_URL,
            )

            agent_card = await resolver.get_agent_card()

            # Create A2A client
            client = A2AClient(
                httpx_client=httpx_client,
                agent_card=agent_card,
            )

            # Build request
            request = SendMessageRequest(
                id=uuid.uuid4().hex,
                params=MessageSendParams(
                    message={
                        "role": "user",
                        "parts": [
                            {
                                "type": "text",
                                "text": text,
                            }
                        ],
                        "messageId": uuid.uuid4().hex,
                    }
                ),
            )

            # Send message
            response = await client.send_message(request)

            response_text = _extract_text_from_response(response)

        except Exception as e:
            error = f"Error calling Todo agent: {e}"
            print(error)
            return {
                "messages": [
                    AIMessage(content=f"(error: {error})"),
                ]
            }

    return {
        "messages": [
            AIMessage(content=response_text or "(no response)"),
        ]
    }


def _call_todo(state: TodoState) -> dict:
    """Synchronous wrapper for the async Todo client."""
    return asyncio.run(_call_todo_async(state))


def build_todo_graph():
    """Build a LangGraph wrapper around the Todo A2A agent."""
    graph = StateGraph(TodoState)

    graph.add_node("call_todo", _call_todo)

    graph.set_entry_point("call_todo")
    graph.add_edge("call_todo", END)

    return graph.compile()