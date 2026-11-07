// Turns the backend's UI events (see stream_events.py) into render state.
//
// Timeline model: `items` is the coordinator's ordered timeline; each
// subagent keeps its own ordered `items`. An item is a reference:
//   { kind: "message", id } | { kind: "tool", id } | { kind: "subagent", id } | { kind: "notice", ... }

export const initialThreadState = {
  threadId: null,
  title: "",
  status: "idle", // idle | loading | running | stopping | paused | done | stopped | disconnected | error
  error: null,
  items: [],
  messages: {},
  tools: {},
  subagents: {},
  todos: [],
  files: [],
  evaluations: [],
};

function pushItem(state, parent, item) {
  if (parent && state.subagents[parent]) {
    const sub = state.subagents[parent];
    return {
      ...state,
      subagents: { ...state.subagents, [parent]: { ...sub, items: [...sub.items, item] } },
    };
  }
  return { ...state, items: [...state.items, item] };
}

function addFile(files, file) {
  const norm = (p) => p.replace(/^\/+/, "").replace(/^workspace\//, "");
  const path = norm(file.path);
  if (files.some((f) => norm(f.path) === path)) return files;
  return [...files, { path, kind: file.kind || "other" }];
}

export function applyEvent(state, ev) {
  switch (ev.type) {
    case "thread":
      return { ...state, threadId: ev.thread_id };

    case "token": {
      const existing = state.messages[ev.msg_id];
      if (existing) {
        if (!existing.streaming) return state;
        return {
          ...state,
          messages: { ...state.messages, [ev.msg_id]: { ...existing, content: existing.content + ev.text } },
        };
      }
      const next = {
        ...state,
        messages: {
          ...state.messages,
          [ev.msg_id]: { id: ev.msg_id, role: "ai", content: ev.text, agent: ev.agent, streaming: true },
        },
      };
      return pushItem(next, ev.parent, { kind: "message", id: ev.msg_id });
    }

    case "message": {
      const msg = { id: ev.msg_id, role: ev.role, content: ev.content, agent: ev.agent, streaming: false };
      if (state.messages[ev.msg_id]) {
        return { ...state, messages: { ...state.messages, [ev.msg_id]: msg } };
      }
      // Live runs add the human prompt locally; skip the server echo.
      if (ev.role === "human") {
        const dup = state.items.some(
          (it) => it.kind === "message" && state.messages[it.id]?.role === "human" && state.messages[it.id]?.content === ev.content && it.local
        );
        if (dup) return state;
      }
      const next = { ...state, messages: { ...state.messages, [ev.msg_id]: msg } };
      return pushItem(next, ev.parent, { kind: "message", id: ev.msg_id });
    }

    case "tool_call": {
      const prior = state.tools[ev.call_id];
      if (prior) {
        if (prior.status !== "interrupted") return state;
        return { ...state, tools: { ...state.tools, [ev.call_id]: { ...prior, status: "running", startedAt: Date.now() } } };
      }
      const tool = {
        id: ev.call_id,
        name: ev.name,
        args: ev.args,
        agent: ev.agent,
        status: "running",
        result: null,
        startedAt: Date.now(),
        endedAt: null,
      };
      const next = { ...state, tools: { ...state.tools, [ev.call_id]: tool } };
      // `task` calls are rendered as subagent cards instead of tool cards.
      if (ev.name === "task") return next;
      return pushItem(next, ev.parent, { kind: "tool", id: ev.call_id });
    }

    case "tool_result": {
      const tool = state.tools[ev.call_id];
      if (!tool) return state;
      return {
        ...state,
        tools: {
          ...state.tools,
          [ev.call_id]: {
            ...tool,
            status: ev.status === "error" ? "error" : "done",
            result: ev.content,
            endedAt: Date.now(),
          },
        },
      };
    }

    case "subagent_start": {
      if (state.subagents[ev.call_id]) return state;
      const next = {
        ...state,
        subagents: {
          ...state.subagents,
          [ev.call_id]: {
            id: ev.call_id,
            type: ev.subagent_type,
            description: ev.description,
            status: "running",
            result: null,
            items: [],
            startedAt: Date.now(),
            endedAt: null,
          },
        },
      };
      return pushItem(next, null, { kind: "subagent", id: ev.call_id });
    }

    case "subagent_end": {
      const sub = state.subagents[ev.call_id];
      if (!sub) return state;
      return {
        ...state,
        subagents: {
          ...state.subagents,
          [ev.call_id]: {
            ...sub,
            status: ev.status === "error" ? "error" : "done",
            result: ev.result,
            endedAt: Date.now(),
          },
        },
      };
    }

    case "todos":
      return { ...state, todos: ev.todos || [] };

    case "file":
      return { ...state, files: addFile(state.files, ev) };

    case "evaluation":
      if (state.evaluations.some((e) => e.call_id === ev.call_id)) return state;
      return { ...state, evaluations: [...state.evaluations, ev] };

    case "crash":
      return pushItem(
        { ...state, status: "paused", error: ev.error, tools: interrupt(state.tools), subagents: interrupt(state.subagents) },
        null,
        { kind: "notice", variant: "crash", text: `Run crashed: ${ev.error}` }
      );

    case "stopped":
      return pushItem({ ...state, status: "stopped", tools: interrupt(state.tools), subagents: interrupt(state.subagents) }, null, {
        kind: "notice",
        variant: "info",
        text: "Run stopped. You can resume it from the last checkpoint.",
      });

    case "done":
      if (["running", "stopping"].includes(state.status)) {
        return { ...state, status: "done", messages: finalizeStreaming(state.messages) };
      }
      return { ...state, messages: finalizeStreaming(state.messages) };

    default:
      return state;
  }
}

/** Mark still-running tool / subagent cards as interrupted. Resuming
 *  re-runs them under the same call ids, so they flip back to done. */
function interrupt(obj) {
  let changed = false;
  const out = {};
  for (const [k, v] of Object.entries(obj)) {
    if (v.status === "running") {
      changed = true;
      out[k] = { ...v, status: "interrupted", endedAt: null };
    } else out[k] = v;
  }
  return changed ? out : obj;
}

function finalizeStreaming(messages) {
  let changed = false;
  const out = {};
  for (const [id, m] of Object.entries(messages)) {
    if (m.streaming) {
      changed = true;
      out[id] = { ...m, streaming: false };
    } else out[id] = m;
  }
  return changed ? out : messages;
}

export function threadReducer(state, action) {
  switch (action.type) {
    case "reset":
      return { ...initialThreadState };

    case "loading":
      return { ...initialThreadState, threadId: action.threadId, status: "loading" };

    case "hydrate": {
      let next = { ...initialThreadState, threadId: action.threadId, title: action.title, status: "loading" };
      for (const ev of action.events) next = applyEvent(next, ev);
      // Replayed history has no live results pending: close open cards.
      const closeAll = (obj) =>
        Object.fromEntries(
          Object.entries(obj).map(([k, v]) => [
            k,
            {
              ...v,
              // Replay has no real timings.
              startedAt: null,
              endedAt: null,
              status: v.status === "running" ? (action.paused ? "interrupted" : "done") : v.status,
            },
          ])
        );
      return {
        ...next,
        tools: closeAll(next.tools),
        subagents: closeAll(next.subagents),
        messages: finalizeStreaming(next.messages),
        status: action.paused ? "paused" : "done",
      };
    }

    case "user_message": {
      const id = `local-${Date.now()}`;
      const next = {
        ...state,
        title: state.title || action.text.slice(0, 60),
        status: "running",
        error: null,
        messages: { ...state.messages, [id]: { id, role: "human", content: action.text, agent: "main" } },
      };
      return pushItem(next, null, { kind: "message", id, local: true });
    }

    case "resuming":
      return pushItem({ ...state, status: "running", error: null }, null, {
        kind: "notice",
        variant: "resume",
        text: "Resuming from the last checkpoint…",
      });

    case "stopping":
      return { ...state, status: "stopping" };

    case "disconnected":
      return pushItem({ ...state, status: "disconnected" }, null, {
        kind: "notice",
        variant: "crash",
        text: action.error ? `Connection lost: ${action.error}` : "Connection lost before the run finished.",
      });

    case "notice":
      return pushItem(state, null, { kind: "notice", variant: action.variant || "info", text: action.text });

    case "event":
      return applyEvent(state, action.event);

    default:
      return state;
  }
}

// ---- derived helpers -------------------------------------------------- //

/** All of the coordinator's replies, newest first (for hashtags / videos). */
export function finalAnswer(state) {
  const out = [];
  for (let i = state.items.length - 1; i >= 0; i--) {
    const it = state.items[i];
    if (it.kind !== "message") continue;
    const m = state.messages[it.id];
    if (m && m.role === "ai" && m.content.trim()) out.push(m.content);
  }
  return out.join("\n\n");
}

export function extractHashtags(text) {
  const tags = text.match(/(^|\s)#[A-Za-z][\w-]{1,40}/g) || [];
  return [...new Set(tags.map((t) => t.trim()))].slice(0, 20);
}

export function extractYouTube(text) {
  const re = /https?:\/\/(?:www\.)?(?:youtube\.com\/watch\?v=|youtu\.be\/)([\w-]{6,})[^\s)\]]*/g;
  const out = [];
  const seen = new Set();
  let m;
  while ((m = re.exec(text))) {
    if (seen.has(m[1])) continue;
    seen.add(m[1]);
    // Use the markdown link text right before the URL as the title, if any.
    const before = text.slice(0, m.index);
    const prevLines = before.split("\n").slice(-3).join("\n");
    const title =
      before.match(/\[([^\]]{3,140})\]\($/)?.[1] ||
      prevLines.match(/\*\*([^*\n]{3,140})\*\*[^*]*$/)?.[1] ||
      prevLines.match(/["“]([^"”\n]{3,140})["”][^"]*$/)?.[1] ||
      null;
    out.push({ id: m[1], url: m[0], title });
  }
  return out;
}
