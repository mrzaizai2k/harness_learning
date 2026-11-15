"""
FastAPI backend for Content Studio: runs the agent and streams it as SSE.

Each conversation thread gets its own DeepAgentRunner and Docker sandbox
(see agent_runner.RunnerPool). Thread history and files live in
routes_threads.py.

Run with:
    make be        # uvicorn backend.main:app --reload --port 8000
"""

import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from starlette.concurrency import iterate_in_threadpool

from backend import config, routes_threads
from backend.agent_runner import DeepAgentRunner
from backend.deps import pool
from backend.stream_events import EventMapper


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    pool.close_all()  # remove every thread's sandbox container on shutdown


app = FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_methods=["*"], allow_headers=["*"])
app.include_router(routes_threads.router)


class RunRequest(BaseModel):
    task: str
    thread_id: str | None = None


class ThreadRequest(BaseModel):
    thread_id: str


def sse(event: dict) -> str:
    return f"data: {json.dumps(event, default=str)}\n\n"


async def sse_stream(runner_events, thread_id: str | None = None):
    """Runner events -> UI events (stream_events.py) -> SSE lines.

    The runner is a sync generator, so it runs in a thread pool to keep the
    event loop free."""
    if thread_id:
        yield sse({"type": "thread", "thread_id": thread_id})
    mapper = EventMapper()
    async for event in iterate_in_threadpool(runner_events):
        if event["type"] == "chunk":
            for ui_event in mapper.map(event["data"]):
                yield sse(ui_event)
        else:  # "crash" or "stopped"
            yield sse(event)
    yield sse({"type": "done"})


def sse_response(gen) -> StreamingResponse:
    return StreamingResponse(gen, media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def existing_runner(thread_id: str) -> DeepAgentRunner:
    runner = pool.get(thread_id)
    if runner is None:
        raise HTTPException(status_code=404, detail=f"No runner for thread_id '{thread_id}'")
    return runner


@app.post("/api/run")
async def run_task(req: RunRequest):
    thread_id = req.thread_id or DeepAgentRunner.new_thread_id()
    runner = pool.get_or_create(thread_id)
    return sse_response(sse_stream(runner.stream_run(req.task, thread_id), thread_id))


@app.post("/api/resume")
async def resume_task(req: ThreadRequest):
    runner = pool.get_or_create(req.thread_id)
    return sse_response(sse_stream(runner.stream_resume(req.thread_id)))


@app.post("/api/threads/{thread_id}/stop")
async def stop_thread(thread_id: str):
    """Stop the running stream; the checkpoint is kept, so it can be resumed."""
    existing_runner(thread_id).request_stop()
    return {"stopping": True, "thread_id": thread_id}


@app.post("/api/arm_crash")
async def arm_crash(req: ThreadRequest):
    """Debug: the next tool call on this thread raises (see crash.py)."""
    pool.get_or_create(req.thread_id).arm_crash()
    return {"armed": True, "thread_id": req.thread_id}


@app.post("/api/close/{thread_id}")
async def close_thread(thread_id: str):
    """Remove the thread's sandbox container. Its history stays in the checkpointer."""
    if not pool.close(thread_id):
        raise HTTPException(status_code=404, detail=f"No runner for thread_id '{thread_id}'")
    return {"closed": True, "thread_id": thread_id}
