import streamlit as st
import subprocess
import threading
import queue
import time
import json
import os
import re
from pathlib import Path


def _reader_thread(pipe, q):
    """Background thread that reads lines from a pipe into a queue."""
    try:
        for line in iter(pipe.readline, ""):
            q.put(line)
    except Exception:
        pass
    finally:
        q.put(None)  # sentinel

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

def start_agent():
    """Start the agent wrapper as a subprocess"""
    try:
        cwd = str(Path(__file__).parent)
        env = os.environ.copy()
        # Propagate DARWIN_CONFIG so the wrapper uses the same provider as the UI
        # e.g. DARWIN_CONFIG=config/agent_config_groq.json streamlit run ui_app.py
        process = subprocess.Popen(
            ["python", "agent_wrapper.py"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
            cwd=cwd,
            env=env
        )

        # Start a background reader so readline() never blocks the UI
        q = queue.Queue()
        t = threading.Thread(target=_reader_thread, args=(process.stdout, q), daemon=True)
        t.start()
        st.session_state.stdout_queue = q

        # Wait for agent to be ready (MCP servers may take a few seconds to start)
        deadline = time.time() + 30  # 30s should be plenty
        while time.time() < deadline:
            try:
                line = q.get(timeout=0.2)
            except queue.Empty:
                continue
            if line is None:
                break
            if "AGENT_READY" in line:
                st.session_state.agent_process = process
                st.session_state.agent_ready = True
                return True
        
        st.error("Agent failed to initialize")
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
    """Send a command to the agent and get the response"""
    try:
        process = st.session_state.agent_process
        if not process or process.poll() is not None:
            return "Error: Agent process not running", []
        
        # Send command
        process.stdin.write(command + "\n")
        process.stdin.flush()

        # Read response via the non-blocking queue
        q = st.session_state.stdout_queue
        response_lines = []
        papers = []
        timeout = 180
        start_time = time.time()

        while time.time() - start_time < timeout:
            try:
                line = q.get(timeout=1.0)
            except queue.Empty:
                continue
            if line is None:
                break

            line = line.rstrip()
            
            # Parse structured output
            if line.startswith("AGENT_RESPONSE:"):
                content = line.replace("AGENT_RESPONSE:", "", 1)
                response_lines.append(("agent", content))
            elif line.startswith("PAPER_CARD:"):
                # Structured paper data sent by agent_wrapper — render as UI cards
                try:
                    paper = json.loads(line.replace("PAPER_CARD:", "", 1))
                    if "id" in paper and "title" in paper:
                        papers.append(paper)
                except Exception:
                    pass
            elif line.startswith("TOOL_EXECUTE:"):
                content = line.replace("TOOL_EXECUTE:", "", 1)
                response_lines.append(("tool", content))
            elif line.startswith("TOOL_ERROR:"):
                content = line.replace("TOOL_ERROR:", "", 1)
                response_lines.append(("error", f"Error: {content}"))
            elif line.startswith("TOOL_CONFIRM:"):
                # Auto-approve downloads from UI — send "yes" back to unblock agent
                process.stdin.write("yes\n")
                process.stdin.flush()
                response_lines.append(("tool", "Download approved"))
            elif line.startswith("TOOL_BLOCKED:"):
                content = line.replace("TOOL_BLOCKED:", "", 1)
                response_lines.append(("tool", f"Blocked: {content}"))
            elif line.startswith("ERROR:"):
                content = line.replace("ERROR:", "", 1)
                response_lines.append(("error", f"Error: {content}"))
                break
            elif line.startswith("AGENT_END"):
                break  # Agent finished processing this command
            elif line.startswith("AGENT_EXIT"):
                break

        # Only include the LLM's actual reply — tool activity stays out of the
        # response text so it doesn't look like command-line output.
        final_response = "\n".join(
            content for role, content in response_lines
            if role == "agent" and content.strip()
        )

        return final_response.strip() if final_response.strip() else "Processing...", papers
    
    except Exception as e:
        return f"Error: {str(e)}", []

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
            response, papers = send_command_to_agent(user_input)
            st.session_state.chat_history.append({
                "role": "agent",
                "content": response,
                "papers": papers,
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
                    # Non-search responses: render the full LLM reply as markdown
                    st.markdown(msg['content'])
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
