"""
DeepAgentRunner
===============
A thin, UI-friendly wrapper around the deepagents / langgraph checkpointing
demo. Same core idea as the original script:

    config = {"configurable": {"thread_id": ...}}

is the ONLY thing that tells the checkpointer which conversation/state to
load. One agent object, one checkpointer -> many independent threads.

Backend
-------
`DeepAgentRunner` now takes a `backend` (anything implementing deepagents'
`SandboxBackendProtocol`) instead of hardcoding `FilesystemBackend`. Pass:
  * nothing                -> local `FilesystemBackend` (original behavior)
  * `use_docker=True`      -> a `PydanticDockerSandboxBackend` is created for
                              you, wrapping a `pydantic_ai_backends.DockerSandbox`
  * `backend=<your obj>`   -> any backend you've already built, e.g. a
                              `PydanticDockerSandboxBackend` wired to a
                              persistent, named container, or one pulled from
                              a `PydanticDockerSandboxManager` for a specific
                              user

Because `list_files` / `read_file` now go through `backend.ls()` /
`backend.read()` instead of raw `os.listdir` / `open()`, they work
identically no matter which backend is plugged in — local disk or Docker
container.
"""

import os
import uuid

from dotenv import load_dotenv
# from langgraph.checkpoint.memory import InMemorySaver
from json_saver import JsonFileSaver
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend
from deepagents.backends.sandbox import SandboxBackendProtocol
from pydantic_ai_backends import RuntimeConfig

from docker_sandbox import PydanticDockerSandboxBackend

load_dotenv()


class CrashController:
    """
    A shared, mutable flag that tools consult before doing their work.
    When armed, the NEXT tool call raises an exception (simulating a
    crashed process) and then automatically disarms itself.
    """

    def __init__(self):
        self.armed = False

    def arm(self):
        self.armed = True

    def maybe_crash(self, context: str):
        if self.armed:
            self.armed = False  # fires once, like the original flaky_read
            raise RuntimeError(f"Simulated crash during: {context}")


class DeepAgentRunner:
    """
    Wraps one agent + one checkpointer. Call `new_thread_id()` to start an
    independent task, `stream_run(task, thread_id)` to start it, and
    `stream_resume(thread_id)` to continue after a crash.
    """

    def __init__(
        self,
        model_name: str = "gpt-4.1-mini",
        root_dir: str | None = None,
        backend: SandboxBackendProtocol | None = None,
        use_docker: bool = False,
        docker_runtime: str | RuntimeConfig | None = "python-minimal",
        docker_container_name: str | None = None,
        docker_volumes: dict[str, str] | None = None,
        docker_work_dir: str = "/workspace",
        model: ChatOpenAI | None = None,
        checkpointer: JsonFileSaver | None = None,
    ):
        """
        `model` and `checkpointer` can be injected so multiple `DeepAgentRunner`
        instances (e.g. one per conversation thread, each with its own Docker
        container) share the same underlying model client and checkpoint
        store instead of each constructing their own. This matters most for
        `checkpointer`: multiple `JsonFileSaver` instances all pointing at the
        same `state.json` risk clobbering each other's writes under
        concurrent access, whereas one shared instance safely multiplexes
        threads via `thread_id` in `config`, same as the original design.
        """
        # Default to the folder this file lives in, NOT the process's cwd —
        # otherwise behavior silently depends on where `streamlit run` was
        # launched from. Only meaningful for the local FilesystemBackend;
        # Docker backends use their own in-container workdir.
        self.root_dir = os.path.abspath(root_dir or os.path.dirname(__file__))

        self.crash_controller = CrashController()
        self.checkpointer = checkpointer or JsonFileSaver(state_path="state.json", memory_path="memory.json")
        self.model = model or ChatOpenAI(model=model_name, api_key=os.environ.get("OPENAI_API_KEY"))

        if backend is not None and use_docker:
            raise ValueError("Pass either `backend` or `use_docker=True`, not both.")

        if backend is not None:
            self.backend = backend
        elif use_docker:
            self.backend = PydanticDockerSandboxBackend.create(
                runtime=docker_runtime,
                container_name=docker_container_name,
                volumes=docker_volumes,
                work_dir=docker_work_dir,
            )
        else:
            self.backend = FilesystemBackend(root_dir=self.root_dir, virtual_mode=True)

        crash_controller = self.crash_controller  # local ref for closures
        backend_ref = self.backend  # local ref for closures

        @tool
        def list_files(directory: str = "/") -> str:
            """List files in a directory."""
            crash_controller.maybe_crash(f"list_files({directory})")
            result = backend_ref.ls(directory)
            if result.error:
                return f"Error: {result.error}"
            return "\n".join(sorted(entry["path"] for entry in result.entries))

        @tool
        def read_file(path: str) -> str:
            """Read a file's contents."""
            crash_controller.maybe_crash(f"read_file({path})")
            result = backend_ref.read(path)
            if result.error:
                return f"Error: {result.error}"
            return result.file_data["content"]

        @tool
        def count_words(text: str) -> int:
            """Count words in a string."""
            crash_controller.maybe_crash("count_words")
            return len(text.split())

        self.agent = create_deep_agent(
            model=self.model,
            backend=self.backend,
            tools=[list_files, read_file, count_words],
            checkpointer=self.checkpointer,
        )

    def close(self):
        """Tear down the backend if it needs explicit cleanup (e.g. Docker containers)."""
        close_fn = getattr(self.backend, "close", None)
        if callable(close_fn):
            close_fn()

    # ------------------------------------------------------------------ #
    # helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def new_thread_id() -> str:
        return uuid.uuid4().hex[:8]

    @staticmethod
    def _config(thread_id: str) -> dict:
        return {"configurable": {"thread_id": thread_id}}

    def arm_crash(self):
        """Arm the crash flag: the next tool call will raise an exception."""
        self.crash_controller.arm()

    # ------------------------------------------------------------------ #
    # running / resuming, as generators so a UI can render progress live
    # ------------------------------------------------------------------ #
    def stream_run(self, task: str, thread_id: str):
        """Start a brand-new task on `thread_id`, yielding events as they happen."""
        config = self._config(thread_id)
        try:
            for event in self.agent.stream(
                {"messages": [{"role": "user", "content": task}]},
                config,
                stream_mode="values",
            ):
                yield {"type": "step", "data": event}
        except Exception as e:  # noqa: BLE001 - intentionally broad, this is a demo
            yield {"type": "crash", "error": str(e)}

    def stream_resume(self, thread_id: str):
        """Resume `thread_id` from its last checkpoint (pass None as input)."""
        config = self._config(thread_id)
        try:
            for event in self.agent.stream(None, config, stream_mode="values"):
                yield {"type": "step", "data": event}
        except Exception as e:  # noqa: BLE001
            yield {"type": "crash", "error": str(e)}

    # ------------------------------------------------------------------ #
    # introspection
    # ------------------------------------------------------------------ #
    def get_state(self, thread_id: str):
        return self.agent.get_state(self._config(thread_id))

    def is_paused(self, thread_id: str) -> bool:
        """True if the graph stopped mid-task (i.e. there's a `next` step waiting)."""
        return bool(self.get_state(thread_id).next)

    def get_history(self, thread_id: str) -> list[dict]:
        """Readable checkpoint timeline for `thread_id`, oldest first."""
        snapshots = list(self.agent.get_state_history(self._config(thread_id)))
        history = []
        for snap in reversed(snapshots):
            msgs = snap.values.get("messages", [])
            last = msgs[-1] if msgs else None
            if last is None:
                summary = "(no messages yet)"
            elif getattr(last, "tool_calls", None):
                summary = f"AI requests tool call(s): {[tc['name'] for tc in last.tool_calls]}"
            elif getattr(last, "type", "") == "tool":
                summary = f"Tool '{last.name}' returned: {str(last.content)[:100]!r}"
            elif getattr(last, "type", "") == "ai":
                summary = f"AI: {str(last.content)[:2000]!r}"
            else:
                summary = f"{getattr(last, 'type', '?')}: {str(last.content)[:100]!r}"
            history.append(
                {
                    "step": snap.metadata["step"],
                    "next": str(snap.next),
                    "summary": summary,
                }
            )
        return history