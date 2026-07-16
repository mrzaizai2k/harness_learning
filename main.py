"""
Demo: two threads, same step 1, DIFFERENT steps 2/3, both crash - then we
resume each one independently just by changing `config`.

The point: `config = {"configurable": {"thread_id": ...}}` is the ONLY
thing that tells the checkpointer which conversation/state to load. Same
agent object, same checkpointer object - swap the thread_id and you get a
completely different, independent graph state.

Task for both threads, step 1 is identical:
    1. List the files in the current directory.
Then they diverge:
    thread-1 -> 2. read README.md   -> 3. count words in it
    thread-2 -> 2. read main.py     -> 3. summarize what it does in 1 sentence

Both crash on step 2 (flaky_read crashes on the FIRST read of any given
path, so thread-1's README.md read and thread-2's main.py read each crash
independently, on their own first attempt).
"""

import os
from langgraph.checkpoint.memory import InMemorySaver
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend
from dotenv import load_dotenv

load_dotenv()

# --------------------------------------------------------------------------
# flaky_read fails on the FIRST read of a given path, then works after.
# Keyed by path (not a single global counter) so thread-1 reading
# README.md and thread-2 reading main.py each get their own "first crash",
# independently of each other and of call order.
# --------------------------------------------------------------------------
_attempts_per_path: dict[str, int] = {}


@tool
def list_files(directory: str = ".") -> str:
    """List files in a directory."""
    return "\n".join(sorted(os.listdir(directory)))


@tool
def flaky_read(path: str) -> str:
    """Read a file's contents. (demo: fails on the first read of each path)"""
    _attempts_per_path[path] = _attempts_per_path.get(path, 0) + 1
    if _attempts_per_path[path] == 1:
        raise RuntimeError(f"Simulated crash: process died reading {path}")
    with open(path) as f:
        return f.read()


@tool
def count_words(text: str) -> int:
    """Count words in a string."""
    return len(text.split())


# --------------------------------------------------------------------------
# ONE agent, ONE checkpointer. Thread isolation comes entirely from the
# thread_id you put in `config` - not from having separate agents.
# --------------------------------------------------------------------------
checkpointer = InMemorySaver()
model = ChatOpenAI(model="gpt-4.1-mini", api_key=os.environ.get("OPENAI_API_KEY"))

agent = create_deep_agent(
    model=model,
    backend=FilesystemBackend(root_dir=".", virtual_mode=True),
    tools=[list_files, flaky_read, count_words],
    checkpointer=checkpointer,
)


def describe_checkpoints(config, label=""):
    snapshots = list(agent.get_state_history(config))
    print(f"  --- {label} (thread_id={config['configurable']['thread_id']}) ---")
    for snap in reversed(snapshots):  # oldest -> newest
        msgs = snap.values.get("messages", [])
        last = msgs[-1] if msgs else None
        if last is None:
            summary = "(no messages yet)"
        elif getattr(last, "tool_calls", None):
            summary = f"AI requests tool call(s): {[tc['name'] for tc in last.tool_calls]}"
        elif last.type == "tool":
            summary = f"Tool '{last.name}' returned: {str(last.content)[:60]!r}"
        elif last.type == "ai":
            summary = f"AI: {str(last.content)[:60]!r}"
        else:
            summary = f"{last.type}: {str(last.content)[:60]!r}"
        print(f"    step={snap.metadata['step']:>2}  next={snap.next!s:<12}  {summary}")


config_1 = {"configurable": {"thread_id": "thread-1"}}
config_2 = {"configurable": {"thread_id": "thread-2"}}

task_1 = (
    "1. List the files in the current directory. "
    "2. Then read README.md with flaky_read. "
    "3. Then count the words in it."
)
task_2 = (
    "1. List the files in the current directory. "
    "2. Then read main.py with flaky_read. "
    "3. Then summarize in one sentence what the script does."
)

# ==========================================================================
# Kick off BOTH threads. Each does step 1 fine, then crashes on step 2 -
# independently, since flaky_read tracks failures per-path.
# ==========================================================================
print("=== thread-1: first attempt (will crash on README.md) ===")
try:
    agent.invoke({"messages": [{"role": "user", "content": task_1}]}, config_1)
except RuntimeError as e:
    print(f"CRASHED: {e}")

print("\n=== thread-2: first attempt (will crash on main.py) ===")
try:
    agent.invoke({"messages": [{"role": "user", "content": task_2}]}, config_2)
except RuntimeError as e:
    print(f"CRASHED: {e}")

print("\n=== Checkpoints saved before resume (both threads paused mid-task) ===")
describe_checkpoints(config_1, "thread-1")
describe_checkpoints(config_2, "thread-2")

# ==========================================================================
# Resume thread-1 ONLY. Pass config_1 -> only thread-1's graph state loads
# and continues. thread-2 is untouched, still paused where it crashed.
# ==========================================================================
print("\n=== Resuming with config_1 -> only thread-1 continues ===")
result_1 = agent.invoke(None, config_1)
print("thread-1 final answer:", result_1["messages"][-1].content)

# Prove thread-2 hasn't moved: still paused at the same `next`.
still_paused = agent.get_state(config_2)
print(f"thread-2 is still paused, next={still_paused.next} (unaffected by resuming thread-1)")

# ==========================================================================
# Now resume thread-2 ONLY, by swapping config to config_2.
# Same agent, same .invoke(None, ...) call shape - the thread_id inside
# config is the only thing that changed, and it's what picks the graph.
# ==========================================================================
print("\n=== Resuming with config_2 -> only thread-2 continues ===")
result_2 = agent.invoke(None, config_2)
print("thread-2 final answer:", result_2["messages"][-1].content)

print("\n=== Full checkpoint timelines after both resumes ===")
describe_checkpoints(config_1, "thread-1")
describe_checkpoints(config_2, "thread-2")