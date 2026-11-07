// Thin API client for the FastAPI backend (main.py).
export const API_BASE = (import.meta.env.VITE_API_BASE || "http://localhost:8000").replace(/\/$/, "");

async function json(path, options = {}) {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail || detail;
    } catch {
      /* not JSON */
    }
    const err = new Error(detail);
    err.status = res.status;
    throw err;
  }
  return res.json();
}

export const api = {
  listThreads: () => json("/api/threads"),
  getThread: (id) => json(`/api/threads/${encodeURIComponent(id)}`),
  listFiles: (id) => json(`/api/threads/${encodeURIComponent(id)}/files`),
  stop: (id) => json(`/api/threads/${encodeURIComponent(id)}/stop`, { method: "POST" }),
  armCrash: (id) => json("/api/arm_crash", { method: "POST", body: JSON.stringify({ thread_id: id }) }),
  fileUrl: (id, path) =>
    `${API_BASE}/api/threads/${encodeURIComponent(id)}/files/raw?path=${encodeURIComponent(path)}`,
};

/**
 * POST to an SSE endpoint and call onEvent(event) for every `data:` JSON line.
 * Resolves to `true` if the server sent a final `done` event, `false` if the
 * connection ended early (network drop / server restart).
 */
export async function streamSSE(path, body, onEvent, signal) {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok || !res.body) {
    throw new Error(`Request failed (${res.status})`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let sawDone = false;

  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop();
    for (const part of parts) {
      const line = part.trim();
      if (!line.startsWith("data:")) continue;
      const payload = line.slice(5).trim();
      if (!payload) continue;
      let event;
      try {
        event = JSON.parse(payload);
      } catch {
        continue;
      }
      if (event.type === "done") sawDone = true;
      onEvent(event);
    }
  }
  return sawDone;
}
