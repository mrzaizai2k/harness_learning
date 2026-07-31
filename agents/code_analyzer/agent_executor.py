"""LLM-backed A2A executor for Code2Graph.

This version does NOT assume a local checkout of the codebase. It connects
to the SAME Docker sandbox container the orchestrator already created for a
given thread, then lets the deep agent:

  1. explore the sandbox filesystem to find the actual source tree,
  2. install/build the Graphify knowledge graph for it (`graphify .`),
  3. query that graph (`graphify query/path/explain`) to answer the user,
     citing real file:line evidence tagged EXTRACTED / INFERRED / AMBIGUOUS.

The thread id is hardcoded to "300529d1" per your current setup — see the
TODO below for how to make this dynamic later.
"""

from __future__ import annotations

import os
import json
import logging
from typing import Any

from typing_extensions import override

from langchain_openai import ChatOpenAI

from deepagents import create_deep_agent
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.utils import new_agent_text_message

from utils import read_config
from prompts import SYSTEM_PROMPT, GRAPHIFY_WORKFLOW_INSTRUCTIONS
from docker_sandbox import PydanticDockerSandboxBackend
from tool_manager import make_graphify_tools

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("code2graph_agent")


DOCKER_WORK_DIR = "/workspace"


def _message_parts(context: RequestContext) -> list[Any]:
    message = getattr(context, "message", None)
    if message is None:
        request = getattr(context, "request", None)
        params = getattr(request, "params", None) if request else None
        message = getattr(params, "message", None) if params else None
    return list(getattr(message, "parts", []) or [])


def _extract_payload(context: RequestContext) -> str | dict[str, Any]:
    """Extract user text (or structured data payload) from the request context."""
    texts: list[str] = []
    for part in _message_parts(context):
        root = getattr(part, "root", part)
        data = getattr(root, "data", None)
        if isinstance(data, dict):
            return data
        text = getattr(root, "text", None)
        if isinstance(text, str):
            texts.append(text)
    return " ".join(texts)


def _assistant_text(result: dict[str, Any]) -> str:
    """Extract the final assistant response returned by Deep Agents."""
    for message in reversed(result.get("messages", [])):
        role = getattr(message, "type", None) or getattr(message, "role", None)
        if role not in ("ai", "assistant"):
            continue
        content = getattr(message, "content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            texts = [
                item.get("text", "")
                for item in content
                if isinstance(item, dict) and item.get("type") == "text"
            ]
            return "\n".join(text for text in texts if text)
    return ""

def _get_metadata(context: RequestContext) -> dict:
    try:
        req = getattr(context, "_params", None)
        if not req:
            return {}

        message = getattr(req, "message", None)
        if not message:
            return {}

        return getattr(message, "metadata", {}) or {}

    except Exception:
        logger.exception("Failed to extract metadata")
        return {}
    

def _normalise_model_output(text: str) -> dict[str, Any]:
    """Convert the model's JSON response into the stable Code2Graph contract."""
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = candidate.removeprefix("```json").removeprefix("```")
        candidate = candidate.removesuffix("```").strip()

    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError:
        start, end = candidate.find("{"), candidate.rfind("}")
        if start < 0 or end <= start:
            payload = {"answer": text}
        else:
            try:
                payload = json.loads(candidate[start : end + 1])
            except json.JSONDecodeError:
                payload = {"answer": text}

    if not isinstance(payload, dict):
        payload = {"answer": text}

    answer = payload.get("answer")
    if not isinstance(answer, str) or not answer.strip():
        answer = text

    return {
        "answer": answer.strip(),
        "nodes": _object_list(payload.get("nodes")),
        "edges": _object_list(payload.get("edges")),
        "evidence": _object_list(payload.get("evidence")),
    }


def _object_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


class Code2GraphAgentExecutor(AgentExecutor):
    """
    Code2Graph Agent Executor. Attaches to the orchestrator's Docker sandbox
    for whichever thread_id is passed in the request metadata, caching one
    backend/agent pair per thread so repeat calls reuse the same container
    connection instead of reattaching every time.
    """

    def __init__(self, config_path: str = "config.yaml"):
        config = read_config(config_path)
        graphify_config = config.get("graphify", {})
        self.query_timeout = int(graphify_config.get("query_timeout_seconds", 120))
        self.build_timeout = int(graphify_config.get("build_timeout_seconds", 900))

        self.chat_model = ChatOpenAI(
            model="gpt-5.4-mini", api_key=os.environ.get("OPENAI_API_KEY")
        )

        # thread_id -> {"backend": ..., "agent": ...}
        self._threads: dict[str, dict[str, Any]] = {}

    def _get_or_create_thread(self, thread_id: str) -> dict[str, Any]:
        """Attach to (or reuse) the sandbox + agent for `thread_id`."""
        existing = self._threads.get(thread_id)
        if existing is not None:
            return existing

        container_name = f"deepagents_sandbox_{thread_id}"
        logger.info(
            "No cached agent for thread_id=%s — attaching to container %s",
            thread_id, container_name,
        )

        backend = PydanticDockerSandboxBackend.create(
            runtime="python-minimal",
            container_name=container_name,
            work_dir=DOCKER_WORK_DIR,
            session_id=thread_id,
            auto_copy_files=False,
        )
        backend.start()
        logger.info("Attached to container %s for thread_id=%s", container_name, thread_id)

        graphify_tools = make_graphify_tools(
            backend, query_timeout=self.query_timeout, build_timeout=self.build_timeout
        )

        agent = create_deep_agent(
            model=self.chat_model,
            backend=backend,
            tools=graphify_tools,
            memory=["/AGENTS.md"],
            system_prompt=f"{SYSTEM_PROMPT}\n\n{GRAPHIFY_WORKFLOW_INSTRUCTIONS}",
        )

        entry = {"backend": backend, "agent": agent}
        self._threads[thread_id] = entry
        return entry

    async def run(self, request: str | dict[str, Any], thread_id: str) -> dict[str, Any]:
        """
        Core agent logic decoupled from A2A event queue.

        Args:
            request: user text, or a structured payload dict.
            thread_id: identifies which sandbox/agent to route to.

        Returns:
            dict with keys: success (bool), message (str), data (dict | None)
        """
        text = (
            json.dumps(request, ensure_ascii=False)
            if isinstance(request, dict)
            else (request or "").strip()
        )
        if not text:
            return {"success": False, "message": "Empty request.", "data": None}

        logger.info(
            "Running Code2Graph agent (thread_id=%s) for input: %s", thread_id, text
        )

        thread = self._get_or_create_thread(thread_id)

        try:
            result = await thread["agent"].ainvoke(
                {"messages": [{"role": "user", "content": text}]},
                config={"configurable": {"thread_id": thread_id}},
            )
        except Exception as exc:
            logger.exception("Code2Graph agent invocation failed (thread_id=%s)", thread_id)
            return {
                "success": False,
                "message": f"Code2Graph agent failed: {exc}",
                "data": None,
            }

        if not result:
            return {
                "success": False,
                "message": "Agent produced no output.",
                "data": None,
            }

        model_text = _assistant_text(result)
        if not model_text:
            return {
                "success": False,
                "message": "The model did not produce a response.",
                "data": None,
            }

        data = _normalise_model_output(model_text)
        node_count = len(data["nodes"])
        edge_count = len(data["edges"])
        return {
            "success": True,
            "message": (
                f"Code2Graph completed with {node_count} nodes and "
                f"{edge_count} relationships."
            ),
            "data": data,
        }

    @override
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        """Handle incoming request and enqueue response event."""
        payload = _extract_payload(context)
        metadata = _get_metadata(context)
        thread_id = metadata.get("thread_id")
        logger.info("execute() dispatching to thread_id=%s (metadata=%s)", thread_id, metadata)

        result = await self.run(payload, thread_id)
        await event_queue.enqueue_event(
            new_agent_text_message(json.dumps(result, ensure_ascii=False))
        )

    @override
    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        """Cancel is not implemented in this sample."""
        raise NotImplementedError()

    def close(self) -> None:
        """
        Do NOT close containers here — they're owned/shared by the
        orchestrator per thread_id. Closing them from this agent would tear
        down state other agents/threads may still be using.
        """
        pass