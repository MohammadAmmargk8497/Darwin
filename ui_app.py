import streamlit as st
import subprocess
import threading
import queue
import time
import json
import os
import re
from pathlib import Path


def _reader_thread(pipe, q, tag: str = "stdout"):
    """Background thread that reads lines from a pipe into a queue.

    Each entry is a ``(tag, line)`` tuple so the consumer can distinguish
    structured stdout from raw stderr diagnostics.
    """
    try:
        for line in iter(pipe.readline, ""):
            q.put((tag, line))
    except Exception:
        pass
    finally:
        q.put((tag, None))  # sentinel

# Page configuration
st.set_page_config(
    page_title="Darwin Research Agent",
    page_icon="",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
    /* Clickable paper card */
    a.paper-card-link {
        text-decoration: none;
        display: block;
        margin: 10px 0;
    }
    .paper-card {
        background: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 12px;
        padding: 18px 22px;
        margin: 12px 0;
        box-shadow: 0 2px 12px rgba(0,0,0,0.10), 0 1px 3px rgba(0,0,0,0.07);
        transition: box-shadow 0.2s ease, transform 0.15s ease, border-color 0.2s ease;
        cursor: pointer;
        color: #1a1a1a;
    }
    a.paper-card-link:hover .paper-card {
        box-shadow: 0 8px 24px rgba(25, 118, 210, 0.18), 0 2px 6px rgba(0,0,0,0.08);
        transform: translateY(-3px);
        border-color: #1976d2;
    }
    .paper-meta {
        font-size: 0.76em;
        color: #64748b;
        font-family: monospace;
        margin-bottom: 7px;
    }
    .paper-title {
        font-size: 1.05em;
        font-weight: 700;
        color: #1976d2;
        line-height: 1.4;
        margin: 0 0 10px 0;
    }
    .paper-summary {
        color: #475569;
        font-size: 0.88em;
        line-height: 1.6;
        margin: 0 0 14px 0;
        display: -webkit-box;
        -webkit-line-clamp: 3;
        -webkit-box-orient: vertical;
        overflow: hidden;
    }
    .paper-links {
        display: flex;
        gap: 14px;
        font-size: 0.82em;
        font-weight: 600;
        color: #1976d2;
        border-top: 1px solid #f0f4f8;
        padding-top: 10px;
    }
    .paper-links span { opacity: 0.85; }
    .paper-links span:hover { opacity: 1; text-decoration: underline; }
    /* Keep old classes for backward compat */
    .agent-message { color: #1a1a1a; }
    .user-message  { color: #1a1a1a; }
    .tool-message  { color: #1a1a1a; }
</style>
""", unsafe_allow_html=True)

# Initialize session state
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "agent_process" not in st.session_state:
    st.session_state.agent_process = None
if "agent_ready" not in st.session_state:
    st.session_state.agent_ready = False
if "current_papers" not in st.session_state:
    st.session_state.current_papers = []
if "stdout_queue" not in st.session_state:
    st.session_state.stdout_queue = None
# Diagnostic log of startup warnings, stderr, and unrecognised stdout lines.
# Capped so long-running sessions don't balloon session state.
if "agent_log" not in st.session_state:
    st.session_state.agent_log = []
if "startup_warnings" not in st.session_state:
    st.session_state.startup_warnings = []


_AGENT_LOG_MAX = 300


def _append_log(kind: str, text: str) -> None:
    """Push a line onto the diagnostic log, trimming to ``_AGENT_LOG_MAX``."""
    st.session_state.agent_log.append((kind, text))
    if len(st.session_state.agent_log) > _AGENT_LOG_MAX:
        del st.session_state.agent_log[: len(st.session_state.agent_log) - _AGENT_LOG_MAX]

def start_agent():
    """Start the agent wrapper as a subprocess.

    Captures both stdout (structured protocol) and stderr (raw diagnostics,
    loguru output from MCP servers) so the UI can surface errors instead of
    silently hanging when, e.g., Ollama isn't running.
    """
    try:
        cwd = str(Path(__file__).parent)
        env = os.environ.copy()
        # Propagate DARWIN_CONFIG so the wrapper uses the same provider as the UI
        # e.g. DARWIN_CONFIG=config/agent_config_groq.json streamlit run ui_app.py
        process = subprocess.Popen(
            ["python", "agent_wrapper.py"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            cwd=cwd,
            env=env
        )

        # Two background readers — stdout for the structured protocol, stderr
        # for raw diagnostics. Both feed a single queue tagged by source.
        q: queue.Queue = queue.Queue()
        threading.Thread(
            target=_reader_thread, args=(process.stdout, q, "stdout"), daemon=True
        ).start()
        threading.Thread(
            target=_reader_thread, args=(process.stderr, q, "stderr"), daemon=True
        ).start()
        st.session_state.stdout_queue = q

        # Wait for AGENT_READY. Collect every other line into the diagnostic
        # log so startup warnings and stderr noise are visible to the user.
        deadline = time.time() + 30
        startup_warnings: list[str] = []
        while time.time() < deadline:
            try:
                tag, line = q.get(timeout=0.2)
            except queue.Empty:
                continue
            if line is None:
                # A reader closed its pipe — process has exited
                break
            line = line.rstrip()
            if not line:
                continue
            if tag == "stdout" and line.startswith("AGENT_READY"):
                st.session_state.agent_process = process
                st.session_state.agent_ready = True
                st.session_state.startup_warnings = startup_warnings
                return True
            if tag == "stdout" and line.startswith("STARTUP_WARNING:"):
                msg = line[len("STARTUP_WARNING:"):]
                startup_warnings.append(msg)
                _append_log("warning", msg)
            elif tag == "stdout" and line.startswith("ERROR:"):
                _append_log("error", line[len("ERROR:"):])
            else:
                _append_log(tag, line)

        # Hit the 30s deadline or process died before AGENT_READY
        rc = process.poll()
        if rc is not None:
            st.error(f"Agent process exited with code {rc} before becoming ready.")
        else:
            st.error("Agent failed to initialize within 30s.")
            process.terminate()
        if startup_warnings:
            st.info("Startup warnings captured — see sidebar 'Agent Log' for details.")
        return False
    except Exception as e:
        st.error(f"Failed to start agent: {str(e)}")
        return False

def extract_papers_from_response(text):
    """Extract paper data from agent response"""
    papers = []
    
    # Look for JSON-like structures in the response
    json_pattern = r'\{\s*"id":\s*"([^"]+)".*?"title":\s*"([^"]+)".*?"summary":\s*"([^"]+)".*?\}'
    matches = re.findall(json_pattern, text, re.DOTALL)
    
    for match in matches:
        papers.append({
            "id": match[0],
            "title": match[1][:100] + "..." if len(match[1]) > 100 else match[1],
            "summary": match[2][:200] + "..." if len(match[2]) > 200 else match[2]
        })
    
    return papers

def send_command_to_agent(command):
    """Send a command to the agent and collect its streamed reply.

    Returns ``(agent_text, papers, errors)`` so the caller can render each
    category distinctly — an error must NOT be smuggled inside the agent
    text (that's what caused the 'Processing...' hang on Ollama outages).
    """
    try:
        process = st.session_state.agent_process
        if not process or process.poll() is not None:
            return "", [], ["Agent process is not running — click 'Start Agent' in the sidebar."]

        process.stdin.write(command + "\n")
        process.stdin.flush()

        q = st.session_state.stdout_queue
        response_lines: list[tuple[str, str]] = []
        papers: list[dict] = []
        errors: list[str] = []
        timeout = 180
        start_time = time.time()

        while time.time() - start_time < timeout:
            try:
                tag, line = q.get(timeout=1.0)
            except queue.Empty:
                if process.poll() is not None:
                    errors.append(f"Agent process exited unexpectedly (code {process.returncode}).")
                    break
                continue
            if line is None:
                errors.append("Agent closed its output stream.")
                break

            line = line.rstrip()
            if not line:
                continue

            # stderr lines (loguru output from MCP servers, Python tracebacks)
            # go straight to the diagnostic log; never into the chat body.
            if tag == "stderr":
                _append_log("stderr", line)
                continue

            if line.startswith("AGENT_RESPONSE:"):
                content = line.replace("AGENT_RESPONSE:", "", 1)
                response_lines.append(("agent", content))
            elif line.startswith("PAPER_CARD:"):
                try:
                    paper = json.loads(line.replace("PAPER_CARD:", "", 1))
                    if "id" in paper and "title" in paper:
                        papers.append(paper)
                except Exception:
                    pass
            elif line.startswith("TOOL_EXECUTE:"):
                content = line.replace("TOOL_EXECUTE:", "", 1)
                response_lines.append(("tool", content))
                _append_log("tool", content)
            elif line.startswith("TOOL_ERROR:"):
                content = line.replace("TOOL_ERROR:", "", 1)
                errors.append(content)
                _append_log("error", content)
            elif line.startswith("TOOL_CONFIRM:"):
                # Auto-approve downloads from UI — send "yes" back to unblock agent
                process.stdin.write("yes\n")
                process.stdin.flush()
                response_lines.append(("tool", "Download approved"))
            elif line.startswith("TOOL_BLOCKED:"):
                content = line.replace("TOOL_BLOCKED:", "", 1)
                response_lines.append(("tool", f"Blocked: {content}"))
                _append_log("tool", f"blocked: {content}")
            elif line.startswith("ERROR:"):
                content = line.replace("ERROR:", "", 1)
                errors.append(content)
                _append_log("error", content)
                # keep reading until AGENT_END so we capture any trailing state
            elif line.startswith("STARTUP_WARNING:"):
                _append_log("warning", line[len("STARTUP_WARNING:"):])
            elif line.startswith("AGENT_END"):
                break
            elif line.startswith("AGENT_EXIT"):
                break
            else:
                # Unrecognised stdout — keep for debugging but don't surface in chat
                _append_log("stdout", line)

        if time.time() - start_time >= timeout:
            errors.append(f"Timed out after {timeout}s waiting for agent response.")

        final_response = "\n".join(
            content for role, content in response_lines
            if role == "agent" and content.strip()
        ).strip()

        return final_response, papers, errors

    except Exception as e:
        return "", [], [f"UI exception: {e}"]

# Header
st.markdown("# Darwin Research Agent")

# Sidebar
with st.sidebar:
    st.title("Agent Control")
    
    if not st.session_state.agent_ready:
        if st.button("🔌 Start Agent", use_container_width=True):
            with st.spinner("Starting agent..."):
                if start_agent():
                    st.success("Agent started!")
                    st.rerun()
    else:
        st.success("Agent Running")

        if st.button("Stop Agent", use_container_width=True):
            if st.session_state.agent_process:
                st.session_state.agent_process.terminate()
                st.session_state.agent_ready = False
            st.rerun()

    # Surface startup warnings (Ollama unreachable, model not pulled, etc.) at
    # the top of the sidebar so the user can't miss them.
    for w in st.session_state.startup_warnings:
        st.warning(w)
    
    st.divider()
    
    # Quick commands
    st.write("**Quick Commands:**")
    
    quick_commands = [
        ("Search Papers", "search papers on machine learning"),
        ("List Papers", "list papers"),
        ("Download Paper", "download paper 2306.04338v1"),
        ("Read Paper", "read paper 2306.04338v1"),
        ("Create Note", "create a research note about deep learning for Obsidian"),
    ]
    
    for label, cmd in quick_commands:
        if st.button(label, use_container_width=True, key=f"quick_{label}"):
            st.session_state.quick_cmd = cmd
    
    st.divider()
    
    with st.expander("Downloaded Papers"):
        papers_path = Path("papers")
        if papers_path.exists():
            papers = list(papers_path.glob("*.pdf"))
            if papers:
                for p in papers:
                    st.text(p.name)
                st.caption(f"Total: {len(papers)}")
            else:
                st.caption("No papers downloaded yet")

    with st.expander("Obsidian Notes"):
        notes_path = Path("Darwin Research/Research/Incoming")
        if notes_path.exists():
            notes = list(notes_path.glob("*.md"))
            if notes:
                for n in notes:
                    st.text(n.name)
                st.caption(f"Total: {len(notes)}")
            else:
                st.caption("No notes created yet")

    with st.expander(f"Agent Log ({len(st.session_state.agent_log)})"):
        if not st.session_state.agent_log:
            st.caption("No log entries yet.")
        else:
            # Render most recent last so scrolling follows the log naturally
            for kind, text in st.session_state.agent_log[-80:]:
                if kind == "error":
                    st.markdown(f":red[**error**] `{text}`")
                elif kind == "warning":
                    st.markdown(f":orange[**warn**] `{text}`")
                elif kind == "tool":
                    st.caption(f"tool · {text}")
                elif kind == "stderr":
                    st.caption(f"stderr · {text}")
                else:
                    st.caption(text)
        if st.button("Clear log", use_container_width=True, key="clear_log"):
            st.session_state.agent_log = []
            st.rerun()

# Increment this key to clear the text_input after each submission
if "input_key" not in st.session_state:
    st.session_state.input_key = 0

# Main chat area
if not st.session_state.agent_ready:
    st.info("Click **'Start Agent'** in the sidebar to begin")
else:
    # ── Input at the top ──────────────────────────────────────────────────────
    col1, col2 = st.columns([5, 1])
    with col1:
        if "quick_cmd" in st.session_state:
            user_input = st.session_state.quick_cmd
            st.session_state.quick_cmd = None
            should_send = True
        else:
            user_input = st.text_input(
                "Type your command:",
                placeholder="search papers on..., download paper..., read paper..., list papers, create note...",
                key=f"user_input_{st.session_state.input_key}",
                label_visibility="collapsed",
            )
            should_send = False
    with col2:
        send_button = st.button("Send", use_container_width=True)

    if (send_button or should_send) and user_input:
        st.session_state.chat_history.append({"role": "user", "content": user_input})
        with st.spinner("Thinking..."):
            response, papers, errors = send_command_to_agent(user_input)
            st.session_state.chat_history.append({
                "role": "agent",
                "content": response,
                "papers": papers,
                "errors": errors,
            })
        # Increment key → text_input renders fresh and empty on next run
        st.session_state.input_key += 1
        st.rerun()

    st.divider()

    # ── Chat history ──────────────────────────────────────────────────────────
    for msg in st.session_state.chat_history:
        if msg["role"] == "user":
            with st.chat_message("user"):
                st.markdown(msg['content'])
        elif msg["role"] == "agent":
            with st.chat_message("assistant"):
                if msg.get("papers"):
                    # When cards are shown, only display the agent's intro sentence —
                    # not the full formatted paper list which would duplicate the cards.
                    lines = [l for l in msg['content'].splitlines() if l.strip()]
                    intro = next(
                        (l for l in lines if not l.startswith("#") and not l.startswith("**") and not l.startswith("-")),
                        ""
                    )
                    if intro:
                        st.markdown(intro)

                    st.markdown(f"#### {len(msg['papers'])} Papers Found")
                    for paper in msg["papers"]:
                        arxiv_url = paper.get("arxiv_url", "")
                        pdf_url   = paper.get("pdf_url", "")
                        meta = " · ".join(filter(None, [
                            paper.get("id", ""),
                            paper.get("published", ""),
                            paper.get("authors", ""),
                        ]))
                        # Use proper <a> tags — no nested anchors so Abstract goes to
                        # the abstract page and PDF goes to the actual PDF file.
                        abstract_link = f'<a href="{arxiv_url}" target="_blank">Abstract</a>' if arxiv_url else ""
                        pdf_link      = f'<a href="{pdf_url}"   target="_blank">PDF</a>'      if pdf_url   else ""
                        links_html    = "&nbsp;&nbsp;|&nbsp;&nbsp;".join(filter(None, [abstract_link, pdf_link]))
                        st.markdown(f"""
                        <div class="paper-card">
                            <div class="paper-meta">{meta}</div>
                            <div class="paper-title">
                                <a href="{arxiv_url or '#'}" target="_blank" style="color:inherit;text-decoration:none;">
                                    {paper.get("title", "")}
                                </a>
                            </div>
                            <div class="paper-summary">{paper.get("summary", "")}</div>
                            <div class="paper-links">{links_html}</div>
                        </div>
                        """, unsafe_allow_html=True)
                else:
                    if msg['content']:
                        st.markdown(msg['content'])
                    elif not msg.get("errors"):
                        st.info("(no response)")

                for err in msg.get("errors", []) or []:
                    st.error(err)
        elif msg["role"] == "error":
            st.error(msg['content'])

# Footer
st.divider()
st.markdown("""
### Available Commands

**Search & Browse:**
- `search papers on machine learning` - Find papers on a topic
- `list papers` - Show downloaded papers

**Download & Read:**
- `download paper 2306.04338v1` - Download by ID
- `download paper 2306.04338v1 without approval` - Auto-download
- `read paper 2306.04338v1` - Extract and read paper text

**Create Notes:**
- `create a research note about AI for Obsidian`
- `create a research note for paper 2306.04338v1 about deep learning for Obsidian`
""")
st.markdown("**Darwin Research Agent** | Powered by ArXiv, Ollama, and MCP | Built with Streamlit")
