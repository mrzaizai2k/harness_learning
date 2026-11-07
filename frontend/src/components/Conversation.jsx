import { useEffect, useRef, useState } from "react";
import Icon from "./Icon.jsx";
import Timeline from "./Timeline.jsx";

const SAMPLES = [
  {
    title: "Blog post",
    text: "Write a blog post about how AI agents are transforming software development",
  },
  {
    title: "LinkedIn post",
    text: "Write a LinkedIn post about the rise of open-source LLMs in 2026",
  },
  {
    title: "Code research",
    text: "Use codeanalyzer subagent to deep research on code_base_c_test folder code",
  },
  {
    title: "File summary",
    text: "List the files, then read one file, count its words and write a summary of it",
  },
];

function EmptyState({ onPick }) {
  return (
    <div className="empty">
      <div className="empty-mark" aria-hidden="true">
        <Icon name="bot" size={28} />
      </div>
      <h1>What should we create today?</h1>
      <p className="muted">
        The agent researches the topic, writes the draft, finds an image and a video, then grades its own
        work until it passes.
      </p>
      <div className="samples">
        {SAMPLES.map((s) => (
          <button key={s.title} className="sample" onClick={() => onPick(s.text)}>
            <span className="sample-title">{s.title}</span>
            <span className="sample-text">{s.text}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

function Skeleton() {
  return (
    <div className="skeleton-wrap" aria-busy="true" aria-label="Loading conversation">
      <div className="skeleton sk-right" />
      <div className="skeleton sk-wide" />
      <div className="skeleton sk-card" />
      <div className="skeleton sk-card" />
      <div className="skeleton sk-wide" />
    </div>
  );
}

function Thinking() {
  return (
    <div className="thinking" role="status" aria-live="polite">
      <span />
      <span />
      <span />
      <span className="sr-only">Agent is working</span>
    </div>
  );
}

export default function Conversation({ state, onPickSample, children }) {
  const scrollRef = useRef(null);
  const innerRef = useRef(null);
  const stickRef = useRef(true);
  const [stick, setStick] = useState(true);

  const pin = () => {
    const el = scrollRef.current;
    if (el && stickRef.current) el.scrollTop = el.scrollHeight;
  };

  // Follow new output (including late layout like images and markdown)
  // unless the user has scrolled up to read.
  useEffect(pin);
  useEffect(() => {
    if (!innerRef.current || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(pin);
    ro.observe(innerRef.current);
    return () => ro.disconnect();
  }, []);

  // Opening another thread starts at the bottom again.
  useEffect(() => {
    stickRef.current = true;
    setStick(true);
  }, [state.threadId]);

  // Only real user input (wheel / touch / keys) can unpin.
  const onScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    if (atBottom !== stickRef.current) {
      stickRef.current = atBottom;
      setStick(atBottom);
    }
  };

  const running = state.status === "running" || state.status === "stopping";
  const empty = state.items.length === 0 && state.status !== "loading";

  return (
    <section className="conversation" aria-label="Conversation">
      <div className="conv-scroll" ref={scrollRef} onScroll={onScroll}>
        <div className="conv-inner" ref={innerRef}>
          {state.status === "loading" && <Skeleton />}
          {empty && <EmptyState onPick={onPickSample} />}
          <Timeline items={state.items} state={state} />
          {running && <Thinking />}
        </div>
      </div>
      {!stick && (
        <button
          className="btn btn-pill jump"
          onClick={() => {
            stickRef.current = true;
            setStick(true);
            scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
          }}
        >
          Jump to latest
        </button>
      )}
      <div className="conv-footer">{children}</div>
    </section>
  );
}
