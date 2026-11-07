import { useState } from "react";
import Icon from "./Icon.jsx";
import Markdown from "./Markdown.jsx";
import MessageBubble from "./MessageBubble.jsx";
import ToolCallCard, { StatusDot, duration } from "./ToolCallCard.jsx";

const SUBAGENT_LABEL = {
  researcher: "Researcher",
  evaluator: "Evaluator",
  "general-purpose": "General assistant",
};

function prettyAgent(type) {
  return SUBAGENT_LABEL[type] || type.replace(/[_-]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function SubagentCard({ sub, state }) {
  const [open, setOpen] = useState(sub.status === "running");
  const steps = sub.items.filter((i) => i.kind === "tool").length;
  const verb = sub.status === "running" ? "working…" : sub.status === "error" ? "failed" : sub.status === "interrupted" ? "interrupted" : "finished";

  return (
    <div className={`sub-card status-${sub.status}`}>
      <button className="sub-head" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <span className="sub-badge">
          <Icon name="bot" size={14} />
        </span>
        <span className="sub-title">
          <strong>{prettyAgent(sub.type)}</strong> <span className="muted">{verb}</span>
        </span>
        <span className="sub-meta">
          {steps > 0 && <span>{steps} steps</span>}
          {duration(sub.startedAt, sub.endedAt) && <span>{duration(sub.startedAt, sub.endedAt)}</span>}
          <StatusDot status={sub.status} />
        </span>
        <Icon name="chevron" size={14} className="chev" />
      </button>
      {sub.description && <p className="sub-desc">{sub.description}</p>}
      {open && (
        <div className="sub-body">
          {sub.items.length === 0 && sub.status === "running" && (
            <p className="muted small">Waiting for the first step…</p>
          )}
          <Timeline items={sub.items} state={state} nested />
          {sub.result && (
            <details className="sub-result">
              <summary>Result returned to the main agent</summary>
              <Markdown>{sub.result}</Markdown>
            </details>
          )}
        </div>
      )}
    </div>
  );
}

function Notice({ item }) {
  const icon = item.variant === "crash" ? "alert" : item.variant === "resume" ? "refresh" : "bolt";
  return (
    <div className={`notice notice-${item.variant}`} role="status">
      <Icon name={icon} size={14} />
      <span>{item.text}</span>
    </div>
  );
}

export default function Timeline({ items, state, nested = false }) {
  return items.map((item, i) => {
    if (item.kind === "message") {
      const m = state.messages[item.id];
      return m ? <MessageBubble key={item.id} message={m} nested={nested} /> : null;
    }
    if (item.kind === "tool") {
      const t = state.tools[item.id];
      return t ? <ToolCallCard key={item.id} tool={t} /> : null;
    }
    if (item.kind === "subagent") {
      const s = state.subagents[item.id];
      return s ? <SubagentCard key={item.id} sub={s} state={state} /> : null;
    }
    if (item.kind === "notice") return <Notice key={`n-${i}`} item={item} />;
    return null;
  });
}
