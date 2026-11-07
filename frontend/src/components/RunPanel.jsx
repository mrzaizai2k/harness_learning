import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client.js";
import { extractHashtags, extractYouTube, finalAnswer } from "../state/threadReducer.js";
import Icon from "./Icon.jsx";
import Markdown from "./Markdown.jsx";

// ------------------------------------------------------------------ Plan
function PlanTab({ todos }) {
  if (!todos.length) {
    return <PanelEmpty icon="list" title="No plan yet" text="The agent's todo list appears here once it starts planning." />;
  }
  const done = todos.filter((t) => t.status === "completed").length;
  const pct = Math.round((done / todos.length) * 100);
  return (
    <div className="plan">
      <div className="progress-row">
        <span>
          {done} of {todos.length} done
        </span>
        <span className="muted">{pct}%</span>
      </div>
      <div className="progress" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
        <div className="progress-bar" style={{ width: `${pct}%` }} />
      </div>
      <ol className="todo-list">
        {todos.map((t, i) => (
          <li key={i} className={`todo todo-${t.status}`}>
            <span className="todo-mark" aria-hidden="true">
              {t.status === "completed" ? <Icon name="check" size={12} /> : t.status === "in_progress" ? <span className="spinner sm" /> : null}
            </span>
            <span className="todo-text">{t.content}</span>
            <span className="sr-only">({t.status.replace("_", " ")})</span>
          </li>
        ))}
      </ol>
    </div>
  );
}

// ---------------------------------------------------------------- Output
function useFileText(threadId, file) {
  const [state, setState] = useState({ text: null, error: null, loading: false });
  useEffect(() => {
    if (!threadId || !file || file.kind === "image") return;
    let alive = true;
    setState({ text: null, error: null, loading: true });
    fetch(api.fileUrl(threadId, file.path))
      .then((r) => (r.ok ? r.text() : Promise.reject(new Error(r.status === 404 ? "File not found (the sandbox may have been closed)" : `HTTP ${r.status}`))))
      .then((text) => alive && setState({ text, error: null, loading: false }))
      .catch((err) => alive && setState({ text: null, error: err.message, loading: false }));
    return () => {
      alive = false;
    };
  }, [threadId, file?.path, file?.kind]);
  return state;
}

function CopyButton({ text, label = "Copy" }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      className="btn btn-ghost btn-sm"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        } catch {
          /* clipboard blocked */
        }
      }}
    >
      <Icon name={copied ? "check" : "copy"} size={14} /> {copied ? "Copied" : label}
    </button>
  );
}

function FilePreview({ threadId, file }) {
  const { text, error, loading } = useFileText(threadId, file);
  const url = api.fileUrl(threadId, file.path);
  return (
    <div className="file-preview">
      <div className="file-preview-head">
        <code title={file.path}>{file.path}</code>
        <div className="row-gap">
          {text && <CopyButton text={text} />}
          <a className="btn btn-ghost btn-sm" href={url} download={file.path.split("/").pop()}>
            <Icon name="download" size={14} /> Download
          </a>
        </div>
      </div>
      {file.kind === "image" ? (
        <img className="preview-img" src={url} alt={file.path} loading="lazy" />
      ) : loading ? (
        <div className="skeleton sk-card" />
      ) : error ? (
        <p className="muted small">{error}</p>
      ) : file.kind === "markdown" ? (
        <Markdown className="doc">{text}</Markdown>
      ) : (
        <pre className="code-block">{text}</pre>
      )}
    </div>
  );
}

function OutputTab({ state }) {
  const answer = finalAnswer(state);
  const hashtags = useMemo(() => extractHashtags(answer), [answer]);
  const videos = useMemo(() => extractYouTube(answer), [answer]);
  const files = state.files;
  const [selected, setSelected] = useState(null);
  const current = files.find((f) => f.path === selected) || files.find((f) => f.kind === "markdown") || files[0];

  if (!files.length && !hashtags.length && !videos.length) {
    return <PanelEmpty icon="file" title="Nothing produced yet" text="Posts, images, hashtags and videos the agent creates show up here." />;
  }

  return (
    <div className="output">
      {videos.length > 0 && (
        <section>
          <h3 className="panel-h">Recommended video</h3>
          {videos.map((v) => (
            <a key={v.id} className="video-card" href={v.url} target="_blank" rel="noreferrer noopener">
              <img src={`https://i.ytimg.com/vi/${v.id}/mqdefault.jpg`} alt="" loading="lazy" />
              <span className="video-meta">
                <span className="video-title">{v.title || "YouTube video"}</span>
                <span className="muted small">youtube.com</span>
              </span>
              <Icon name="play" size={16} />
            </a>
          ))}
        </section>
      )}

      {hashtags.length > 0 && (
        <section>
          <div className="row-between">
            <h3 className="panel-h">Hashtags</h3>
            <CopyButton text={hashtags.join(" ")} label="Copy all" />
          </div>
          <div className="chips">
            {hashtags.map((h) => (
              <span key={h} className="chip">
                {h}
              </span>
            ))}
          </div>
        </section>
      )}

      {files.length > 0 && (
        <section>
          <h3 className="panel-h">Files</h3>
          <ul className="file-list">
            {files.map((f) => (
              <li key={f.path}>
                <button className={`file-item ${current?.path === f.path ? "is-active" : ""}`} onClick={() => setSelected(f.path)}>
                  <Icon name={f.kind === "image" ? "image" : "file"} size={14} />
                  <span>{f.path}</span>
                </button>
              </li>
            ))}
          </ul>
          {current && state.threadId && <FilePreview threadId={state.threadId} file={current} />}
        </section>
      )}
    </div>
  );
}

// ------------------------------------------------------------ Evaluation
const CHECKS = [
  ["content", "Content"],
  ["research", "Research"],
  ["images", "Image"],
  ["youtube", "YouTube"],
];

function ScoreRing({ score, result }) {
  const pct = score == null ? 0 : Math.max(0, Math.min(10, score)) * 10;
  const tone = result === "PASS" ? "success" : result === "FAIL" ? "danger" : "muted";
  return (
    <div className={`score-ring tone-${tone}`} style={{ "--pct": pct }}>
      <div className="score-inner">
        <strong>{score == null ? "–" : score}</strong>
        <span>/10</span>
      </div>
    </div>
  );
}

function EvaluationTab({ evaluations }) {
  const [index, setIndex] = useState(null);
  if (!evaluations.length) {
    return <PanelEmpty icon="star" title="Not evaluated yet" text="The evaluator scores the draft out of 10. Anything 5 or below goes back for another round." />;
  }
  const i = index ?? evaluations.length - 1;
  const ev = evaluations[i];
  return (
    <div className="evaluation">
      {evaluations.length > 1 && (
        <div className="attempts" role="tablist" aria-label="Evaluation attempts">
          {evaluations.map((e, j) => (
            <button key={e.call_id} role="tab" aria-selected={j === i} className={`attempt ${j === i ? "is-active" : ""} tone-${e.result === "PASS" ? "success" : "danger"}`} onClick={() => setIndex(j)}>
              Attempt {j + 1}
            </button>
          ))}
        </div>
      )}
      <div className="score-row">
        <ScoreRing score={ev.score} result={ev.result} />
        <div>
          <span className={`verdict tone-${ev.result === "PASS" ? "success" : ev.result === "FAIL" ? "danger" : "muted"}`}>{ev.result || "Unscored"}</span>
          <p className="muted small">{ev.result === "PASS" ? "Ready for publication." : ev.result === "FAIL" ? "Sent back for another round." : "The evaluator did not return a score."}</p>
        </div>
      </div>
      {Object.keys(ev.checks || {}).length > 0 && (
        <ul className="checks">
          {CHECKS.filter(([k]) => ev.checks[k]).map(([k, label]) => (
            <li key={k} className={ev.checks[k] === "PASS" ? "tone-success" : "tone-danger"}>
              <Icon name={ev.checks[k] === "PASS" ? "check" : "x"} size={14} />
              <span>{label}</span>
            </li>
          ))}
        </ul>
      )}
      {ev.next_steps?.length > 0 && (
        <section>
          <h3 className="panel-h">Next steps</h3>
          <ul className="next-steps">
            {ev.next_steps.map((s, j) => (
              <li key={j}>{s}</li>
            ))}
          </ul>
        </section>
      )}
      <details className="raw-eval">
        <summary>Full evaluator report</summary>
        <Markdown>{ev.raw}</Markdown>
      </details>
    </div>
  );
}

// ----------------------------------------------------------------- Panel
function PanelEmpty({ icon, title, text }) {
  return (
    <div className="panel-empty">
      <Icon name={icon} size={22} />
      <strong>{title}</strong>
      <p className="muted small">{text}</p>
    </div>
  );
}

const TABS = [
  ["plan", "Plan"],
  ["output", "Output"],
  ["evaluation", "Evaluation"],
];

export default function RunPanel({ state, tab, onTab, onClose }) {
  const counts = {
    plan: state.todos.length ? `${state.todos.filter((t) => t.status === "completed").length}/${state.todos.length}` : null,
    output: state.files.length || null,
    evaluation: state.evaluations.length ? state.evaluations[state.evaluations.length - 1].result || "?" : null,
  };
  return (
    <aside className="run-panel" aria-label="Run details">
      <div className="panel-tabs" role="tablist">
        {TABS.map(([id, label]) => (
          <button key={id} role="tab" aria-selected={tab === id} className={`panel-tab ${tab === id ? "is-active" : ""}`} onClick={() => onTab(id)}>
            {label}
            {counts[id] != null && <span className={`count ${counts[id] === "PASS" ? "tone-success" : counts[id] === "FAIL" ? "tone-danger" : ""}`}>{counts[id]}</span>}
          </button>
        ))}
        <button className="btn btn-icon btn-ghost panel-close" onClick={onClose} title="Close panel">
          <Icon name="x" size={16} />
          <span className="sr-only">Close panel</span>
        </button>
      </div>
      <div className="panel-body" role="tabpanel">
        {tab === "plan" && <PlanTab todos={state.todos} />}
        {tab === "output" && <OutputTab state={state} />}
        {tab === "evaluation" && <EvaluationTab evaluations={state.evaluations} />}
      </div>
    </aside>
  );
}
