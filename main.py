"""
FastAPI SSE wrapper around DeepAgentRunner.

Endpoints
---------
POST /api/run          {task, thread_id?}  -> starts a new task, streams SSE
POST /api/resume       {thread_id}         -> resumes a crashed task, streams SSE
POST /api/arm_crash    {}                  -> arms the crash flag (fires on next tool call)
GET  /api/state/{tid}                      -> {"paused": bool}

Run with:
    uvicorn main:app --reload --port 8000
"""

import json
import asyncio
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agent_runner import DeepAgentRunner  # <- your uploaded module, save it as deep_agent_runner.py

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Single shared runner/crash_controller instance, same as the original script.
runner = DeepAgentRunner()


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
    gen = runner.stream_run(req.task, thread_id)

    async def stream():
        yield sse_format({"type": "thread", "thread_id": thread_id})
        async for chunk in sse_from_sync_generator(gen):
            yield chunk

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.post("/api/resume")
async def resume_task(req: ThreadRequest):
    gen = runner.stream_resume(req.thread_id)
    return StreamingResponse(sse_from_sync_generator(gen), media_type="text/event-stream")


@app.post("/api/arm_crash")
async def arm_crash():
    """Arms the shared CrashController: the very next tool call (in the
    currently running or next-started stream) will raise."""
    runner.arm_crash()
    return {"armed": True}


@app.get("/api/state/{thread_id}")
async def get_state(thread_id: str):
    return {"paused": runner.is_paused(thread_id)}