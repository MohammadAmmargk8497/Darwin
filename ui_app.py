import streamlit as st
import subprocess
import time
import json
import os
import re
from pathlib import Path

# ─── Page Config ───
st.set_page_config(
    page_title="Darwin - Research Agent",
    page_icon="🧬",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ─── Custom CSS ───
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
header {visibility: hidden;}

.block-container {
    padding-top: 1rem;
    padding-bottom: 0rem;
    max-width: 1100px;
}

/* Hero */
.hero {
    background: linear-gradient(135deg, #0f172a 0%, #1e293b 50%, #334155 100%);
    border-radius: 16px;
    padding: 24px 32px;
    margin-bottom: 20px;
    display: flex;
    align-items: center;
    gap: 18px;
    box-shadow: 0 4px 20px rgba(0,0,0,0.15);
    border: 1px solid rgba(255,255,255,0.05);
}
.hero-icon { font-size: 2.5rem; }
.hero-title { font-size: 1.8rem; font-weight: 700; color: #f1f5f9; margin: 0; }
.hero-sub { font-size: 0.9rem; color: #94a3b8; margin: 2px 0 0 0; }
.hero-status {
    margin-left: auto;
    padding: 5px 14px;
    border-radius: 20px;
    font-size: 0.8rem;
    font-weight: 500;
}
.status-on { background: rgba(34,197,94,0.12); border: 1px solid rgba(34,197,94,0.35); color: #4ade80; }
.status-off { background: rgba(239,68,68,0.12); border: 1px solid rgba(239,68,68,0.35); color: #f87171; }

/* Sidebar card */
.stat-card {
    background: #1e293b;
    border: 1px solid #334155;
    border-radius: 10px;
    padding: 14px;
    margin: 6px 0;
}
.stat-row {
    display: flex; justify-content: space-between; align-items: center;
    padding: 5px 0; border-bottom: 1px solid #2d3a4d;
}
.stat-row:last-child { border-bottom: none; }
.stat-label { color: #94a3b8; font-size: 0.85rem; }
.stat-val { color: #f1f5f9; font-weight: 600; }

/* Welcome */
.welcome {
    text-align: center; padding: 50px 20px;
    background: #1e293b; border: 1px solid #334155;
    border-radius: 16px; margin: 30px 0;
}
.welcome h2 { color: #f1f5f9; margin: 10px 0 6px 0; }
.welcome p { color: #94a3b8; max-width: 480px; margin: 0 auto; line-height: 1.6; }
.chips { display: flex; flex-wrap: wrap; gap: 8px; justify-content: center; margin-top: 18px; }
.chip {
    background: rgba(99,102,241,0.1); border: 1px solid rgba(99,102,241,0.3);
    border-radius: 18px; padding: 5px 14px; color: #a5b4fc; font-size: 0.8rem;
}

/* Footer */
.foot { text-align: center; color: #475569; font-size: 0.75rem; padding: 16px 0; margin-top: 20px; border-top: 1px solid #1e293b; }
</style>
""", unsafe_allow_html=True)


# ─── Session State ───
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "agent_process" not in st.session_state:
    st.session_state.agent_process = None
if "agent_ready" not in st.session_state:
    st.session_state.agent_ready = False


# ─── Agent Functions ───
def start_agent():
    try:
        cwd = str(Path(__file__).parent)
        env = os.environ.copy()
        process = subprocess.Popen(
            ["python", "agent_wrapper.py"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1, cwd=cwd, env=env
        )
        for _ in range(80):
            line = process.stdout.readline()
            if "AGENT_READY" in line:
                st.session_state.agent_process = process
                st.session_state.agent_ready = True
                return True
            time.sleep(0.1)
        st.error("Agent failed to initialize")
        return False
    except Exception as e:
        st.error(f"Failed to start agent: {str(e)}")
        return False


def extract_papers(text):
    """Extract papers from numbered list format."""
    papers = []
    pattern = r'(\d+)\.\s+\[([^\]]+)\]\s+(.+?)\s+\((\d{4}-\d{2}-\d{2})\)\s*\n\s+(.+?)(?=\n\d+\.|$)'
    for m in re.finditer(pattern, text, re.DOTALL):
        papers.append({
            "id": m.group(2).strip(),
            "title": m.group(3).strip(),
            "date": m.group(4).strip(),
            "summary": m.group(5).strip()
        })
    return papers


def clean_response(text, has_papers):
    """Remove raw tool output and paper listings when cards are shown."""
    if not has_papers:
        return text
    # Remove tool prefix
    text = re.sub(r'search_papers:\[.*?\n', '', text, count=1)
    # Remove "Found N papers:" line
    text = re.sub(r'Found \d+ papers?:\s*\n?', '', text)
    # Remove numbered paper entries
    text = re.sub(r'\d+\.\s+\[[^\]]+\]\s+.+?\(\d{4}-\d{2}-\d{2}\)\s*\n\s+.+?(?=\n\d+\.|\n[A-Z]|$)', '', text, flags=re.DOTALL)
    return text.strip()


def send_command(command):
    try:
        process = st.session_state.agent_process
        if not process or process.poll() is not None:
            return "Error: Agent not running. Please restart.", []

        process.stdin.write(command + "\n")
        process.stdin.flush()

        lines = []
        start = time.time()
        while time.time() - start < 180:
            line = process.stdout.readline()
            if not line:
                time.sleep(0.05)
                continue
            line = line.rstrip()
            if line.startswith("AGENT_RESPONSE:"):
                lines.append(("agent", line.replace("AGENT_RESPONSE:", "", 1)))
            elif line.startswith("TOOL_EXECUTE:"):
                lines.append(("tool", line.replace("TOOL_EXECUTE:", "", 1)))
            elif line.startswith("TOOL_ERROR:"):
                lines.append(("error", line.replace("TOOL_ERROR:", "", 1)))
            elif line.startswith("TOOL_CONFIRM:"):
                process.stdin.write("yes\n")
                process.stdin.flush()
                lines.append(("tool", "Download approved"))
            elif line.startswith("TOOL_BLOCKED:"):
                lines.append(("tool", "Blocked: " + line.replace("TOOL_BLOCKED:", "", 1)))
            elif line.startswith("ERROR:"):
                lines.append(("error", line.replace("ERROR:", "", 1)))
                break
            elif "AGENT_END" in line or "AGENT_EXIT" in line:
                break

        response = "\n".join(c for _, c in lines if c.strip())
        papers = extract_papers(response)
        return response if response else "Done.", papers
    except Exception as e:
        return f"Error: {str(e)}", []


def render_paper_cards(papers):
    """Render paper cards using st.html component."""
    cards_html = ""
    for p in papers:
        cards_html += f"""
        <div style="
            background: linear-gradient(135deg, #1e293b, #0f172a);
            border: 1px solid #334155;
            border-radius: 12px;
            padding: 18px 22px;
            margin: 10px 0;
            font-family: 'Inter', sans-serif;
            transition: border-color 0.2s;
        ">
            <div style="display:flex; align-items:center; gap:10px; margin-bottom:8px;">
                <span style="
                    font-family: 'JetBrains Mono', monospace;
                    font-size: 0.78rem; color: #818cf8;
                    background: rgba(99,102,241,0.12);
                    padding: 3px 10px; border-radius: 6px;
                ">{p.get('id','')}</span>
                <span style="font-size:0.78rem; color:#64748b;">
                    {p.get('date','')}
                </span>
            </div>
            <div style="font-size:0.98rem; font-weight:600; color:#f1f5f9; line-height:1.4; margin-bottom:8px;">
                {p.get('title','Untitled')}
            </div>
            <div style="font-size:0.84rem; color:#94a3b8; line-height:1.55;">
                {p.get('summary','')}
            </div>
        </div>
        """

    full_html = f"""
    <div style="max-width:100%;">
        <div style="
            font-size:0.85rem; color:#94a3b8; font-weight:500;
            margin-bottom:8px; padding-left:4px;
        ">
            Found {len(papers)} paper{'s' if len(papers)!=1 else ''}
        </div>
        {cards_html}
    </div>
    """
    st.html(full_html)


# ─── Header ───
status_cls = "status-on" if st.session_state.agent_ready else "status-off"
status_txt = "Online" if st.session_state.agent_ready else "Offline"
st.markdown(f"""
<div class="hero">
    <div class="hero-icon">&#129516;</div>
    <div>
        <div class="hero-title">Darwin</div>
        <div class="hero-sub">AI Research Agent &mdash; Search, Download &amp; Organize Papers</div>
    </div>
    <div class="hero-status {status_cls}">&#9679; {status_txt}</div>
</div>
""", unsafe_allow_html=True)


# ─── Sidebar ───
with st.sidebar:
    st.markdown("### Control Panel")

    if not st.session_state.agent_ready:
        if st.button("Start Agent", use_container_width=True):
            with st.spinner("Initializing Darwin..."):
                if start_agent():
                    st.rerun()
    else:
        c1, c2 = st.columns(2)
        with c1:
            if st.button("Restart", use_container_width=True):
                if st.session_state.agent_process:
                    st.session_state.agent_process.terminate()
                    st.session_state.agent_ready = False
                    time.sleep(0.5)
                with st.spinner("Restarting..."):
                    if start_agent():
                        st.rerun()
        with c2:
            if st.button("Stop", use_container_width=True):
                if st.session_state.agent_process:
                    st.session_state.agent_process.terminate()
                    st.session_state.agent_ready = False
                    st.session_state.agent_process = None
                st.rerun()

    st.markdown("---")

    # Stats
    papers_dir = Path("papers")
    pdf_count = len(list(papers_dir.glob("*.pdf"))) if papers_dir.exists() else 0
    notes_dir = Path("Darwin Research/Research/Incoming")
    notes_count = len(list(notes_dir.glob("*.md"))) if notes_dir.exists() else 0

    st.markdown(f"""
    <div class="stat-card">
        <div class="stat-row"><span class="stat-label">Papers</span><span class="stat-val">{pdf_count}</span></div>
        <div class="stat-row"><span class="stat-label">Notes</span><span class="stat-val">{notes_count}</span></div>
        <div class="stat-row"><span class="stat-label">Messages</span><span class="stat-val">{len(st.session_state.chat_history)}</span></div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("##### Quick Actions")

    if st.button("Search Papers", use_container_width=True):
        st.session_state.quick_cmd = "search papers on machine learning"
    if st.button("List Downloads", use_container_width=True):
        st.session_state.quick_cmd = "list papers"
    if st.button("Create Note", use_container_width=True):
        st.session_state.quick_cmd = "create a research note about deep learning for Obsidian"

    st.markdown("---")

    with st.expander("Downloaded Papers"):
        if papers_dir.exists():
            pl = sorted(papers_dir.glob("*.pdf"))
            for p in pl:
                st.caption(f"  {p.stem}")
            if not pl:
                st.caption("No papers yet")

    with st.expander("Research Notes"):
        if notes_dir.exists():
            nl = sorted(notes_dir.glob("*.md"))
            for n in nl:
                st.caption(f"  {n.stem}")
            if not nl:
                st.caption("No notes yet")

    st.markdown("---")
    if st.button("Clear Chat", use_container_width=True):
        st.session_state.chat_history = []
        st.rerun()


# ─── Main Area ───
if not st.session_state.agent_ready:
    st.markdown("""
    <div class="welcome">
        <div style="font-size:3rem;">&#129516;</div>
        <h2>Welcome to Darwin</h2>
        <p>Your AI research assistant for discovering, downloading, and organizing
        academic papers from arXiv. Start the agent from the sidebar to begin.</p>
        <div class="chips">
            <span class="chip">search papers on transformers</span>
            <span class="chip">download paper</span>
            <span class="chip">read paper</span>
            <span class="chip">create note</span>
            <span class="chip">list papers</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

else:
    # ─── Chat Display ───
    for msg in st.session_state.chat_history:
        if msg["role"] == "user":
            with st.chat_message("user", avatar="👤"):
                st.markdown(msg["content"])

        elif msg["role"] == "agent":
            with st.chat_message("assistant", avatar="🧬"):
                papers = msg.get("papers", [])
                display = clean_response(msg["content"], bool(papers))

                if display:
                    st.markdown(display)

                if papers:
                    render_paper_cards(papers)

        elif msg["role"] == "error":
            with st.chat_message("assistant", avatar="⚠️"):
                st.error(msg["content"])

    # ─── Input ───
    if "quick_cmd" in st.session_state and st.session_state.quick_cmd:
        user_input = st.session_state.quick_cmd
        st.session_state.quick_cmd = None
        should_send = True
    else:
        user_input = st.chat_input("Message Darwin... (search, download, read, create note)")
        should_send = bool(user_input)

    if should_send and user_input:
        st.session_state.chat_history.append({"role": "user", "content": user_input})

        with st.chat_message("user", avatar="👤"):
            st.markdown(user_input)

        with st.chat_message("assistant", avatar="🧬"):
            with st.spinner("Darwin is thinking..."):
                response, papers = send_command(user_input)

            display = clean_response(response, bool(papers))
            if display:
                st.markdown(display)
            if papers:
                render_paper_cards(papers)

        st.session_state.chat_history.append({
            "role": "agent",
            "content": response,
            "papers": papers
        })
        st.rerun()


# ─── Footer ───
st.markdown("""
<div class="foot">
    <strong>Darwin Research Agent</strong> &bull;
    Powered by ArXiv, Ollama &amp; MCP &bull;
    Built with Streamlit
</div>
""", unsafe_allow_html=True)
