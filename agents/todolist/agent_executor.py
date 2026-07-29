import json
import logging
import os
from pathlib import Path

from typing_extensions import override

from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.utils import new_agent_text_message

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("todo_agent")

# This file's folder is the agent's "project root": it holds AGENTS.md and skills/
PROJECT_DIR = Path(__file__).parent


def _get_user_text(context: RequestContext) -> str:
    msg = getattr(context, "message", None)
    if not msg:
        request = getattr(context, "request", None)
        if request:
            params = getattr(request, "params", None)
            if params:
                msg = getattr(params, "message", None)

    if not msg:
        return ""

    texts = []
    for part in getattr(msg, "parts", []):
        root = getattr(part, "root", part)
        if getattr(root, "kind", None) == "text":
            texts.append(root.text)

    return " ".join(texts)


class TodoAgentExecutor(AgentExecutor):
    """Turns a user request into a structured todo list.

    Uses langchain's `create_deep_agent`, which ships a `write_todos` tool
    out of the box. The actual todo items are not generated freely by the
    model: they live in skills/blog-plan/SKILL.md, and AGENTS.md instructs
    the agent to copy that list verbatim via write_todos when it applies.
    """

    def __init__(self, model: str | None = None):
        model = model or os.getenv("DEEPAGENT_MODEL", "openai:gpt-4.1-mini")

        # FilesystemBackend reads AGENTS.md / skills/ straight off disk,
        # so there's no need to manually load and seed file contents.
        backend = FilesystemBackend(root_dir=str(PROJECT_DIR), virtual_mode=True)

        self.agent = create_deep_agent(
            model=model,
            backend=backend,
            memory=["/AGENTS.md"],
            skills=["/skills/"],
        )

    async def run(self, text: str) -> dict:
        """Core logic, decoupled from the A2A event-queue protocol.

        Returns a plain dict: {"success": bool, "message": str, "data": {"todos": [...]}}
        """
        text = (text or "").strip()

        if not text:
            return {"success": False, "message": "Empty request.", "data": {"todos": []}}

        logger.info("Running todo agent for: %s", text)

        result = await self.agent.ainvoke(
            {"messages": [{"role": "user", "content": text}]},
            config={"configurable": {"thread_id": "todo-agent"}},
        )

        todos = result.get("todos", [])
        if not todos:
            return {"success": False, "message": "No todo list produced.", "data": {"todos": []}}

        return {
            "success": True,
            "message": f"Generated {len(todos)} todo items.",
            "data": {"todos": todos},
        }

    @override
    async def execute(self, context: RequestContext, event_queue: EventQueue):
        text = _get_user_text(context)
        logger.info("text: %s", text)

        result = await self.run(text)
        await event_queue.enqueue_event(new_agent_text_message(json.dumps(result)))

    @override
    async def cancel(self, context: RequestContext, event_queue: EventQueue):
        raise NotImplementedError()