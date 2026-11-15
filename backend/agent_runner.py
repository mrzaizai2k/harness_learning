"""
DeepAgentRunner: builds one deep agent (tools, subagents, skills, AGENTS.md
memory) on top of a sandbox backend and a shared checkpointer, and streams
its LangGraph v2 output per `thread_id`. The `thread_id` in the config is
what lets the checkpointer resume a conversation after a crash or stop.
"""

import os
import uuid
from typing import cast
import yaml
from pathlib import Path

from backend import config
from backend.json_saver import JsonFileSaver
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from deepagents.backends import FilesystemBackend
from deepagents.backends.protocol import BackendProtocol, SandboxBackendProtocol
from langchain_core.runnables import RunnableConfig
from pydantic_ai_backends import RuntimeConfig
from backend.docker_sandbox import PydanticDockerSandboxBackend
from langchain.agents.middleware import TodoListMiddleware
from deepagents import create_deep_agent
from backend.subagent_registry import SubAgentRegistry

from langfuse import get_client
from langfuse.langchain import CallbackHandler

from backend.prompts import WRITE_TODOS_TOOL, WRITE_TODOS_SYSTEM_PROMPT
from backend.tool_manager import (
    web_search,
    generate_hashtags,
    download_image,
    move_file,
)


def load_subagents(config_path: Path) -> list:
    """Load subagent definitions from YAML and wire up tools.
    
    NOTE: This is a custom utility for this example. Unlike `memory` and `skills`,
    deepagents doesn't natively load subagents from files - they're normally
    defined inline in the create_deep_agent() call. We externalize to YAML here
    to keep configuration separate from code.
    """
    available_tools = {
        "web_search": web_search,
    }
    
    if not config_path.exists():
        print(f"Warning: Subagents config not found at {config_path}")
        return []
    
    try:
        with open(config_path) as f:
            specs = yaml.safe_load(f)
        
        if not specs:
            print("Warning: Empty subagents configuration")
            return []
        
        subagents = []
        for name, spec in specs.items():
            if not isinstance(spec, dict):
                print(f"Warning: Invalid spec for subagent '{name}', skipping")
                continue
            
            subagent = {
                "name": name,
                "description": spec.get("description", ""),
                "system_prompt": spec.get("system_prompt", ""),
            }
            
            if "model" in spec:
                subagent["model"] = spec["model"]
            
            if "tools" in spec:
                tools = []
                for tool_name in spec["tools"]:
                    if tool_name in available_tools:
                        tools.append(available_tools[tool_name])
                    else:
                        print(f"Warning: Unknown tool '{tool_name}' for subagent '{name}'")
                subagent["tools"] = tools
            
            subagents.append(subagent)
        
        return subagents
    except Exception as e:
        print(f"Error loading subagents: {e}")
        return []


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
            self.armed = False
            raise RuntimeError(f"Simulated crash during: {context}")


class DeepAgentRunner:
    """
    Wraps one agent + one checkpointer. Call `new_thread_id()` to start an
    independent task, `stream_run(task, thread_id)` to start it, and
    `stream_resume(thread_id)` to continue after a crash.
    """

    def __init__(
        self,
        model_name: str = config.MODEL_NAME,
        root_dir: str | None = None,
        backend: SandboxBackendProtocol | None = None,
        use_docker: bool = False,
        docker_runtime: str | RuntimeConfig | None = config.SANDBOX_RUNTIME,
        docker_container_name: str | None = None,
        docker_volumes: dict[str, str] | None = None,
        docker_work_dir: str = config.SANDBOX_WORKDIR,
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
        self.root_dir = os.path.abspath(root_dir or config.PROJECT_ROOT)

        self.crash_controller = CrashController()
        self._stop_requested = False
        self.checkpointer = checkpointer or JsonFileSaver(state_path=config.STATE_PATH, memory_path=config.MEMORY_PATH)
        self.model = model or ChatOpenAI(model=model_name)  # reads OPENAI_API_KEY from env

        if backend is not None and use_docker:
            raise ValueError("Pass either `backend` or `use_docker=True`, not both.")

        self.backend: BackendProtocol
        if backend is not None:
            self.backend = backend
        elif use_docker:
            self.backend = PydanticDockerSandboxBackend.create(
                runtime=docker_runtime,
                container_name=docker_container_name,
                volumes=docker_volumes,
                work_dir=docker_work_dir,
                auto_copy_files=True,
                source_dir=self.root_dir,
            )
        else:
            self.backend = FilesystemBackend(root_dir=self.root_dir, virtual_mode=True)

        crash_controller = self.crash_controller
        backend_ref = cast(BackendProtocol, self.backend)
        self.langfuse = get_client()
        self.langfuse_handler = CallbackHandler()

        @tool
        def list_files(directory: str = "/") -> str:
            """List files in a directory."""
            crash_controller.maybe_crash(f"list_files({directory})")
            result = backend_ref.ls(directory)
            if result.error:
                return f"Error: {result.error}"
            return "\n".join(sorted(entry["path"] for entry in result.entries or []))

        @tool
        def read_file(path: str) -> str:
            """Read a file's contents."""
            crash_controller.maybe_crash(f"read_file({path})")
            result = backend_ref.read(path)
            if result.error or result.file_data is None:
                return f"Error: {result.error or 'file not found'}"
            return result.file_data["content"]

        @tool
        def count_words(text: str) -> int:
            """Count words in a string."""
            crash_controller.maybe_crash("count_words")
            return len(text.split())

        tools = [
            list_files,
            read_file,
            count_words,
            generate_hashtags,
            download_image,
            web_search,
            move_file,
        ]

        registry = SubAgentRegistry(agent_list_path=config.AGENT_LIST_PATH)

        self.agent = create_deep_agent(
            model=self.model,
            backend=self.backend,
            tools=tools,
            subagents=load_subagents(config.SUBAGENTS_YAML) + registry.get_subagents(),
            checkpointer=self.checkpointer,
            middleware=[TodoListMiddleware(system_prompt=WRITE_TODOS_SYSTEM_PROMPT, tool_description=WRITE_TODOS_TOOL)],
            memory=["./AGENTS.md"],
            skills=["./skills/"],
        )

    def close(self):
        """Tear down the backend if it needs explicit cleanup (e.g. Docker containers)."""
        close_fn = getattr(self.backend, "close", None)
        if callable(close_fn):
            close_fn()

    @staticmethod
    def new_thread_id() -> str:
        return uuid.uuid4().hex[:8]

    def _config(self, thread_id: str) -> RunnableConfig:
        return {
            "configurable": {"thread_id": thread_id},
            "run_name": f"thread-{thread_id}",
            "tags": [f"thread:{thread_id}"],
            "callbacks": [self.langfuse_handler],
            "metadata": {
                "langfuse_session_id": thread_id,  # groups all runs of a thread into one Langfuse session
            },
        }

    def arm_crash(self):
        """Arm the crash flag: the next tool call will raise an exception."""
        self.crash_controller.arm()

    # LangGraph v2 streaming: token chunks ("messages") + per-node deltas
    # ("updates"), including subagent namespaces (subgraphs=True). See
    # stream_events.EventMapper for how chunks become UI events.
    def request_stop(self):
        """Ask the current stream to stop at the next chunk boundary."""
        self._stop_requested = True

    def _stream(self, agent_input, thread_id: str):
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
        """Start a brand-new task on `thread_id`, yielding events as they happen."""
        yield from self._stream({"messages": [{"role": "user", "content": task}]}, thread_id)

    def stream_resume(self, thread_id: str):
        """Resume `thread_id` from its last checkpoint (pass None as input)."""
        yield from self._stream(None, thread_id)

    def get_state(self, thread_id: str):
        return self.agent.get_state(self._config(thread_id))

    def is_paused(self, thread_id: str) -> bool:
        """True if the graph stopped mid-task (i.e. there's a `next` step waiting)."""
        return bool(self.get_state(thread_id).next)
