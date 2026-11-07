import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client.js";

/** Read the thread id from the URL hash: #/t/<id> */
export function readHashThread() {
  const m = window.location.hash.match(/^#\/t\/([^/?#]+)/);
  return m ? decodeURIComponent(m[1]) : null;
}

export function setHashThread(id) {
  const next = id ? `#/t/${encodeURIComponent(id)}` : "#/";
  if (window.location.hash !== next) window.history.pushState(null, "", next);
}

/** Thread list from GET /api/threads, with a manual refresh. */
export function useThreads() {
  const [threads, setThreads] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const refresh = useCallback(async () => {
    try {
      const data = await api.listThreads();
      setThreads(data.threads || []);
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return { threads, loading, error, refresh };
}

/** Subscribe to back/forward navigation between threads. */
export function useHashThread(onChange) {
  useEffect(() => {
    const handler = () => onChange(readHashThread());
    window.addEventListener("popstate", handler);
    window.addEventListener("hashchange", handler);
    return () => {
      window.removeEventListener("popstate", handler);
      window.removeEventListener("hashchange", handler);
    };
  }, [onChange]);
}
