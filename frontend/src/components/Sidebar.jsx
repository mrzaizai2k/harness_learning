import { forwardRef, useMemo, useState } from "react";
import Icon from "./Icon.jsx";

function relTime(iso) {
  if (!iso) return "";
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  if (diff < 86400 * 7) return `${Math.floor(diff / 86400)}d ago`;
  return new Date(iso).toLocaleDateString();
}

const Sidebar = forwardRef(function Sidebar(
  { threads, loading, error, activeId, activeStatus, onSelect, onNew, onRetry, onClose },
  searchRef
) {
  const [q, setQ] = useState("");
  const filtered = useMemo(() => {
    const s = q.trim().toLowerCase();
    return s ? threads.filter((t) => (t.title || "").toLowerCase().includes(s) || t.thread_id.includes(s)) : threads;
  }, [threads, q]);

  return (
    <nav className="sidebar" aria-label="Threads">
      <div className="sidebar-top">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">
            <Icon name="bolt" size={14} />
          </span>
          <span>Content Studio</span>
          <button className="btn btn-icon btn-ghost sidebar-close" onClick={onClose} title="Close">
            <Icon name="x" size={16} />
            <span className="sr-only">Close sidebar</span>
          </button>
        </div>
        <button className="btn btn-primary btn-block" onClick={onNew}>
          <Icon name="plus" size={16} /> New task
        </button>
        <div className="search">
          <Icon name="search" size={14} />
          <input ref={searchRef} type="search" placeholder="Search threads" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search threads" />
          <kbd>⌘K</kbd>
        </div>
      </div>

      <div className="thread-list">
        {loading && [0, 1, 2, 3].map((i) => <div key={i} className="skeleton sk-thread" />)}
        {error && (
          <div className="sidebar-error">
            <p className="small">Can't reach the server.</p>
            <button className="btn btn-ghost btn-sm" onClick={onRetry}>
              <Icon name="refresh" size={14} /> Retry
            </button>
          </div>
        )}
        {!loading && !error && filtered.length === 0 && <p className="muted small pad">{q ? "No matching threads." : "No threads yet."}</p>}
        {filtered.map((t) => {
          const active = t.thread_id === activeId;
          const status = active && activeStatus === "running" ? "running" : t.paused ? "paused" : "done";
          return (
            <button key={t.thread_id} className={`thread ${active ? "is-active" : ""}`} onClick={() => onSelect(t.thread_id)} aria-current={active ? "page" : undefined}>
              <span className={`dot dot-${status}`} title={status} />
              <span className="thread-text">
                <span className="thread-title">{t.title || "Untitled task"}</span>
                <span className="thread-sub">
                  {relTime(t.updated_at)}
                  {status === "paused" && " · interrupted"}
                </span>
              </span>
            </button>
          );
        })}
      </div>
    </nav>
  );
});

export default Sidebar;
