import { useState } from "react";
import Icon from "./Icon.jsx";
import { TOOL_LABELS } from "../constants.js";

function summarize(name, args = {}) {
  const v =
    args.query || args.file_path || args.path || args.filename || args.dest_path || args.pattern || args.command;
  if (typeof v === "string") return v;
  if (name === "write_todos" && Array.isArray(args.todos)) return `${args.todos.length} tasks`;
  return "";
}

export function duration(start, end) {
  if (!start || !end) return null;
  const s = (end - start) / 1000;
  return s < 1 ? `${Math.round(s * 1000)}ms` : `${s.toFixed(1)}s`;
}

export function StatusDot({ status }) {
  if (status === "running") return <span className="spinner" aria-label="Running" />;
  if (status === "error") return <Icon name="x" size={14} className="tone-danger" title="Failed" />;
  if (status === "interrupted") return <Icon name="alert" size={14} className="tone-warn" title="Interrupted" />;
  return <Icon name="check" size={14} className="tone-success" title="Done" />;
}

export default function ToolCallCard({ tool }) {
  const [open, setOpen] = useState(false);
  const label = TOOL_LABELS[tool.name] || tool.name;
  const detail = summarize(tool.name, tool.args);
  const time = duration(tool.startedAt, tool.endedAt);

  return (
    <div className={`tool-card ${open ? "is-open" : ""} status-${tool.status}`}>
      <button className="tool-head" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <StatusDot status={tool.status} />
        <span className="tool-label">{label}</span>
        {detail && <span className="tool-detail">{detail}</span>}
        <span className="tool-meta">
          <code>{tool.name}</code>
          {time && <span>{time}</span>}
        </span>
        <Icon name="chevron" size={14} className="chev" />
      </button>
      {open && (
        <div className="tool-body">
          <div className="tool-section">
            <div className="tool-section-title">Input</div>
            <pre>{JSON.stringify(tool.args, null, 2)}</pre>
          </div>
          <div className="tool-section">
            <div className="tool-section-title">Output</div>
            <pre>{tool.result ?? (tool.status === "running" ? "Waiting for result…" : "No output")}</pre>
          </div>
        </div>
      )}
    </div>
  );
}
