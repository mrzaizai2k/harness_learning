"""
Read-only routes: past threads and the files the agent produced.

History is read from the checkpointer, so it survives restarts and needs no
container. Files are served from the thread's sandbox first, then from the
host content folders (download_image / move_file write on the host).
"""

import asyncio
import mimetypes
import shlex

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from backend import config
from backend.deps import checkpointer, history_reader, pool
from backend.stream_events import EventMapper, file_kind

router = APIRouter(prefix="/api/threads")


# ---------------------------------------------------------------- history

def _read_thread(thread_id: str):
    """(messages, todos, updated_at, paused) for a thread, or None."""
    snap = history_reader.get_state({"configurable": {"thread_id": thread_id}})
    messages = snap.values.get("messages") or []
    if not messages:
        return None
    return messages, snap.values.get("todos"), snap.created_at, bool(snap.next)


def _title(messages: list) -> str:
    for m in messages:
        if m.type == "human":
            text = " ".join(str(m.content).split())
            return text[:60] + ("…" if len(text) > 60 else "")
    return "Untitled task"


@router.get("")
async def list_threads():
    """Every thread in the checkpointer, newest first."""
    threads = []
    for thread_id in list(checkpointer.storage):
        found = await asyncio.to_thread(_read_thread, thread_id)
        if found is None:
            continue
        messages, _todos, updated_at, paused = found
        threads.append({
            "thread_id": thread_id,
            "title": _title(messages),
            "updated_at": updated_at,
            "paused": paused,
            "alive": pool.get(thread_id) is not None,
        })
    threads.sort(key=lambda t: t["updated_at"] or "", reverse=True)
    return {"threads": threads}


@router.get("/{thread_id}")
async def get_thread(thread_id: str):
    """Rebuild a thread as the same UI events the live stream emits."""
    found = await asyncio.to_thread(_read_thread, thread_id)
    if found is None:
        raise HTTPException(status_code=404, detail=f"Unknown thread_id '{thread_id}'")
    messages, todos, updated_at, paused = found
    return {
        "thread_id": thread_id,
        "title": _title(messages),
        "updated_at": updated_at,
        "paused": paused,
        "events": EventMapper().replay(messages, todos),
    }


# ---------------------------------------------------------------- files

def _clean_rel_path(path: str) -> str:
    """'/workspace/blogs/x.md' -> 'blogs/x.md'; rejects '..'."""
    rel = path.strip().lstrip("/").removeprefix("workspace/")
    parts = [p for p in rel.split("/") if p not in ("", ".")]
    if not parts or ".." in parts:
        raise HTTPException(status_code=400, detail="Invalid path")
    return "/".join(parts)


def _read_host_file(rel: str) -> bytes | None:
    if rel.split("/")[0] not in config.CONTENT_DIRS:
        return None
    full = (config.PROJECT_ROOT / rel).resolve()
    if not full.is_relative_to(config.PROJECT_ROOT) or not full.is_file():
        return None
    return full.read_bytes()


@router.get("/{thread_id}/files")
async def list_files(thread_id: str):
    """Content files (blogs/, research/, output/ …) in the thread's sandbox."""
    runner = pool.get(thread_id)
    if runner is None:
        return {"files": []}
    dirs = " ".join(shlex.quote(d) for d in config.CONTENT_DIRS)
    cmd = f'cd {config.SANDBOX_WORKDIR} && for d in {dirs}; do [ -d "$d" ] && find "$d" -type f; done; true'
    result = await asyncio.to_thread(runner.backend.execute, cmd)  # pyright: ignore[reportAttributeAccessIssue]
    paths = [line.strip() for line in (result.output or "").splitlines() if line.strip()]
    return {"files": [{"path": p, "kind": file_kind(p), "source": "sandbox"} for p in paths]}


@router.get("/{thread_id}/files/raw")
async def read_file_raw(thread_id: str, path: str):
    """Serve one file: the thread's sandbox first, then the host content dirs."""
    rel = _clean_rel_path(path)
    content = None
    runner = pool.get(thread_id)
    if runner is not None:
        resp = (await asyncio.to_thread(runner.backend.download_files, [rel]))[0]
        if not resp.error:
            content = resp.content
    if content is None:
        content = _read_host_file(rel)
    if content is None:
        raise HTTPException(status_code=404, detail=f"File not found: {rel}")

    media_type = mimetypes.guess_type(rel)[0] or "application/octet-stream"
    if rel.endswith((".md", ".markdown")):
        media_type = "text/markdown; charset=utf-8"
    return Response(content=content, media_type=media_type)
