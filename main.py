"""
FastAPI SSE wrapper around DeepAgentRunner.

Endpoints
---------
POST /api/run          {task, thread_id?}  -> starts a new task, streams SSE
POST /api/resume       {thread_id}         -> resumes a crashed task, streams SSE
POST /api/arm_crash    {thread_id}         -> arms that thread's crash flag (fires on next tool call)
GET  /api/state/{tid}                      -> {"paused": bool}
POST /api/close/{tid}                      -> stops and removes that thread's Docker container

Per-thread isolation
---------------------
Each conversation `thread_id` gets its OWN `DeepAgentRunner`, and therefore
its OWN Docker container (named `deepagents_sandbox_<thread_id>`). Threads no
longer share a filesystem inside the same container. The `model` (ChatOpenAI
client) and `checkpointer` (JsonFileSaver) ARE shared across all threads --
those are cheap/safe to share and the checkpointer already multiplexes
threads via `thread_id` in its `config`, same as the original single-runner
design; only the sandbox needed to be split out.

File Copying
------------
When a new Docker container is created for a thread, all files from the
project directory (respecting .dockerignore) are automatically copied into
the container's /workspace directory. This ensures each container has access
to your project files (agents.md, skills/, etc.).

Run with:
    uvicorn main:app --reload --port 8000
"""

import json
import asyncio
import os
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from langchain_openai import ChatOpenAI

from agent_runner import DeepAgentRunner
from json_saver import JsonFileSaver

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Shared across every thread: cheap to construct, and JsonFileSaver is
# designed to multiplex many threads over one store. Only the Docker
# backend is actually duplicated per thread (see RunnerPool below).
_shared_model = ChatOpenAI(model="gpt-5.4", api_key=os.environ.get("OPENAI_API_KEY"))
_shared_checkpointer = JsonFileSaver(state_path="state.json", memory_path="memory.json")

# Project directory to copy files from (defaults to where this file lives)
_project_root = os.path.abspath(os.path.dirname(__file__))


class RunnerPool:
    """Lazily creates one `DeepAgentRunner` (and one Docker container) per
    `thread_id`, so concurrent conversations never write into each other's
    container filesystem.
    
    Each new container automatically receives a copy of the project files
    (respecting .dockerignore) so agents have access to agents.md, skills/, etc.
    """

    def __init__(self, project_root: str):
        self._runners: dict[str, DeepAgentRunner] = {}
        self._project_root = project_root

    def get_or_create(self, thread_id: str) -> DeepAgentRunner:
        if thread_id not in self._runners:
            print(f"Creating new Docker sandbox for thread: {thread_id}")
            self._runners[thread_id] = DeepAgentRunner(
                model=_shared_model,
                checkpointer=_shared_checkpointer,
                root_dir=self._project_root,
                use_docker=True,
                docker_runtime="python-minimal",
                docker_container_name=f"deepagents_sandbox_{thread_id}",
                docker_work_dir="/workspace",
            )
            print(f"✓ Docker sandbox ready for thread: {thread_id}")
        return self._runners[thread_id]

    def get(self, thread_id: str) -> Optional[DeepAgentRunner]:
        return self._runners.get(thread_id)

    def close(self, thread_id: str) -> bool:
        runner = self._runners.pop(thread_id, None)
        if runner is None:
            return False
        print(f"Closing Docker sandbox for thread: {thread_id}")
        runner.close()
        return True

    def close_all(self) -> None:
        """Close all running containers (useful for cleanup on shutdown)."""
        for thread_id in list(self._runners.keys()):
            self.close(thread_id)


pool = RunnerPool(project_root=_project_root)


# Cleanup on shutdown
@app.on_event("shutdown")
async def shutdown_event():
    print("Shutting down: closing all Docker containers...")
    pool.close_all()


class RunRequest(BaseModel):
    task: str
    thread_id: Optional[str] = None


class ThreadRequest(BaseModel):
    thread_id: str


def sse_format(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


def extract_event(event: dict) -> dict:
    """Reduce a raw stream_run/stream_resume event down to something small
    and JSON-serializable for the UI (LangChain message objects aren't)."""
    if event["type"] == "crash":
        return {"type": "crash", "error": event["error"]}

    messages = event["data"].get("messages", [])
    if not messages:
        return {"type": "step", "role": None, "content": ""}

    last = messages[-1]
    role = getattr(last, "type", "unknown")  # "human" | "ai" | "tool"
    content = last.content if isinstance(last.content, str) else str(last.content)
    tool_calls = [tc["name"] for tc in (getattr(last, "tool_calls", None) or [])]

    return {
        "type": "step",
        "role": role,
        "content": content,
        "tool_calls": tool_calls,
    }


_SENTINEL = object()


async def sse_from_sync_generator(gen):
    """DeepAgentRunner's generators are sync; run them in a thread pool so
    they don't block the event loop, yielding SSE-formatted chunks.

    NOTE: we pass `_SENTINEL` as next()'s default instead of letting
    StopIteration propagate out of the executor thread — PEP 479 forbids a
    StopIteration from crossing a Future boundary (it would otherwise show
    up as "RuntimeError: StopIteration interacts badly with generators").
    """
    loop = asyncio.get_event_loop()
    it = iter(gen)
    while True:
        event = await loop.run_in_executor(None, next, it, _SENTINEL)
        if event is _SENTINEL:
            break
        yield sse_format(extract_event(event))
    yield sse_format({"type": "done"})


@app.post("/api/run")
async def run_task(req: RunRequest):
    thread_id = req.thread_id or DeepAgentRunner.new_thread_id()
    runner = pool.get_or_create(thread_id)
    gen = runner.stream_run(req.task, thread_id)

    async def stream():
        yield sse_format({"type": "thread", "thread_id": thread_id})
        async for chunk in sse_from_sync_generator(gen):
            yield chunk

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.post("/api/resume")
async def resume_task(req: ThreadRequest):
    runner = pool.get_or_create(req.thread_id)
    gen = runner.stream_resume(req.thread_id)
    return StreamingResponse(sse_from_sync_generator(gen), media_type="text/event-stream")


@app.post("/api/arm_crash")
async def arm_crash(req: ThreadRequest):
    """Arms that thread's CrashController: the very next tool call on
    `req.thread_id` (in the currently running or next-started stream) will
    raise."""
    runner = pool.get_or_create(req.thread_id)
    runner.arm_crash()
    return {"armed": True, "thread_id": req.thread_id}


@app.get("/api/state/{thread_id}")
async def get_state(thread_id: str):
    runner = pool.get(thread_id)
    if runner is None:
        raise HTTPException(status_code=404, detail=f"No runner for thread_id '{thread_id}'")
    return {"paused": runner.is_paused(thread_id)}


@app.post("/api/close/{thread_id}")
async def close_thread(thread_id: str):
    """Stop and remove that thread's Docker container once you're done with it."""
    closed = pool.close(thread_id)
    if not closed:
        raise HTTPException(status_code=404, detail=f"No runner for thread_id '{thread_id}'")
    return {"closed": True, "thread_id": thread_id}


@app.get("/api/threads")
async def list_threads():
    """List all active thread IDs with their container status."""
    threads = []
    for thread_id, runner in pool._runners.items():
        threads.append({
            "thread_id": thread_id,
            "alive": runner.is_alive(),
            "paused": runner.is_paused(thread_id),
        })
    return {"threads": threads}


@app.post("/api/close_all")
async def close_all_threads():
    """Close all active Docker containers."""
    count = len(pool._runners)
    pool.close_all()
    return {"closed": count, "message": f"Closed {count} containers"}