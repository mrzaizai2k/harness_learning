"""A JSON-file-backed drop-in for InMemorySaver.

Two files:
  memory.json - tiny human-readable index: which thread_ids exist / their status
  state.json  - the actual checkpoint data (opaque, don't hand-edit)

How it works: InMemorySaver already keeps everything in a few plain dicts
(self.storage, self.writes, self.blobs). We just mirror those dicts to disk
after every write, and reload them into the same dicts on startup. Nothing
about LangGraph's internals changes - we're just persisting its normal
in-memory data structures instead of losing them when the process exits.
"""

import base64
import json
import os
import threading
import uuid
from collections import defaultdict

from langgraph.checkpoint.memory import InMemorySaver


def _encode(obj):
    """Turn the saver's internal dicts (which have tuple keys and raw bytes)
    into something json.dump can handle."""
    if isinstance(obj, bytes):
        return {"__bytes__": base64.b64encode(obj).decode()}
    if isinstance(obj, tuple):
        return {"__tuple__": [_encode(x) for x in obj]}
    if isinstance(obj, dict):
        # dict keys are often tuples, so store as [key, value] pairs instead
        # of relying on JSON object keys (which must be strings)
        return {"__dict__": [[_encode(k), _encode(v)] for k, v in obj.items()]}
    if isinstance(obj, list):
        return [_encode(x) for x in obj]
    return obj  # str / int / float / bool / None


def _decode(obj):
    if isinstance(obj, dict):
        if "__bytes__" in obj:
            return base64.b64decode(obj["__bytes__"])
        if "__tuple__" in obj:
            return tuple(_decode(x) for x in obj["__tuple__"])
        if "__dict__" in obj:
            return {_decode(k): _decode(v) for k, v in obj["__dict__"]}
        return {k: _decode(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_decode(x) for x in obj]
    return obj


class JsonFileSaver(InMemorySaver):
    def __init__(self, state_path="state.json", memory_path="memory.json"):
        super().__init__()
        self.state_path = state_path
        self.memory_path = memory_path
        self._lock = threading.Lock()  # langgraph can call put/put_writes from
                                        # multiple worker threads concurrently
        self._load()

    # ---- reload previous run's data on startup ----
    def _load(self):
        if not os.path.exists(self.state_path):
            return
        with open(self.state_path) as f:
            raw = json.load(f)
        data = _decode(raw)

        self.storage = defaultdict(lambda: defaultdict(dict))
        for thread_id, ns_dict in data.get("storage", {}).items():
            self.storage[thread_id] = defaultdict(dict, ns_dict)

        self.writes = defaultdict(dict, data.get("writes", {}))
        self.blobs = dict(data.get("blobs", {}))

    # ---- persist to disk after every checkpoint write ----
    def _dump(self):
        # langgraph fans work out across worker threads, so put()/put_writes()
        # can land here concurrently - serialize disk writes and use a unique
        # tmp filename so two threads never race on the same rename.
        with self._lock:
            raw = _encode({
                "storage": {k: dict(v) for k, v in self.storage.items()},
                "writes": dict(self.writes),
                "blobs": dict(self.blobs),
            })
            tmp = f"{self.state_path}.{uuid.uuid4().hex}.tmp"
            with open(tmp, "w") as f:
                json.dump(raw, f)
            os.replace(tmp, self.state_path)  # atomic swap, no half-written file on crash

            # memory.json: just a friendly index of thread_ids, not required for
            # resuming (state.json alone is enough) but handy to eyeball
            index = {}
            if os.path.exists(self.memory_path):
                with open(self.memory_path) as f:
                    index = json.load(f)
            for thread_id in self.storage:
                index[thread_id] = {"thread_id": thread_id}
            with open(self.memory_path, "w") as f:
                json.dump(index, f, indent=2)

    def put(self, config, checkpoint, metadata, new_versions):
        result = super().put(config, checkpoint, metadata, new_versions)
        self._dump()
        return result

    def put_writes(self, config, writes, task_id, task_path=""):
        result = super().put_writes(config, writes, task_id, task_path)
        self._dump()
        return result