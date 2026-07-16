"""
Same idea as your original demo, but the checkpointer is now JsonFileSaver
instead of InMemorySaver, so state actually survives the process dying.

Workflow you want:
  1. `python demo_resumable.py`      -> starts thread-1 and thread-2, both
                                         crash on step 2, process exits.
                                         state.json / memory.json are on disk.
  2. (pretend the machine rebooted / you just killed python)
  3. `python demo_resumable.py`      -> same command, no special flags.
                                         It notices both threads have
                                         unfinished work saved in state.json
                                         and resumes each one from where it
                                         crashed, instead of starting over.

The only moving part that changed vs your original file: swap
`InMemorySaver()` for `JsonFileSaver()`. Everything else about how you call
`agent.invoke(...)` / `agent.invoke(None, config)` is identical - the
thread_id in `config` is still the only thing that picks which state loads.
"""

import os
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend
from dotenv import load_dotenv

from json_saver import JsonFileSaver  # the file from this same folder

load_dotenv()

# Marker-file based instead of a RAM dict: a RAM dict resets every time you
# start a new `python` process, so it would say "first attempt" forever and
# crash on every single restart. A file on disk survives the process dying,
# same as state.json/memory.json do - so it only "crashes" once, ever,
# per path, which is what you actually want to simulate a one-off flaky failure.
_CRASH_MARKERS_DIR = ".flaky_read_markers"


@tool
def list_files(directory: str = ".") -> str:
    """List files in a directory."""
    return "\n".join(sorted(os.listdir(directory)))


@tool
def flaky_read(path: str) -> str:
    """Read a file's contents. (demo: fails on the first-ever read of each path)"""
    os.makedirs(_CRASH_MARKERS_DIR, exist_ok=True)
    marker = os.path.join(_CRASH_MARKERS_DIR, path.replace("/", "_").replace("\\", "_"))
    if not os.path.exists(marker):
        with open(marker, "w") as f:
            f.write("crashed once")
        raise RuntimeError(f"Simulated crash: process died reading {path}")
    # FilesystemBackend(virtual_mode=True) gives the agent a virtual root at
    # "/", so it calls us with e.g. "/README.md" - strip the leading slash
    # so we open the real file relative to cwd instead of the OS root.
    real_path = path.lstrip("/")
    with open(real_path) as f:
        return f.read()


@tool
def count_words(text: str) -> int:
    """Count words in a string."""
    return len(text.split())


# JsonFileSaver() loads state.json / memory.json right here in __init__ if
# they exist from a previous run - nothing else to do to "resume".
checkpointer = JsonFileSaver(state_path="state.json", memory_path="memory.json")
model = ChatOpenAI(model="gpt-4.1-mini", api_key=os.environ.get("OPENAI_API_KEY"))

agent = create_deep_agent(
    model=model,
    backend=FilesystemBackend(root_dir=".", virtual_mode=True),
    tools=[list_files, flaky_read, count_words],
    checkpointer=checkpointer,
)

TASKS = {
    "thread-1": (
        "1. List the files in the current directory. "
        "2. Then read README.md with flaky_read. "
        "3. Then count the words in it."
    ),
    "thread-2": (
        "1. List the files in the current directory. "
        "2. Then read main.py with flaky_read. "
        "3. Then summarize in one sentence what the script does."
    ),
}


def run_or_resume(thread_id: str, task: str):
    config = {"configurable": {"thread_id": thread_id}}
    state = agent.get_state(config)

    if state.values and state.next:
        # We have a saved checkpoint AND it's paused mid-graph -> resume it.
        print(f"[{thread_id}] found unfinished work in state.json, resuming (next={state.next})")
        try:
            result = agent.invoke(None, config)
        except RuntimeError as e:
            print(f"[{thread_id}] CRASHED AGAIN: {e}")
            return
    elif state.values and not state.next:
        # Already finished in a previous run - nothing to do.
        print(f"[{thread_id}] already completed in a previous run, skipping")
        return
    else:
        # No checkpoint at all -> first time we've seen this thread_id.
        print(f"[{thread_id}] starting fresh")
        try:
            result = agent.invoke({"messages": [{"role": "user", "content": task}]}, config)
        except RuntimeError as e:
            print(f"[{thread_id}] CRASHED: {e}")
            return

    print(f"[{thread_id}] final answer:", result["messages"][-1].content)


if __name__ == "__main__":
    for tid, task in TASKS.items():
        run_or_resume(tid, task)