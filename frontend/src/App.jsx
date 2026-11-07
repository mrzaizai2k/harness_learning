import { useCallback, useEffect, useRef, useState } from "react";
import Composer from "./components/Composer.jsx";
import Conversation from "./components/Conversation.jsx";
import CrashBanner from "./components/CrashBanner.jsx";
import Icon from "./components/Icon.jsx";
import RunPanel, { RunShortcuts } from "./components/RunPanel.jsx";
import Sidebar from "./components/Sidebar.jsx";
import { useAgentStream } from "./hooks/useAgentStream.js";
import { readHashThread, setHashThread, useHashThread, useThreads } from "./hooks/useThreads.js";

const DEBUG = new URLSearchParams(window.location.search).has("debug");

const STATUS_LABEL = {
  idle: null,
  loading: "Loading",
  running: "Running",
  stopping: "Stopping",
  paused: "Interrupted",
  disconnected: "Disconnected",
  stopped: "Stopped",
  done: "Done",
};

function useTheme() {
  const [theme, setTheme] = useState(() => {
    try {
      return localStorage.getItem("theme") || "system";
    } catch {
      return "system";
    }
  });
  useEffect(() => {
    const root = document.documentElement;
    if (theme === "system") root.removeAttribute("data-theme");
    else root.setAttribute("data-theme", theme);
    try {
      localStorage.setItem("theme", theme);
    } catch {
      /* storage blocked */
    }
  }, [theme]);
  const isDark =
    theme === "dark" || (theme === "system" && window.matchMedia?.("(prefers-color-scheme: dark)").matches);
  return { isDark, toggle: () => setTheme(isDark ? "light" : "dark") };
}

export default function App() {
  const { threads, loading, error, refresh } = useThreads();
  const composerRef = useRef(null);
  const searchRef = useRef(null);
  const { isDark, toggle } = useTheme();

  const [panelTab, setPanelTab] = useState("plan");
  const isWide = () => window.innerWidth >= 1024;
  // Remember the panel on wide screens; on narrow ones it is a drawer and starts closed.
  const [panelOpen, setPanelOpen] = useState(() => {
    if (!isWide()) return false;
    try {
      return localStorage.getItem("panelOpen") !== "false";
    } catch {
      return true;
    }
  });
  useEffect(() => {
    if (!isWide()) return;
    try {
      localStorage.setItem("panelOpen", String(panelOpen));
    } catch {
      /* storage blocked */
    }
  }, [panelOpen]);
  const openPanel = (tab) => {
    setPanelTab(tab);
    setPanelOpen(true);
  };
  const [sidebarOpen, setSidebarOpen] = useState(false);

  const onThreadChange = useCallback(
    (id) => {
      setHashThread(id);
      refresh(); // show the new thread in the sidebar right away
    },
    [refresh]
  );
  const { state, run, resume, stop, armCrash, load, reset } = useAgentStream({
    onThreadChange,
    onRunFinished: refresh,
  });

  // Open the thread named in the URL on first load and on back/forward.
  const openFromHash = useCallback(
    (id) => {
      if (id && id !== state.threadId) load(id);
      if (!id && state.threadId) reset();
    },
    [load, reset, state.threadId]
  );
  useEffect(() => {
    const id = readHashThread();
    if (id) load(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useHashThread(openFromHash);

  // Show the first produced file / evaluation as soon as it appears.
  const prevFiles = useRef(0);
  const prevEvals = useRef(0);
  useEffect(() => {
    const live = state.status === "running";
    if (live && state.files.length > prevFiles.current && prevFiles.current === 0) setPanelTab("output");
    if (live && state.evaluations.length > prevEvals.current) setPanelTab("evaluation");
    prevFiles.current = state.files.length;
    prevEvals.current = state.evaluations.length;
  }, [state.files.length, state.evaluations.length, state.status]);

  const busy = state.status === "running" || state.status === "stopping";

  // Keyboard: Esc stops a run, Cmd/Ctrl+K focuses thread search.
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === "Escape" && busy) {
        e.preventDefault();
        stop();
      }
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setSidebarOpen(true);
        requestAnimationFrame(() => searchRef.current?.focus());
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [busy, stop]);

  const newTask = () => {
    if (busy) return;
    reset();
    setHashThread(null);
    setSidebarOpen(false);
    requestAnimationFrame(() => composerRef.current?.focus());
  };

  const selectThread = (id) => {
    setSidebarOpen(false);
    if (id === state.threadId || busy) return;
    setHashThread(id);
    load(id);
  };

  const canResume = ["paused", "disconnected", "stopped"].includes(state.status);
  const statusLabel = STATUS_LABEL[state.status];

  return (
    <div className={`app ${panelOpen ? "panel-open" : ""} ${sidebarOpen ? "sidebar-open" : ""}`}>
      <Sidebar
        ref={searchRef}
        threads={threads}
        loading={loading}
        error={error}
        activeId={state.threadId}
        activeStatus={state.status}
        onSelect={selectThread}
        onNew={newTask}
        onRetry={refresh}
        onClose={() => setSidebarOpen(false)}
      />
      <div className="scrim" onClick={() => { setSidebarOpen(false); if (window.innerWidth < 1024) setPanelOpen(false); }} aria-hidden="true" />

      <main className="main">
        <header className="topbar">
          <button className="btn btn-icon btn-ghost only-mobile" onClick={() => setSidebarOpen(true)} title="Threads">
            <Icon name="menu" size={18} />
            <span className="sr-only">Open threads</span>
          </button>
          <div className="topbar-title">
            <h2>{state.title || (state.threadId ? "Untitled task" : "New task")}</h2>
            {state.threadId && <code className="thread-id">{state.threadId}</code>}
          </div>
          <div className="topbar-actions">
            {!panelOpen && <RunShortcuts state={state} onOpen={openPanel} />}
            {statusLabel && (
              <span className={`status-pill status-${state.status}`} aria-live="polite">
                {busy && <span className="spinner sm" />}
                {statusLabel}
              </span>
            )}
            {DEBUG && (
              <button className="btn btn-ghost btn-sm tone-danger" onClick={armCrash} disabled={!state.threadId || !busy} title="Debug: the next tool call will raise">
                <Icon name="alert" size={14} /> Simulate crash
              </button>
            )}
            <button className="btn btn-icon btn-ghost" onClick={toggle} title={isDark ? "Light theme" : "Dark theme"}>
              <Icon name={isDark ? "sun" : "moon"} size={16} />
              <span className="sr-only">Toggle theme</span>
            </button>
            <button className={`btn btn-icon btn-ghost ${panelOpen ? "is-on" : ""}`} onClick={() => setPanelOpen((o) => !o)} title="Run details">
              <Icon name="panel" size={16} />
              <span className="sr-only">Toggle run details</span>
            </button>
          </div>
        </header>

        <Conversation state={state} onPickSample={(text) => composerRef.current?.fill(text)}>
          {canResume && <CrashBanner status={state.status} error={state.error} onResume={resume} />}
          <Composer
            ref={composerRef}
            busy={busy}
            disabled={state.status === "loading"}
            onSend={run}
            onStop={stop}
            placeholder={canResume ? "Resume above, or send a new instruction…" : state.threadId ? "Ask for changes or a follow-up…" : "Describe the content you want…"}
          />
          <p className="hint">
            <kbd>Enter</kbd> to send · <kbd>Shift</kbd>+<kbd>Enter</kbd> for a new line{busy && <> · <kbd>Esc</kbd> to stop</>}
          </p>
        </Conversation>
      </main>

      <RunPanel state={state} tab={panelTab} onTab={setPanelTab} onClose={() => setPanelOpen(false)} />
    </div>
  );
}
