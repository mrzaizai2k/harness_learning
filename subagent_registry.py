import os
import json
import time
import uuid
import asyncio
import logging
from typing import TypedDict, Annotated, Optional

import httpx
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langchain_core.messages import AIMessage

from a2a.client import A2ACardResolver, A2AClient
from a2a.types import MessageSendParams, SendMessageRequest

logger = logging.getLogger("orchestrator.subagent_registry")


# ==================================================
# Generic A2A graph (parameterized version of
# build_infotainment_graph, reusable for any agent URL)
# ==================================================

class A2AAgentState(TypedDict):
    """State schema compatible with DeepAgents. Must include 'messages'."""
    messages: Annotated[list, add_messages]


def _last_human_text(messages: list) -> str:
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
        kind = getattr(part_root, "kind", None)
        if kind == "text":
            text = getattr(part_root, "text", "")
            if text:
                collected.append(text)
        else:
            text_attr = getattr(part_root, "text", None)
            if text_attr:
                collected.append(text_attr)

    return " ".join(collected)


def make_a2a_graph(base_url: str, timeout: float = 300.0):
    """
    Build a single-node LangGraph runnable that forwards the last human
    message to the A2A agent at `base_url` and returns its text reply.

    This is a generalized, reusable version of build_infotainment_graph() —
    instead of being hardcoded to one agent's URL, it's parameterized so it
    can be built for *any* agent discovered via the registry.
    """

    async def _call_agent_async(state: A2AAgentState) -> dict:
        text = _last_human_text(state["messages"])

        async with httpx.AsyncClient(timeout=timeout) as httpx_client:
            try:
                resolver = A2ACardResolver(
                    httpx_client=httpx_client,
                    base_url=base_url,
                )
                agent_card = await resolver.get_agent_card()

                client = A2AClient(
                    httpx_client=httpx_client,
                    agent_card=agent_card,
                )

                req = SendMessageRequest(
                    id=uuid.uuid4().hex,
                    params=MessageSendParams(
                        message={
                            "role": "user",
                            "parts": [{"type": "text", "text": text}],
                            "messageId": uuid.uuid4().hex,
                        }
                    ),
                )

                response = await client.send_message(req)
                response_text = _extract_text_from_response(response)

            except Exception as e:
                error_msg = f"Error calling agent at {base_url}: {str(e)}"
                logger.error(error_msg)
                return {"messages": [AIMessage(content=f"(error: {error_msg})")]}

        return {"messages": [AIMessage(content=response_text or "(no response)")]}

    def _call_agent(state: A2AAgentState) -> dict:
        return asyncio.run(_call_agent_async(state))

    graph = StateGraph(A2AAgentState)
    graph.add_node("call_agent", _call_agent)
    graph.set_entry_point("call_agent")
    graph.add_edge("call_agent", END)
    return graph.compile()


# ==================================================
# SubAgentRegistry
# ==================================================

class SubAgentRegistry:
    """
    Reads agent_list.json (url + enabled flags per agent), fetches each
    agent's A2A agent-card metadata (name/description), builds a generic
    A2A LangGraph runnable per agent, and wraps each one as a
    CompiledSubAgent ready to be passed into create_deep_agent(subagents=...).

    Example agent_list.json:
        {
          "infotainment": {"url": "http://localhost:8004", "enabled": true},
          "todolist":     {"url": "http://localhost:8005", "enabled": true}
        }

    Usage:
        registry = SubAgentRegistry(agent_list_path="config/agent_list.json")
        subagents = registry.get_subagents()

        agent = create_deep_agent(
            ...,
            subagents=load_subagents(Path("./subagents.yaml")) + subagents,
        )
    """

    def __init__(
        self,
        agent_list_path: str = "config/agent_list.json",
        agent_card_path: str = "/.well-known/agent-card.json",
        agent_load_retries: int = 3,
        agent_load_retry_delay: float = 2.0,
    ):
        self.agent_list_path = agent_list_path
        self.agent_card_path = agent_card_path
        self.agent_load_retries = agent_load_retries
        self.agent_load_retry_delay = agent_load_retry_delay

        self._config_agents: dict = {}
        self._subagents: dict = {}  # agent_id -> CompiledSubAgent

    # --------------------------------------------------
    # loading
    # --------------------------------------------------

    def _load_config(self) -> dict:
        if not os.path.isfile(self.agent_list_path):
            logger.warning("Agent list file does not exist: %s", self.agent_list_path)
            return {}

        with open(self.agent_list_path, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except Exception as e:
                logger.error("Error reading agent list: %s", e)
                return {}

    def _fetch_agent_card(self, url: str) -> Optional[dict]:
        card_url = url.rstrip("/") + self.agent_card_path
        try:
            with httpx.Client(timeout=10) as client:
                r = client.get(card_url)
                if r.status_code == 200:
                    return r.json()
        except Exception as e:
            logger.error("card fetch error for %s: %s", card_url, e)
        return None

    def _build_subagent(self, agent_id: str, url: str):
        # Deferred import so this module doesn't hard-require deepagents
        # just to be imported (e.g. for testing make_a2a_graph in isolation).
        from deepagents import CompiledSubAgent

        card = None
        for attempt in range(1, self.agent_load_retries + 1):
            logger.info(
                "Fetching agent card for '%s' at %s (attempt %d/%d)",
                agent_id, url, attempt, self.agent_load_retries,
            )
            card = self._fetch_agent_card(url)
            if card:
                break
            if attempt < self.agent_load_retries:
                time.sleep(self.agent_load_retry_delay)

        if not card:
            logger.warning(
                "Agent '%s' at %s is unreachable after %d retries — skipping.",
                agent_id, url, self.agent_load_retries,
            )
            return None

        name = card.get("name") or agent_id
        description = card.get("description") or f"Sub agent for {agent_id}"

        return CompiledSubAgent(
            name=agent_id,
            description=description,
            runnable=make_a2a_graph(url),
        )

    def reload(self):
        """Reload subagents from the agent_list.json config file."""
        self._config_agents = self._load_config()
        self._subagents = {}

        for agent_id, info in self._config_agents.items():
            if not info.get("enabled", True):
                logger.debug("Agent '%s' is disabled — skipping", agent_id)
                continue

            url = info.get("url")
            if not url:
                logger.warning("Agent '%s' has no URL — skipping", agent_id)
                continue

            subagent = self._build_subagent(agent_id, url)
            if subagent is not None:
                self._subagents[agent_id] = subagent

        logger.info("Loaded subagents: %d", len(self._subagents))
        return self

    # --------------------------------------------------
    # public accessors
    # --------------------------------------------------

    def get_subagents(self, reload: bool = True) -> list:
        """Return a list of CompiledSubAgent objects, ready to pass into
        create_deep_agent(subagents=...)."""
        if reload or not self._subagents:
            self.reload()
        return list(self._subagents.values())

    def get(self, agent_id: str, reload: bool = False):
        if reload or agent_id not in self._subagents:
            self.reload()
        return self._subagents.get(agent_id)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    registry = SubAgentRegistry(agent_list_path="agent_list.json")
    subagents = registry.get_subagents()
    print(f"Loaded {len(subagents)} subagents:")
    for sa in subagents:
        print(f"- {sa['name']}: {sa['description']}")