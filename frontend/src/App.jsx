import { useEffect, useRef, useState } from "react";

const API_BASE = "http://localhost:8000";

// Small icon set, kept as inline glyphs so no icon library is needed.
const ICONS = {
  user: "\u{1F464}", // 👤
  ai: "\u{1F916}", // 🤖
  tool: "\u2699", // ⚙
  crash: "\u26A0", // ⚠
  resume: "\u21BB", // ↻
  info: "\u2139", // ℹ
};

function roleLabel(role) {
  if (role === "human") return "You";
  if (role === "ai") return "Assistant";
  if (role === "tool") return "Tool result";
  return "System";
}

function roleIcon(role) {
  if (role === "human") return ICONS.user;
  if (role === "ai") return ICONS.ai;
  if (role === "tool") return ICONS.tool;
  return ICONS.info;
}

function ThinkingIndicator() {
  return (
    <div className="message message-thinking">
      <div className="message-icon">{ICONS.ai}</div>
      <div className="message-body">
        <div className="message-role">Assistant</div>
        <div className="thinking-dots">
          <span></span>
          <span></span>
          <span></span>
        </div>
      </div>
    </div>
  );
}

export default function App() {
  const [messages, setMessages] = useState([]); // {kind, role, content, tools}
  const [input, setInput] = useState("");
  const [threadId, setThreadId] = useState(null);
  const [isRunning, setIsRunning] = useState(false);
  const [isPaused, setIsPaused] = useState(false);
  const scrollRef = useRef(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, isRunning]);

  const appendMessage = (kind, role, content) => {
    setMessages((prev) => [...prev, { kind, role, content }]);
  };

  const appendNotice = (content, variant = "info") => {
    setMessages((prev) => [...prev, { kind: "notice", variant, content }]);
  };

  const appendToolCall = (tools) => {
    setMessages((prev) => [...prev, { kind: "tool-call", tools }]);
  };

  // Reads an SSE response body and calls onEvent for each parsed JSON event.
  const consumeStream = async (response, onEvent) => {
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      const parts = buffer.split("\n\n");
      buffer = parts.pop(); // last chunk may be incomplete, keep it in buffer

      for (const part of parts) {
        const line = part.trim();
        if (!line.startsWith("data:")) continue;
        const jsonStr = line.slice("data:".length).trim();
        if (!jsonStr) continue;
        onEvent(JSON.parse(jsonStr));
      }
    }
  };

  const handleEvent = (event) => {
    if (event.type === "thread") {
      setThreadId(event.thread_id);
    } else if (event.type === "step") {
      if (event.tool_calls && event.tool_calls.length > 0) {
        appendToolCall(event.tool_calls);
      }
      if (event.content) {
        appendMessage("message", event.role || "ai", event.content);
      }
    } else if (event.type === "crash") {
      appendNotice(`Crashed: ${event.error}`, "crash");
      setIsPaused(true);
      setIsRunning(false);
    } else if (event.type === "done") {
      setIsRunning(false);
    }
  };

  const handleSend = async () => {
    if (!input.trim() || isRunning) return;
    const task = input;
    setInput("");
    appendMessage("message", "human", task);
    setIsRunning(true);
    setIsPaused(false);

    const response = await fetch(`${API_BASE}/api/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ task, thread_id: threadId }),
    });

    await consumeStream(response, handleEvent);
    setIsRunning(false);
  };

  const handleResume = async () => {
    if (!threadId || isRunning) return;
    setIsRunning(true);
    setIsPaused(false);
    appendNotice("Resuming...", "resume");

    const response = await fetch(`${API_BASE}/api/resume`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ thread_id: threadId }),
    });

    await consumeStream(response, handleEvent);
    setIsRunning(false);
  };

  const handleCrashButton = async () => {
    if (isPaused) {
      await handleResume();
    } else {
      await fetch(`${API_BASE}/api/arm_crash`, { method: "POST" });
      appendNotice("Crash armed: next tool call will crash.", "crash");
    }
  };

  return (
    <div className="app-shell">
      <div className="chat-card">
        <div className="chat-header">
          <span className="chat-title">DeepAgent Chat</span>
          {threadId && <span className="thread-badge">thread: {threadId}</span>}
        </div>

        <div className="chat-messages" ref={scrollRef}>
          {messages.map((m, i) => {
            if (m.kind === "notice") {
              return (
                <div key={i} className={`notice notice-${m.variant}`}>
                  <span className="notice-icon">{ICONS[m.variant] || ICONS.info}</span>
                  {m.content}
                </div>
              );
            }
            if (m.kind === "tool-call") {
              return (
                <div key={i} className="tool-call-row">
                  <span className="notice-icon">{ICONS.tool}</span>
                  Calling tool(s):
                  {m.tools.map((t, j) => (
                    <span key={j} className="tool-chip">
                      {t}
                    </span>
                  ))}
                </div>
              );
            }
            return (
              <div key={i} className={`message message-${m.role}`}>
                <div className="message-icon">{roleIcon(m.role)}</div>
                <div className="message-body">
                  <div className="message-role">{roleLabel(m.role)}</div>
                  <div className="message-content">{m.content}</div>
                </div>
              </div>
            );
          })}

          {isRunning && <ThinkingIndicator />}
        </div>

        <div className="chat-input-row">
          <input
            className="chat-input"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSend()}
            placeholder="Type an instruction..."
            disabled={isRunning}
          />
          <button className="btn btn-send" onClick={handleSend} disabled={isRunning || isPaused}>
            Send
          </button>
          <button className={`btn btn-crash ${isPaused ? "btn-resume" : ""}`} onClick={handleCrashButton}>
            {isPaused ? "Resume" : "Simulate Crash"}
          </button>
        </div>
      </div>
    </div>
  );
}