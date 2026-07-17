"""
DeepAgentRunner
===============
A thin, UI-friendly wrapper around the deepagents / langgraph checkpointing
demo. Same core idea as the original script:

    config = {"configurable": {"thread_id": ...}}

is the ONLY thing that tells the checkpointer which conversation/state to
load. One agent object, one checkpointer -> many independent threads.

Differences from the original script (made for the Streamlit UI):
  * The old `flaky_read` auto-crashed on the FIRST read of any path.
    Here the crash is controlled manually via `CrashController`, so the
    UI can arm/disarm it with a button instead of it being automatic.
  * Everything that used to be printed to stdout is now yielded as
    events (`stream_run` / `stream_resume`) so a UI can render it live.
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

    def __init__(self, model_name: str = "gpt-4.1-mini", root_dir: str | None = None):
        # Default to the folder this file lives in, NOT the process's cwd —
        # otherwise behavior silently depends on where `streamlit run` was
        # launched from.
        self.root_dir = os.path.abspath(root_dir or os.path.dirname(__file__))

        self.crash_controller = CrashController()
        self.checkpointer = JsonFileSaver(state_path="state.json", memory_path="memory.json")
        self.model = ChatOpenAI(model=model_name, api_key=os.environ.get("OPENAI_API_KEY"))

        crash_controller = self.crash_controller  # local ref for closures
        resolve = self._resolve_path  # local ref for closures

        @tool
        def list_files(directory: str = "/") -> str:
            """List files in a directory."""
            crash_controller.maybe_crash(f"list_files({directory})")
            return "\n".join(sorted(os.listdir(resolve(directory))))

        @tool
        def read_file(path: str) -> str:
            """Read a file's contents."""
            crash_controller.maybe_crash(f"read_file({path})")
            with open(resolve(path)) as f:
                return f.read()

        @tool
        def count_words(text: str) -> int:
            """Count words in a string."""
            crash_controller.maybe_crash("count_words")
            return len(text.split())

        self.agent = create_deep_agent(
            model=self.model,
            backend=FilesystemBackend(root_dir=self.root_dir, virtual_mode=True),
            tools=[list_files, read_file, count_words],
            checkpointer=self.checkpointer,
        )

    def _resolve_path(self, path: str) -> str:
        """
        The FilesystemBackend presents files under a *virtual* root of "/"
        (that's why `ls` prints things like '/AGENTS.md'). Our own tools
        talk to the real OS filesystem, so we strip that virtual leading
        slash and resolve against `root_dir` instead of the OS's real root
        — otherwise `read_file("/main.py")` looks for main.py on your
        actual disk root instead of inside the project folder.
        """
        relative = path.lstrip("/")
        return os.path.join(self.root_dir, relative) if relative else self.root_dir

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