import { useCallback, useReducer, useRef } from "react";
import { api, streamSSE } from "../api/client.js";
import { initialThreadState, threadReducer } from "../state/threadReducer.js";

/**
 * Owns one thread's render state and the actions that drive it:
 * run, resume, stop, armCrash, load (hydrate from history) and reset.
 * `onThreadChange(id)` fires when the server assigns or the user opens a thread.
 */
export function useAgentStream({ onThreadChange, onRunFinished } = {}) {
  const [state, dispatch] = useReducer(threadReducer, initialThreadState);
  const abortRef = useRef(null);
  const threadRef = useRef(null);
  threadRef.current = state.threadId;

  const consume = useCallback(
    async (path, body) => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      try {
        const finished = await streamSSE(
          path,
          body,
          (event) => {
            if (event.type === "thread") onThreadChange?.(event.thread_id);
            dispatch({ type: "event", event });
          },
          controller.signal
        );
        if (!finished && !controller.signal.aborted) dispatch({ type: "disconnected" });
      } catch (err) {
        if (!controller.signal.aborted) dispatch({ type: "disconnected", error: err.message });
      } finally {
        if (abortRef.current === controller) abortRef.current = null;
        onRunFinished?.();
      }
    },
    [onThreadChange, onRunFinished]
  );

  const run = useCallback(
    (task) => {
      dispatch({ type: "user_message", text: task });
      return consume("/api/run", { task, thread_id: threadRef.current });
    },
    [consume]
  );

  const resume = useCallback(() => {
    if (!threadRef.current) return;
    dispatch({ type: "resuming" });
    return consume("/api/resume", { thread_id: threadRef.current });
  }, [consume]);

  const stop = useCallback(async () => {
    if (!threadRef.current) return;
    dispatch({ type: "stopping" });
    try {
      await api.stop(threadRef.current);
    } catch (err) {
      // No live runner: just drop the connection.
      abortRef.current?.abort();
      dispatch({ type: "event", event: { type: "stopped" } });
    }
  }, []);

  const armCrash = useCallback(async () => {
    if (!threadRef.current) return;
    try {
      await api.armCrash(threadRef.current);
      dispatch({ type: "notice", variant: "crash", text: "Crash armed: the next tool call will fail." });
    } catch (err) {
      dispatch({ type: "notice", variant: "crash", text: `Could not arm crash: ${err.message}` });
    }
  }, []);

  const load = useCallback(async (threadId) => {
    abortRef.current?.abort();
    dispatch({ type: "loading", threadId });
    try {
      const data = await api.getThread(threadId);
      dispatch({ type: "hydrate", threadId, title: data.title, events: data.events, paused: data.paused });
    } catch (err) {
      dispatch({ type: "hydrate", threadId, title: "", events: [], paused: false });
      dispatch({ type: "notice", variant: "crash", text: `Could not load this thread: ${err.message}` });
    }
  }, []);

  const reset = useCallback(() => {
    abortRef.current?.abort();
    dispatch({ type: "reset" });
  }, []);

  return { state, run, resume, stop, armCrash, load, reset };
}
