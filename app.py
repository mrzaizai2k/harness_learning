"""
Streamlit UI for DeepAgentRunner.

Run with:
    streamlit run app.py

Requires an OPENAI_API_KEY (in a .env file or the environment).

NOTE on the "crash" button:
Streamlit runs your script synchronously on each interaction — it can't
reach in and interrupt a call that's already in progress. So instead of
crashing mid-execution, you ARM the crash flag first (checkbox in the
sidebar), then press Run/Resume; the very next tool call the agent makes
will raise an exception, the checkpoint is saved right before it, and
you can then hit Resume to continue from exactly that point.
"""

import streamlit as st

from agent_runner import DeepAgentRunner

st.set_page_config(page_title="Deep Agent — Crash & Resume Demo", layout="wide")
st.title("🕵️ Deep Agent — Crash & Resume Demo")

# ---------------------------------------------------------------- session
if "runner" not in st.session_state:
    st.session_state.runner = DeepAgentRunner()
if "thread_id" not in st.session_state:
    st.session_state.thread_id = None
if "log" not in st.session_state:
    st.session_state.log = []
if "crashed" not in st.session_state:
    st.session_state.crashed = False

runner: DeepAgentRunner = st.session_state.runner


def log(msg: str):
    st.session_state.log.append(msg)


def render_event(event: dict):
    """Turn one stream event into a human-readable log line."""
    if event["type"] == "crash":
        log(f"💥 CRASHED: {event['error']}")
        return
    msgs = event["data"].get("messages", [])
    if not msgs:
        return
    last = msgs[-1]
    if getattr(last, "tool_calls", None):
        names = [tc["name"] for tc in last.tool_calls]
        log(f"🤖 requests tool call(s): {names}")
    elif getattr(last, "type", "") == "tool":
        log(f"🔧 tool '{last.name}' returned: {str(last.content)[:150]!r}")
    elif getattr(last, "type", "") == "ai":
        log(f"🤖 AI: {str(last.content)[:250]!r}")


# ---------------------------------------------------------------- sidebar
with st.sidebar:
    st.header("Controls")

    task = st.text_area(
        "Task for the agent",
        height=110,
        placeholder="1. List files.\n2. Read README.md.\n3. Count the words in it.",
    )

    arm_crash = st.checkbox(
        "💣 Arm crash (next tool call will raise an exception)",
        help="Arm this BEFORE pressing Run/Resume to simulate a crash "
        "at the very next tool call.",
    )

    col1, col2 = st.columns(2)
    run_clicked = col1.button("▶️ Run new task", use_container_width=True)
    resume_clicked = col2.button(
        "⏯️ Resume",
        use_container_width=True,
        disabled=st.session_state.thread_id is None,
    )

    if st.button("🗑️ Reset session", use_container_width=True):
        st.session_state.thread_id = None
        st.session_state.log = []
        st.session_state.crashed = False
        st.rerun()

    if st.session_state.thread_id:
        st.divider()
        st.caption(f"thread_id: `{st.session_state.thread_id}`")
        st.caption("⏸️ paused, ready to resume" if st.session_state.crashed else "idle / finished")

# ---------------------------------------------------------------- layout
# Placeholders are created BEFORE we run anything, so we can push updates
# into them on every single streamed event (true live streaming) instead
# of only rendering after the whole loop finishes.
left, right = st.columns([2, 1])

with left:
    st.subheader("Process log")
    log_placeholder = st.empty()

with right:
    st.subheader("Checkpoint history")
    history_placeholder = st.empty()


def render_log():
    with log_placeholder.container():
        if st.session_state.log:
            # st.code doesn't wrap long lines (horizontal scroll instead),
            # so use markdown with CSS white-space: pre-wrap to force wrap.
            log_text = "\n".join(st.session_state.log).replace("\n", "  \n")
            st.markdown(
                f'<div style="white-space: pre-wrap; word-wrap: break-word; '
                f'font-family: monospace; font-size: 0.85rem; '
                f'background-color: rgba(128,128,128,0.1); padding: 0.75rem; '
                f'border-radius: 0.5rem;">{log_text}</div>',
                unsafe_allow_html=True,
            )
        else:
            st.info("Enter a task in the sidebar and click **Run new task**.")


def render_history():
    with history_placeholder.container():
        if st.session_state.thread_id:
            for h in runner.get_history(st.session_state.thread_id):
                st.text(f"step {h['step']:>2} | next={h['next']:<15}\n{h['summary']}")
                st.divider()
        else:
            st.caption("No thread yet.")


def stream_and_render(event_generator):
    """Consume a stream_run/stream_resume generator, updating the log
    placeholder after EVERY event so the UI actually streams live."""
    for event in event_generator:
        render_event(event)
        render_log()  # <- pushed on every event, not just at the end
        if event["type"] == "crash":
            st.session_state.crashed = True


# ---------------------------------------------------------------- actions
if run_clicked:
    if not task.strip():
        st.warning("Type a task first.")
    else:
        st.session_state.thread_id = runner.new_thread_id()
        st.session_state.log = [f"🚀 starting new task on thread `{st.session_state.thread_id}`"]
        st.session_state.crashed = False

        if arm_crash:
            runner.arm_crash()
            log("💣 crash armed for next tool call")

        stream_and_render(runner.stream_run(task, st.session_state.thread_id))

if resume_clicked and st.session_state.thread_id:
    log(f"▶️ resuming thread `{st.session_state.thread_id}`")
    st.session_state.crashed = False

    if arm_crash:
        runner.arm_crash()
        log("💣 crash armed for next tool call")

    stream_and_render(runner.stream_resume(st.session_state.thread_id))

# Always render current state (covers first load / after reset / after run)
render_log()
render_history()