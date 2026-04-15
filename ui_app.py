import streamlit as st
import subprocess
import time
import json
import os
import re
from pathlib import Path

# Page configuration
st.set_page_config(
    page_title="Darwin Research Agent",
    page_icon="🧬",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
    .paper-card {
        background-color: #f0f4f8;
        padding: 15px;
        border-radius: 8px;
        margin: 10px 0;
        border-left: 4px solid #1976d2;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        color: #1a1a1a;
    }
    .paper-id { font-family: monospace; color: #666; font-size: 0.9em; }
    .paper-title { font-size: 1.1em; font-weight: bold; color: #1976d2; margin: 5px 0; }
    .paper-summary { color: #333; line-height: 1.5; margin: 10px 0; }
    .agent-message { background-color: #e8f5e9; padding: 12px; border-radius: 5px; margin: 5px 0; border-left: 4px solid #4caf50; color: #1a1a1a; }
    .user-message { background-color: #f3e5f5; padding: 12px; border-radius: 5px; margin: 5px 0; text-align: right; color: #1a1a1a; }
    .tool-message { background-color: #fff3e0; padding: 12px; border-radius: 5px; margin: 5px 0; border-left: 4px solid #ff9800; font-family: monospace; font-size: 0.9em; color: #1a1a1a; }
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
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            cwd=cwd,
            env=env
        )

        # Wait for agent to be ready (MCP servers may take a few seconds to start)
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
        
        # Read response
        response_lines = []
        papers = []
        timeout = 180
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            line = process.stdout.readline()
            
            if not line:
                time.sleep(0.05)
                continue
            
            line = line.rstrip()
            
            # Parse structured output
            if line.startswith("AGENT_RESPONSE:"):
                content = line.replace("AGENT_RESPONSE:", "", 1)
                response_lines.append(("agent", content))
                # Try to extract papers from this response
                extracted = extract_papers_from_response(content)
                if extracted:
                    papers.extend(extracted)
            elif line.startswith("TOOL_EXECUTE:"):
                content = line.replace("TOOL_EXECUTE:", "", 1)
                response_lines.append(("tool", f"🔧 Executing: {content}"))
            elif line.startswith("TOOL_ERROR:"):
                content = line.replace("TOOL_ERROR:", "", 1)
                response_lines.append(("error", f"✗ Error: {content}"))
            elif line.startswith("TOOL_CONFIRM:"):
                # Auto-approve downloads from UI — send "yes" back to unblock agent
                process.stdin.write("yes\n")
                process.stdin.flush()
                response_lines.append(("tool", "✓ Download approved"))
            elif line.startswith("TOOL_BLOCKED:"):
                content = line.replace("TOOL_BLOCKED:", "", 1)
                response_lines.append(("tool", f"⚠ Blocked: {content}"))
            elif line.startswith("ERROR:"):
                content = line.replace("ERROR:", "", 1)
                response_lines.append(("error", f"Error: {content}"))
                break
            elif line.startswith("AGENT_END"):
                break  # Agent finished processing this command
            elif line.startswith("AGENT_EXIT"):
                break
        
        # Format response
        final_response = ""
        for role, content in response_lines:
            if content.strip():
                final_response += content + "\n"
        
        return final_response.strip() if final_response.strip() else "Processing...", papers
    
    except Exception as e:
        return f"Error: {str(e)}", []

# Header
st.markdown("# 🧬 Darwin Research Agent")
st.markdown("**Web frontend for your research agent**")

# Sidebar
with st.sidebar:
    st.title("⚙️ Agent Control")
    
    if not st.session_state.agent_ready:
        if st.button("🔌 Start Agent", use_container_width=True):
            with st.spinner("Starting agent..."):
                if start_agent():
                    st.success("Agent started!")
                    st.rerun()
    else:
        st.success("✅ Agent Running")
        
        if st.button("🛑 Stop Agent", use_container_width=True):
            if st.session_state.agent_process:
                st.session_state.agent_process.terminate()
                st.session_state.agent_ready = False
            st.rerun()
    
    st.divider()
    
    # Quick commands
    st.write("**Quick Commands:**")
    
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
        papers_path = Path("papers")
        if papers_path.exists():
            papers = list(papers_path.glob("*.pdf"))
            if papers:
                for p in papers:
                    st.text(f"📄 {p.name}")
                st.caption(f"Total: {len(papers)}")
            else:
                st.caption("No papers downloaded yet")
    
    with st.expander("📚 Obsidian Notes"):
        notes_path = Path("Darwin Research/Research/Incoming")
        if notes_path.exists():
            notes = list(notes_path.glob("*.md"))
            if notes:
                for n in notes:
                    st.text(f"📝 {n.name}")
                st.caption(f"Total: {len(notes)}")
            else:
                st.caption("No notes created yet")

# Main chat area
if not st.session_state.agent_ready:
    st.info("👈 Click **'Start Agent'** in the sidebar to begin")
else:
    # Display chat history
    for msg in st.session_state.chat_history:
        if msg["role"] == "user":
            st.markdown(f"<div class='user-message'><b>You:</b> {msg['content']}</div>", unsafe_allow_html=True)
        elif msg["role"] == "agent":
            st.markdown(f"<div class='agent-message'>{msg['content']}</div>", unsafe_allow_html=True)
            
            # Display papers if this response had papers
            if msg.get("papers"):
                st.markdown("### 📄 Search Results:")
                for paper in msg["papers"]:
                    st.markdown(f"""
                    <div class='paper-card'>
                        <div class='paper-id'>ID: {paper['id']}</div>
                        <div class='paper-title'>{paper['title']}</div>
                        <div class='paper-summary'>{paper['summary']}</div>
                    </div>
                    """, unsafe_allow_html=True)
        elif msg["role"] == "error":
            st.error(msg['content'])
    
    st.divider()
    
    # Input area
    col1, col2 = st.columns([5, 1])
    
    with col1:
        # Check if quick command was clicked
        if "quick_cmd" in st.session_state:
            user_input = st.session_state.quick_cmd
            st.session_state.quick_cmd = None
            should_send = True
        else:
            user_input = st.text_input(
                "Type your command:",
                placeholder="search papers on..., download paper..., read paper..., list papers, create note...",
                key="user_input"
            )
            should_send = False
    
    with col2:
        send_button = st.button("📤 Send", use_container_width=True)
    
    if (send_button or should_send) and user_input:
        # Add user message to history
        st.session_state.chat_history.append({"role": "user", "content": user_input})
        
        # Send command and get response
        with st.spinner("Executing..."):
            response, papers = send_command_to_agent(user_input)
            
            # Add response to history with papers
            st.session_state.chat_history.append({
                "role": "agent",
                "content": response,
                "papers": papers
            })
        
        st.rerun()

# Footer
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

---
**🟢 Direct Agent Integration** - Same agent as terminal, now in your browser!
""")
st.markdown("**Darwin Research Agent** | Powered by ArXiv, Ollama, and MCP | Built with Streamlit")
