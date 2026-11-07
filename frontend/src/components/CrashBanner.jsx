import Icon from "./Icon.jsx";

const COPY = {
  paused: { title: "Run interrupted", text: "The agent stopped mid-task. Resume picks up from the last checkpoint." },
  disconnected: { title: "Connection lost", text: "The stream ended before the run finished. Resume to continue." },
  stopped: { title: "Run stopped", text: "You stopped this run. Resume to continue from the last checkpoint." },
};

export default function CrashBanner({ status, error, onResume }) {
  const copy = COPY[status];
  if (!copy) return null;
  return (
    <div className={`banner banner-${status}`} role="alert">
      <Icon name="alert" size={16} />
      <div className="banner-text">
        <strong>{copy.title}</strong>
        <span>{status === "paused" && error ? error : copy.text}</span>
      </div>
      <button className="btn btn-primary btn-sm" onClick={onResume}>
        <Icon name="refresh" size={14} /> Resume
      </button>
    </div>
  );
}
