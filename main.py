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
import mimetypes
import os
import shlex
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
from langchain_openai import ChatOpenAI
from deepagents import create_deep_agent

from agent_runner import DeepAgentRunner
from stream_events import EventMapper, file_kind
from json_saver import JsonFileSaver

app = FastAPI()

_cors_origins = [o.strip() for o in os.environ.get("CORS_ORIGINS", "http://localhost:5173").split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Shared across every thread: cheap to construct, and JsonFileSaver is
# designed to multiplex many threads over one store. Only the Docker
# backend is actually duplicated per thread (see RunnerPool below).
_shared_model = ChatOpenAI(model="gpt-5.4", api_key=os.environ.get("OPENAI_API_KEY"))
_shared_checkpointer = JsonFileSaver(state_path="state.json", memory_path="memory.json")

# Project directory to copy files from (defaults to where this file lives)
_project_root = os.path.realpath(os.path.dirname(__file__))


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
    return f"data: {json.dumps(event, default=str)}\n\n"


_SENTINEL = object()


async def sse_from_sync_generator(gen):
    """DeepAgentRunner's generators are sync; run them in a thread pool so
    they don't block the event loop, mapping each LangGraph v2 chunk into UI
    events (see stream_events.py) and yielding SSE-formatted chunks.

    NOTE: we pass `_SENTINEL` as next()'s default instead of letting
    StopIteration propagate out of the executor thread — PEP 479 forbids a
    StopIteration from crossing a Future boundary.
    """
    loop = asyncio.get_event_loop()
    mapper = EventMapper()
    it = iter(gen)
    while True:
        event = await loop.run_in_executor(None, next, it, _SENTINEL)
        if event is _SENTINEL:
            break
        if event["type"] == "chunk":
            for ui_event in mapper.map(event["data"]):
                yield sse_format(ui_event)
        elif event["type"] == "crash":
            yield sse_format({"type": "crash", "error": event["error"]})
        elif event["type"] == "stopped":
            yield sse_format({"type": "stopped"})
    yield sse_format({"type": "done"})


_SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


@app.post("/api/run")
async def run_task(req: RunRequest):
    thread_id = req.thread_id or DeepAgentRunner.new_thread_id()
    runner = pool.get_or_create(thread_id)
    gen = runner.stream_run(req.task, thread_id)

    async def stream():
        yield sse_format({"type": "thread", "thread_id": thread_id})
        async for chunk in sse_from_sync_generator(gen):
            yield chunk

    return StreamingResponse(stream(), media_type="text/event-stream", headers=_SSE_HEADERS)


@app.post("/api/resume")
async def resume_task(req: ThreadRequest):
    runner = pool.get_or_create(req.thread_id)
    gen = runner.stream_resume(req.thread_id)
    return StreamingResponse(sse_from_sync_generator(gen), media_type="text/event-stream", headers=_SSE_HEADERS)


@app.post("/api/arm_crash")
async def arm_crash(req: ThreadRequest):
    """Arms that thread's CrashController: the very next tool call on
    `req.thread_id` (in the currently running or next-started stream) will
    raise."""
    runner = pool.get_or_create(req.thread_id)
    runner.arm_crash()
    return {"armed": True, "thread_id": req.thread_id}


@app.post("/api/threads/{thread_id}/stop")
async def stop_thread(thread_id: str):
    """Cooperatively stop the running stream; the checkpoint is kept, so the
    thread can be resumed later with /api/resume."""
    runner = pool.get(thread_id)
    if runner is None:
        raise HTTPException(status_code=404, detail=f"No runner for thread_id '{thread_id}'")
    runner.request_stop()
    return {"stopping": True, "thread_id": thread_id}


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


# ---------------------------------------------------------------------- #
# Thread history (read straight from the checkpointer, no container needed)
# ---------------------------------------------------------------------- #
# A container-free graph used only to *read* thread state. Reading through a
# compiled graph (rather than the raw checkpoint) matters: newer LangGraph
# stores `messages` as a delta channel that only the graph can rebuild.
_history_reader = create_deep_agent(model=_shared_model, checkpointer=_shared_checkpointer)


def _read_thread(thread_id: str):
    """(messages, todos, updated_at, paused) for a thread, or None."""
    snap = _history_reader.get_state({"configurable": {"thread_id": thread_id}})
    messages = snap.values.get("messages", []) or []
    if not messages:
        return None
    return messages, snap.values.get("todos"), snap.created_at, bool(snap.next)


def _title(messages: list) -> str:
    for m in messages:
        if getattr(m, "type", "") == "human":
            text = m.content if isinstance(m.content, str) else str(m.content)
            text = " ".join(text.split())
            return text[:60] + ("…" if len(text) > 60 else "")
    return "Untitled task"


@app.get("/api/threads")
async def list_threads():
    """All threads known to the checkpointer (survives server restarts),
    newest first, flagged with whether a live container exists."""
    threads = []
    for thread_id in list(_shared_checkpointer.storage.keys()):
        found = await asyncio.to_thread(_read_thread, thread_id)
        if found is None:
            continue
        messages, _todos, ts, paused = found
        threads.append({
            "thread_id": thread_id,
            "title": _title(messages),
            "updated_at": ts,
            "paused": paused,
            "alive": pool.get(thread_id) is not None,
        })
    threads.sort(key=lambda t: t["updated_at"] or "", reverse=True)
    return {"threads": threads}


@app.get("/api/threads/{thread_id}")
async def get_thread(thread_id: str):
    """Rebuild a thread as the same UI events the live stream emits."""
    found = await asyncio.to_thread(_read_thread, thread_id)
    if found is None:
        raise HTTPException(status_code=404, detail=f"Unknown thread_id '{thread_id}'")
    messages, todos, ts, paused = found
    events = EventMapper().replay(messages, todos)
    return {
        "thread_id": thread_id,
        "title": _title(messages),
        "updated_at": ts,
        "paused": paused,
        "events": events,
    }


# ---------------------------------------------------------------------- #
# Files produced by the agent
# ---------------------------------------------------------------------- #
# The agent's built-in file tools write inside the thread's Docker sandbox,
# while `download_image` / `move_file` (tool_manager.py) write on the host.
_CONTENT_DIRS = ("blogs", "research", "output", "linkedin", "tweets")


def _clean_rel_path(path: str) -> str:
    rel = path.strip().lstrip("/")
    if rel.startswith("workspace/"):
        rel = rel[len("workspace/"):]
    parts = [p for p in rel.split("/") if p not in ("", ".")]
    if not parts or ".." in parts:
        raise HTTPException(status_code=400, detail="Invalid path")
    return "/".join(parts)


def _host_file(rel: str) -> Optional[str]:
    if rel.split("/")[0] not in _CONTENT_DIRS:
        return None
    full = os.path.realpath(os.path.join(_project_root, rel))
    if not full.startswith(_project_root + os.sep) or not os.path.isfile(full):
        return None
    return full


@app.get("/api/threads/{thread_id}/files")
async def list_files(thread_id: str):
    """Content files in the thread's sandbox (blogs/, research/, output/ …)."""
    runner = pool.get(thread_id)
    files: list[dict] = []
    if runner is not None and hasattr(runner.backend, "execute"):
        dirs = " ".join(shlex.quote(d) for d in _CONTENT_DIRS)
        cmd = f"cd /workspace && for d in {dirs}; do [ -d \"$d\" ] && find \"$d\" -type f; done; true"
        result = await asyncio.to_thread(runner.backend.execute, cmd)
        for line in (getattr(result, "output", "") or "").splitlines():
            line = line.strip()
            if line:
                files.append({"path": line, "kind": file_kind(line), "source": "sandbox"})
    return {"files": files}


@app.get("/api/threads/{thread_id}/files/raw")
async def read_file_raw(thread_id: str, path: str):
    """Serve one file: the thread's sandbox first, then the host content dirs."""
    rel = _clean_rel_path(path)
    content: Optional[bytes] = None
    runner = pool.get(thread_id)
    if runner is not None and hasattr(runner.backend, "download_files"):
        resp = (await asyncio.to_thread(runner.backend.download_files, [rel]))[0]
        if not getattr(resp, "error", None) and resp.content is not None:
            content = resp.content
    if content is None:
        host = _host_file(rel)
        if host is None:
            raise HTTPException(status_code=404, detail=f"File not found: {rel}")
        with open(host, "rb") as f:
            content = f.read()
    media_type = mimetypes.guess_type(rel)[0] or "application/octet-stream"
    if rel.endswith((".md", ".markdown")):
        media_type = "text/markdown; charset=utf-8"
    return Response(content=content, media_type=media_type)


@app.post("/api/close_all")
async def close_all_threads():
    """Close all active Docker containers."""
    count = len(pool._runners)
    pool.close_all()
    return {"closed": count, "message": f"Closed {count} containers"}
