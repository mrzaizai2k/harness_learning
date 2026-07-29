import os
import json
import uuid
import asyncio
import httpx
from typing import TypedDict, Annotated

from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langchain_core.messages import AIMessage, HumanMessage

from a2a.client import A2ACardResolver, A2AClient
from a2a.types import MessageSendParams, SendMessageRequest

# Default to localhost for host machine access
INFOTAINMENT_URL = os.environ.get("INFOTAINMENT_URL", "http://localhost:8004")


class InfotainmentState(TypedDict):
    """State schema compatible with DeepAgents.
    
    Must include 'messages' key for subagent communication.
    """
    messages: Annotated[list, add_messages]


def _last_human_text(messages: list) -> str:
    for msg in reversed(messages):
        content = getattr(msg, "content", None)
        if content and getattr(msg, "type", "human") == "human":
            return content if isinstance(content, str) else str(content)
    return ""


def _extract_text_from_response(response) -> str:
    """Extract text content from A2A response."""
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
        kind = getattr(part_root, "kind", None)
        if kind == "text":
            text = getattr(part_root, "text", "")
            if text:
                collected.append(text)
        else:
            # Try to get text attribute directly
            text_attr = getattr(part_root, "text", None)
            if text_attr:
                collected.append(text_attr)

    return " ".join(collected)


async def _call_infotainment_async(state: InfotainmentState) -> dict:
    text = _last_human_text(state["messages"])

    async with httpx.AsyncClient(timeout=300.0) as httpx_client:
        try:
            # Resolve agent card first
            resolver = A2ACardResolver(
                httpx_client=httpx_client,
                base_url=INFOTAINMENT_URL,
            )
            
            agent_card = await resolver.get_agent_card()
            
            # Create client with agent_card
            client = A2AClient(
                httpx_client=httpx_client,
                agent_card=agent_card,
            )

            # Build message request
            req = SendMessageRequest(
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
            response = await client.send_message(req)
            
            # Extract text from response
            response_text = _extract_text_from_response(response)
            
        except Exception as e:
            error_msg = f"Error calling infotainment agent: {str(e)}"
            print(error_msg)
            return {"messages": [AIMessage(content=f"(error: {error_msg})")]}

    return {"messages": [AIMessage(content=response_text or "(no response)")]}


def _call_infotainment(state: InfotainmentState) -> dict:
    """Synchronous wrapper for the async function"""
    return asyncio.run(_call_infotainment_async(state))


def build_infotainment_graph():
    graph = StateGraph(InfotainmentState)
    graph.add_node("call_infotainment", _call_infotainment)  # Use sync version
    graph.set_entry_point("call_infotainment")
    graph.add_edge("call_infotainment", END)
    return graph.compile()