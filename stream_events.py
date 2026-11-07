"""
Normalize LangGraph v2 stream chunks into a small, JSON-safe UI protocol.

The agent is streamed with::

    agent.stream(input, config,
                 stream_mode=["updates", "messages"],
                 subgraphs=True, version="v2")

Every chunk is ``{"type": "updates" | "messages", "ns": tuple, "data": ...}``.
``ns == ()`` is the coordinator; subagents (the deepagents ``task`` tool) run
in a namespace like ``("tools:<pregel-task-id>",)`` and their message metadata
carries ``lc_agent_name`` (the subagent name).

`EventMapper.map(chunk)` returns a list of UI events (see `EVENT TYPES`).
`EventMapper.replay(messages, todos)` turns a stored message list into the
same events so a reloaded thread renders exactly like a live one.

EVENT TYPES
-----------
token           {msg_id, text, agent, parent}             incremental AI text
message         {msg_id, role, content, agent, parent}    finalized human/AI message
tool_call       {call_id, name, args, agent, parent}
tool_result     {call_id, name, content, status, agent, parent}
subagent_start  {call_id, subagent_type, description}
subagent_end    {call_id, subagent_type, result, status}
todos           {todos: [{content, status}]}
file            {path, kind, tool}
evaluation      {call_id, score, result, checks, next_steps, raw}

`parent` is the `call_id` of the `task` call a subagent event belongs to
(None for the coordinator), so the UI can nest it under the right card.
"""

from __future__ import annotations

import json
import re
from typing import Any

MAIN = "main"
TOOL_RESULT_LIMIT = 4000

# Tools whose arguments name a file the agent produced.
_FILE_TOOLS = {
    "write_file": ("file_path", "path"),
    "edit_file": ("file_path", "path"),
    "download_image": ("filename",),
    "move_file": ("dest_path",),
}
_IMAGE_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg")
_MD_EXT = (".md", ".markdown", ".txt")


def file_kind(path: str) -> str:
    p = path.lower()
    if p.endswith(_IMAGE_EXT):
        return "image"
    if p.endswith(_MD_EXT):
        return "markdown"
    return "other"


def _text(content: Any) -> str:
    """Flatten LangChain message content (str or list of blocks) to text."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") in ("text", "text-delta"):
                parts.append(block.get("text", ""))
        return "".join(parts)
    return str(content)


def _safe(value: Any) -> Any:
    """Make tool args JSON-serializable."""
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return json.loads(json.dumps(value, default=str))


def _truncate(text: str, limit: int = TOOL_RESULT_LIMIT) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n… ({len(text) - limit} more characters)"


_SCORE_RE = re.compile(r"Score:\s*\**\s*(\d+(?:\.\d+)?)\s*/\s*10", re.I)
_SCORE_LOOSE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:/|out of)\s*10\b", re.I)
_RESULT_RE = re.compile(r"Result:\s*\**\s*(PASS|FAIL)", re.I)
_RESULT_LOOSE_RE = re.compile(r"\b(PASS|FAIL)(?:ED|ES)?\b")
_CHECK_RE = re.compile(r"^\s*[-*]\s*\**(Content|Research|Images?|YouTube)\**\s*:\s*\**\s*(PASS|FAIL)", re.I | re.M)
_NEXT_RE = re.compile(r"#+\s*Next Steps\s*\n(.*)", re.I | re.S)


def parse_evaluation(raw: str) -> dict:
    """Parse the evaluator subagent's fixed markdown format (subagents.yaml)."""
    # Strict format first (subagents.yaml), then prose like "scored a 7 out of 10 … PASS".
    score = _SCORE_RE.search(raw) or _SCORE_LOOSE_RE.search(raw)
    result = _RESULT_RE.search(raw) or _RESULT_LOOSE_RE.search(raw)
    checks = {}
    for name, verdict in _CHECK_RE.findall(raw):
        key = name.lower().rstrip("s") if name.lower().startswith("image") else name.lower()
        checks["images" if key == "image" else key] = verdict.upper()
    next_steps = []
    m = _NEXT_RE.search(raw)
    if m:
        for line in m.group(1).splitlines():
            line = line.strip()
            if line.startswith("#"):
                break
            if line.startswith(("-", "*")):
                next_steps.append(line.lstrip("-* ").strip())
    score_val = float(score.group(1)) if score else None
    verdict = result.group(1).upper() if result else (
        None if score_val is None else ("PASS" if score_val > 5 else "FAIL")
    )
    return {"score": score_val, "result": verdict, "checks": checks, "next_steps": next_steps, "raw": raw}


class EventMapper:
    """Stateful per-run translator. Not thread-safe; one per stream."""

    def __init__(self) -> None:
        self.seen: set[str] = set()          # message ids already emitted as `message`
        self.calls: dict[str, dict] = {}     # call_id -> {name, args, parent}
        self.pending_tasks: list[str] = []   # task call_ids not yet bound to a namespace
        self.ns_to_call: dict[str, str] = {} # ns[0] -> task call_id
        self.last_todos: Any = None

    # ------------------------------------------------------------------ #
    # Namespace -> subagent binding
    # ------------------------------------------------------------------ #
    def _parent_for(self, ns: tuple, agent_name: str | None) -> str | None:
        if not ns:
            return None
        key = ns[0]
        if key in self.ns_to_call:
            return self.ns_to_call[key]
        # Bind this new namespace to the oldest open task call, preferring
        # one whose subagent_type matches the agent name in the metadata.
        choice = None
        for cid in self.pending_tasks:
            if agent_name and self.calls[cid]["args"].get("subagent_type") == agent_name:
                choice = cid
                break
        if choice is None and self.pending_tasks:
            choice = self.pending_tasks[0]
        if choice is not None:
            self.pending_tasks.remove(choice)
            self.ns_to_call[key] = choice
        return choice

    def _agent_label(self, parent: str | None, agent_name: str | None) -> str:
        if parent is None:
            return MAIN
        return agent_name or self.calls.get(parent, {}).get("args", {}).get("subagent_type") or "subagent"

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def map(self, chunk: dict) -> list[dict]:
        ctype, ns, data = chunk.get("type"), tuple(chunk.get("ns") or ()), chunk.get("data")
        if ctype == "messages":
            return self._on_token(ns, data)
        if ctype == "updates":
            return self._on_updates(ns, data)
        return []

    def replay(self, messages: list, todos: Any = None) -> list[dict]:
        """Turn a stored (coordinator) message list into UI events."""
        events: list[dict] = []
        for msg in messages:
            events.extend(self._on_message(msg, (), None))
        if todos:
            events.append({"type": "todos", "todos": _safe(todos)})
        return events

    # ------------------------------------------------------------------ #
    # Handlers
    # ------------------------------------------------------------------ #
    def _on_token(self, ns: tuple, data: Any) -> list[dict]:
        try:
            msg, meta = data
        except (TypeError, ValueError):
            return []
        if getattr(msg, "type", None) not in ("ai", "AIMessageChunk"):
            return []
        text = _text(getattr(msg, "content", ""))
        if not text or not getattr(msg, "id", None):
            return []
        agent_name = (meta or {}).get("lc_agent_name")
        parent = self._parent_for(ns, agent_name)
        return [{
            "type": "token",
            "msg_id": msg.id,
            "text": text,
            "agent": self._agent_label(parent, agent_name),
            "parent": parent,
        }]

    def _on_updates(self, ns: tuple, data: Any) -> list[dict]:
        if not isinstance(data, dict):
            return []
        events: list[dict] = []
        for _node, update in data.items():
            if not isinstance(update, dict):
                continue
            parent = self._parent_for(ns, None)
            msgs = update.get("messages")
            if isinstance(msgs, (list, tuple)):
                for msg in msgs:
                    events.extend(self._on_message(msg, ns, parent))
            if "todos" in update and not ns and update["todos"] != self.last_todos:
                self.last_todos = update["todos"]
                events.append({"type": "todos", "todos": _safe(update["todos"] or [])})
        return events

    def _on_message(self, msg: Any, ns: tuple, parent: str | None) -> list[dict]:
        mid = getattr(msg, "id", None)
        if mid and mid in self.seen:
            return []
        if mid:
            self.seen.add(mid)
        mtype = getattr(msg, "type", None)
        agent = self._agent_label(parent, None)
        events: list[dict] = []

        if mtype in ("human", "ai"):
            content = _text(getattr(msg, "content", ""))
            if content.strip():
                events.append({
                    "type": "message",
                    "msg_id": mid,
                    "role": mtype,
                    "content": content,
                    "agent": agent,
                    "parent": parent,
                })
            for tc in getattr(msg, "tool_calls", None) or []:
                events.extend(self._on_tool_call(tc, agent, parent))

        elif mtype == "tool":
            events.extend(self._on_tool_result(msg, agent, parent))
        return events

    def _on_tool_call(self, tc: dict, agent: str, parent: str | None) -> list[dict]:
        cid = tc.get("id") or ""
        name = tc.get("name", "")
        args = _safe(tc.get("args") or {})
        self.calls[cid] = {"name": name, "args": args, "parent": parent}
        events = [{
            "type": "tool_call",
            "call_id": cid,
            "name": name,
            "args": args,
            "agent": agent,
            "parent": parent,
        }]
        if name == "task":
            self.pending_tasks.append(cid)
            events.append({
                "type": "subagent_start",
                "call_id": cid,
                "subagent_type": args.get("subagent_type", "subagent"),
                "description": args.get("description", ""),
            })
        if name in _FILE_TOOLS:
            for key in _FILE_TOOLS[name]:
                path = args.get(key)
                if name == "download_image":
                    path = path or "social_image.png"
                    # download_image always saves under output/ on the host
                    path = f"output/{path}"
                if path:
                    events.append({"type": "file", "path": path, "kind": file_kind(path), "tool": name})
                    break
        return events

    def _on_tool_result(self, msg: Any, agent: str, parent: str | None) -> list[dict]:
        cid = getattr(msg, "tool_call_id", "") or ""
        call = self.calls.get(cid, {})
        name = getattr(msg, "name", None) or call.get("name", "")
        content = _text(getattr(msg, "content", ""))
        status = getattr(msg, "status", "success") or "success"
        events = [{
            "type": "tool_result",
            "call_id": cid,
            "name": name,
            "content": _truncate(content),
            "status": status,
            "agent": agent,
            "parent": parent,
        }]
        if name == "task":
            if cid in self.pending_tasks:
                self.pending_tasks.remove(cid)
            sub = call.get("args", {}).get("subagent_type", "subagent")
            events.append({
                "type": "subagent_end",
                "call_id": cid,
                "subagent_type": sub,
                "result": content,
                "status": status,
            })
            if sub == "evaluator":
                events.append({"type": "evaluation", "call_id": cid, **parse_evaluation(content)})
        return events
