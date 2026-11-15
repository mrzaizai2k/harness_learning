"""
DeepAgentRunner: one deep agent (tools, subagents, skills, AGENTS.md memory)
on top of one sandbox backend. It streams LangGraph v2 output per
`thread_id`; the `thread_id` in the config is what lets the shared
checkpointer resume a conversation after a crash or stop.

RunnerPool: one runner, and so one Docker sandbox, per conversation thread.
"""

import uuid

from deepagents import create_deep_agent
from deepagents.backends.protocol import BackendProtocol
from langchain.agents.middleware import TodoListMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver

from backend import config
from backend.crash import CrashMiddleware
from backend.docker_sandbox import PydanticDockerSandboxBackend
from backend.prompts import WRITE_TODOS_SYSTEM_PROMPT, WRITE_TODOS_TOOL
from backend.subagent_registry import SubAgentRegistry, load_subagents
from backend.tools import download_image, generate_hashtags, move_file, web_search

TOOLS = [web_search, download_image, generate_hashtags, move_file]


class DeepAgentRunner:
    """Start a task with `stream_run`, continue it with `stream_resume`."""

    def __init__(self, model: BaseChatModel, checkpointer: BaseCheckpointSaver, backend: BackendProtocol):
        self.backend = backend
        self.crash = CrashMiddleware()
        self._stop_requested = False

        subagents = (
            load_subagents(config.SUBAGENTS_YAML, {t.name: t for t in TOOLS})
            + SubAgentRegistry(agent_list_path=config.AGENT_LIST_PATH).get_subagents()
        )
        self.agent = create_deep_agent(
            model=model,
            backend=backend,
            tools=TOOLS,
            subagents=subagents,
            checkpointer=checkpointer,
            middleware=[
                TodoListMiddleware(system_prompt=WRITE_TODOS_SYSTEM_PROMPT, tool_description=WRITE_TODOS_TOOL),
                self.crash,
            ],
            memory=["./AGENTS.md"],
            skills=["./skills/"],
        )

        self._callbacks = []
        if config.LANGFUSE_ENABLED:
            from langfuse.langchain import CallbackHandler

            self._callbacks.append(CallbackHandler())

    @staticmethod
    def new_thread_id() -> str:
        return uuid.uuid4().hex[:8]

    def _config(self, thread_id: str) -> RunnableConfig:
        return {
            "configurable": {"thread_id": thread_id},
            "run_name": f"thread-{thread_id}",
            "callbacks": self._callbacks,
            "metadata": {"langfuse_session_id": thread_id},  # one Langfuse session per thread
        }

    def arm_crash(self) -> None:
        """The next tool call will raise (see crash.py)."""
        self.crash.arm()

    def request_stop(self) -> None:
        """Stop the current stream at the next chunk; the checkpoint is kept."""
        self._stop_requested = True

    def _stream(self, agent_input, thread_id: str):
        # v2 streaming: token chunks ("messages") and per-node deltas ("updates"),
        # including subagent namespaces. stream_events.EventMapper turns these
        # chunks into UI events.
        self._stop_requested = False
        stream = self.agent.stream(
            agent_input,
            self._config(thread_id),
            stream_mode=["updates", "messages"],
            subgraphs=True,
            version="v2",
        )
        try:
            for chunk in stream:
                yield {"type": "chunk", "data": chunk}
                if self._stop_requested:
                    yield {"type": "stopped"}
                    return
        except Exception as e:
            yield {"type": "crash", "error": str(e)}
        finally:
            stream.close()  # pyright: ignore[reportAttributeAccessIssue] -- it is a generator

    def stream_run(self, task: str, thread_id: str):
        """Start a new task on `thread_id`."""
        yield from self._stream({"messages": [{"role": "user", "content": task}]}, thread_id)

    def stream_resume(self, thread_id: str):
        """Continue `thread_id` from its last checkpoint (input None = resume)."""
        yield from self._stream(None, thread_id)

    def close(self) -> None:
        self.backend.close()  # pyright: ignore[reportAttributeAccessIssue] -- sandbox backend


class RunnerPool:
    """Lazily creates one runner per thread, each with its own Docker sandbox,
    so concurrent conversations never share a filesystem. The model and the
    checkpointer are shared (the checkpointer keys everything by thread_id)."""

    def __init__(self, model: BaseChatModel, checkpointer: BaseCheckpointSaver):
        self.model = model
        self.checkpointer = checkpointer
        self._runners: dict[str, DeepAgentRunner] = {}

    def __len__(self) -> int:
        return len(self._runners)

    def get(self, thread_id: str) -> DeepAgentRunner | None:
        return self._runners.get(thread_id)

    def get_or_create(self, thread_id: str) -> DeepAgentRunner:
        if thread_id not in self._runners:
            sandbox = PydanticDockerSandboxBackend.create(
                runtime=config.SANDBOX_RUNTIME,
                container_name=f"deepagents_sandbox_{thread_id}",
                work_dir=config.SANDBOX_WORKDIR,
                auto_copy_files=True,  # AGENTS.md, skills/ … (respects .dockerignore)
                source_dir=str(config.PROJECT_ROOT),
            )
            self._runners[thread_id] = DeepAgentRunner(self.model, self.checkpointer, sandbox)
        return self._runners[thread_id]

    def close(self, thread_id: str) -> bool:
        runner = self._runners.pop(thread_id, None)
        if runner is None:
            return False
        runner.close()
        return True

    def close_all(self) -> None:
        for thread_id in list(self._runners):
            self.close(thread_id)
