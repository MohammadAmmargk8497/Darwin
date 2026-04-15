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

/* ── Paper Cards ── */
.paper-card {
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 12px;
    padding: 18px 22px;
    margin: 12px 0;
    box-shadow: 0 2px 12px rgba(0,0,0,0.08), 0 1px 3px rgba(0,0,0,0.05);
    transition: box-shadow 0.2s ease, transform 0.15s ease, border-color 0.2s ease;
    color: #1a1a1a;
}
.paper-card:hover {
    box-shadow: 0 8px 24px rgba(25, 118, 210, 0.15), 0 2px 6px rgba(0,0,0,0.06);
    transform: translateY(-2px);
    border-color: #1976d2;
}
.paper-meta {
    font-size: 0.76em;
    color: #64748b;
    font-family: 'JetBrains Mono', monospace;
    margin-bottom: 7px;
}
.paper-title {
    font-size: 1.05em;
    font-weight: 700;
    color: #1976d2;
    line-height: 1.4;
    margin: 0 0 10px 0;
}
.paper-title a {
    color: inherit;
    text-decoration: none;
}
.paper-title a:hover {
    text-decoration: underline;
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
    border-top: 1px solid #f0f4f8;
    padding-top: 10px;
}
.paper-links a {
    color: #1976d2;
    text-decoration: none;
}
.paper-links a:hover {
    text-decoration: underline;
}

/* ── Sidebar Stats ── */
.stat-card {
    background: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 10px;
    padding: 14px;
    margin: 6px 0;
}
.stat-row {
    display: flex; justify-content: space-between; align-items: center;
    padding: 5px 0; border-bottom: 1px solid #f0f4f8;
}
.stat-row:last-child { border-bottom: none; }
.stat-label { color: #64748b; font-size: 0.85rem; }
.stat-val { color: #1e293b; font-weight: 600; }

/* ── Footer ── */
.foot {
    text-align: center; color: #94a3b8; font-size: 0.78rem;
    padding: 16px 0; margin-top: 20px; border-top: 1px solid #e2e8f0;
}
</style>
""", unsafe_allow_html=True)


# ─── Session State ───
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "agent_process" not in st.session_state:
    st.session_state.agent_process = None
if "agent_ready" not in st.session_state:
    st.session_state.agent_ready = False
if "input_key" not in st.session_state:
    st.session_state.input_key = 0


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
        paper_id = m.group(2).strip()
        base_id = paper_id.split("v")[0]
        papers.append({
            "id": paper_id,
            "title": m.group(3).strip(),
            "published": m.group(4).strip(),
            "summary": m.group(5).strip(),
            "arxiv_url": f"https://arxiv.org/abs/{base_id}",
            "pdf_url": f"https://arxiv.org/pdf/{base_id}",
        })
    return papers


def send_command(command):
    try:
        process = st.session_state.agent_process
        if not process or process.poll() is not None:
            return "Error: Agent not running. Please restart.", []

        process.stdin.write(command + "\n")
        process.stdin.flush()

        lines = []
        papers = []
        start = time.time()
        while time.time() - start < 180:
            line = process.stdout.readline()
            if not line:
                time.sleep(0.05)
                continue
            line = line.rstrip()
            if line.startswith("AGENT_RESPONSE:"):
                lines.append(("agent", line.replace("AGENT_RESPONSE:", "", 1)))
            elif line.startswith("PAPER_CARD:"):
                try:
                    paper = json.loads(line.replace("PAPER_CARD:", "", 1))
                    if "id" in paper and "title" in paper:
                        papers.append(paper)
                except Exception:
                    pass
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

        # Build response — only agent lines for display
        response = "\n".join(c for role, c in lines if role == "agent" and c.strip())

        # Extract papers from numbered list if no PAPER_CARD data
        if not papers:
            full_text = "\n".join(c for _, c in lines if c.strip())
            papers = extract_papers(full_text)

        return response if response else "Done.", papers
    except Exception as e:
        return f"Error: {str(e)}", []


def render_paper_cards(papers):
    """Render paper cards with clickable links."""
    st.markdown(f"#### 📄 {len(papers)} Papers Found")
    for paper in papers:
        arxiv_url = paper.get("arxiv_url", "")
        pdf_url = paper.get("pdf_url", "")
        meta_parts = [
            paper.get("id", ""),
            paper.get("published", ""),
            paper.get("authors", ""),
        ]
        meta = " · ".join(p for p in meta_parts if p)

        links = []
        if arxiv_url:
            links.append(f'<a href="{arxiv_url}" target="_blank">Abstract</a>')
        if pdf_url:
            links.append(f'<a href="{pdf_url}" target="_blank">PDF</a>')
        links_html = "&nbsp;&nbsp;|&nbsp;&nbsp;".join(links)

        title_html = paper.get("title", "Untitled")
        if arxiv_url:
            title_html = f'<a href="{arxiv_url}" target="_blank">{title_html}</a>'

        st.markdown(f"""
        <div class="paper-card">
            <div class="paper-meta">{meta}</div>
            <div class="paper-title">{title_html}</div>
            <div class="paper-summary">{paper.get("summary", "")}</div>
            <div class="paper-links">{links_html}</div>
        </div>
        """, unsafe_allow_html=True)


# ─── Header ───
st.markdown("# 🧬 Darwin Research Agent")


# ─── Sidebar ───
with st.sidebar:
    st.markdown("### ⚙️ Agent Control")

    if not st.session_state.agent_ready:
        if st.button("🔌 Start Agent", use_container_width=True):
            with st.spinner("Starting agent..."):
                if start_agent():
                    st.success("Agent started!")
                    st.rerun()
    else:
        st.success("✅ Agent Running")
        c1, c2 = st.columns(2)
        with c1:
            if st.button("🔄 Restart", use_container_width=True):
                if st.session_state.agent_process:
                    st.session_state.agent_process.terminate()
                    st.session_state.agent_ready = False
                    time.sleep(0.5)
                with st.spinner("Restarting..."):
                    if start_agent():
                        st.rerun()
        with c2:
            if st.button("🛑 Stop", use_container_width=True):
                if st.session_state.agent_process:
                    st.session_state.agent_process.terminate()
                    st.session_state.agent_ready = False
                    st.session_state.agent_process = None
                st.rerun()

    st.divider()

    # Stats
    papers_dir = Path("papers")
    pdf_count = len(list(papers_dir.glob("*.pdf"))) if papers_dir.exists() else 0
    notes_dir = Path("Darwin Research/Research/Incoming")
    notes_count = len(list(notes_dir.glob("*.md"))) if notes_dir.exists() else 0

    st.markdown(f"""
    <div class="stat-card">
        <div class="stat-row"><span class="stat-label">📄 Papers</span><span class="stat-val">{pdf_count}</span></div>
        <div class="stat-row"><span class="stat-label">📝 Notes</span><span class="stat-val">{notes_count}</span></div>
        <div class="stat-row"><span class="stat-label">💬 Messages</span><span class="stat-val">{len(st.session_state.chat_history)}</span></div>
    </div>
    """, unsafe_allow_html=True)

    st.divider()

    # Quick commands
    st.markdown("**Quick Commands:**")
    quick_commands = [
        ("🔍 Search Papers", "search papers on machine learning"),
        ("📋 List Papers", "list papers"),
        ("📥 Download Paper", "download paper 2306.04338v1"),
        ("📖 Read Paper", "read paper 2306.04338v1"),
        ("📝 Create Note", "create a research note about deep learning for Obsidian"),
    ]
    for label, cmd in quick_commands:
        if st.button(label, use_container_width=True, key=f"quick_{label}"):
            st.session_state.quick_cmd = cmd

    st.divider()

    with st.expander("📋 Downloaded Papers"):
        if papers_dir.exists():
            pl = sorted(papers_dir.glob("*.pdf"))
            for p in pl:
                st.text(f"📄 {p.name}")
            if not pl:
                st.caption("No papers downloaded yet")

    with st.expander("📚 Obsidian Notes"):
        if notes_dir.exists():
            nl = sorted(notes_dir.glob("*.md"))
            for n in nl:
                st.text(f"📝 {n.name}")
            if not nl:
                st.caption("No notes created yet")

    st.divider()
    if st.button("🗑️ Clear Chat", use_container_width=True):
        st.session_state.chat_history = []
        st.rerun()


# ─── Main Area ───
if not st.session_state.agent_ready:
    st.info("👈 Click **'Start Agent'** in the sidebar to begin")
else:
    # Input at the top
    col1, col2 = st.columns([5, 1])
    with col1:
        if "quick_cmd" in st.session_state and st.session_state.quick_cmd:
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
        send_button = st.button("📤 Send", use_container_width=True)

    if (send_button or should_send) and user_input:
        st.session_state.chat_history.append({"role": "user", "content": user_input})
        with st.spinner("Darwin is thinking..."):
            response, papers = send_command(user_input)
            st.session_state.chat_history.append({
                "role": "agent",
                "content": response,
                "papers": papers,
            })
        st.session_state.input_key += 1
        st.rerun()

    st.divider()

    # Chat history
    for msg in st.session_state.chat_history:
        if msg["role"] == "user":
            with st.chat_message("user"):
                st.markdown(msg["content"])
        elif msg["role"] == "agent":
            with st.chat_message("assistant"):
                if msg.get("papers"):
                    # Show intro line only, skip the full paper list text
                    text_lines = [l for l in msg["content"].splitlines() if l.strip()]
                    intro = next(
                        (l for l in text_lines
                         if not l.startswith("#") and not l.startswith("**")
                         and not l.startswith("-") and not l.startswith("Found")),
                        ""
                    )
                    if intro:
                        st.markdown(intro)
                    render_paper_cards(msg["papers"])
                else:
                    st.markdown(msg["content"])
        elif msg["role"] == "error":
            st.error(msg["content"])


# ─── Footer ───
st.divider()
st.markdown("""
### 📖 Available Commands

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

st.markdown("""
<div class="foot">
    <strong>Darwin Research Agent</strong> · Powered by ArXiv, Ollama & MCP · Built with Streamlit
</div>
""", unsafe_allow_html=True)
