import streamlit as st
import subprocess
import threading
import time
from pathlib import Path

# Page configuration
st.set_page_config(
    page_title="Darwin Research Agent - Live Chat",
    page_icon="🧬",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
    .agent-message { background-color: #e3f2fd; padding: 10px; border-radius: 5px; margin: 5px 0; border-left: 4px solid #1976d2; }
    .user-message { background-color: #f3e5f5; padding: 10px; border-radius: 5px; margin: 5px 0; border-left: 4px solid #7b1fa2; text-align: right; }
    .tool-execution { background-color: #fff3e0; padding: 10px; border-radius: 5px; margin: 5px 0; border-left: 4px solid #f57c00; font-family: monospace; font-size: 0.9em; }
    .thinking { background-color: #f0f4c3; padding: 10px; border-radius: 5px; margin: 5px 0; border-left: 4px solid #9ccc65; font-style: italic; }
</style>
""", unsafe_allow_html=True)

# Initialize session state
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "agent_process" not in st.session_state:
    st.session_state.agent_process = None
if "agent_ready" not in st.session_state:
    st.session_state.agent_ready = False

def start_agent():
    """Start the agent wrapper as a subprocess"""
    try:
        process = subprocess.Popen(
            ["python", "agent_wrapper.py"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            cwd="c:\\Users\\ADMIN\\Darwin"
        )
        
        # Wait for agent to be ready
        import time
        for _ in range(30):
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

def send_command_to_agent(command):
    """Send a command to the agent and get the response"""
    try:
        process = st.session_state.agent_process
        if not process or process.poll() is not None:
            return "Error: Agent process not running"
        
        # Send command
        process.stdin.write(command + "\n")
        process.stdin.flush()
        
        # Read response
        response_lines = []
        import time
        timeout = 60
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
            elif line.startswith("TOOL_EXECUTE:"):
                content = line.replace("TOOL_EXECUTE:", "", 1)
                response_lines.append(("tool", f"🔧 Executing: {content}"))
            elif line.startswith("TOOL_ERROR:"):
                content = line.replace("TOOL_ERROR:", "", 1)
                response_lines.append(("error", f"✗ {content}"))
            elif line.startswith("TOOL_AUTO_APPROVE"):
                response_lines.append(("tool", "⚡ Auto-approved (no user prompt)"))
            elif line.startswith("TOOL_USER_APPROVED"):
                response_lines.append(("tool", "✓ User approved"))
            elif line.startswith("TOOL_USER_REJECTED"):
                response_lines.append(("tool", "✗ User rejected"))
            elif line.startswith("TOOL_BLOCKED:"):
                content = line.replace("TOOL_BLOCKED:", "", 1)
                response_lines.append(("tool", f"🔒 Blocked: {content}"))
            elif line.startswith("ERROR:"):
                content = line.replace("ERROR:", "", 1)
                response_lines.append(("error", f"Error: {content}"))
                break
            elif line.startswith("AGENT_EXIT"):
                break
            else:
                # Unknown line - just add it
                if line:
                    response_lines.append(("agent", line))
        
        # Format response
        if not response_lines:
            return "No response from agent"
        
        # Combine into single response
        final_response = ""
        has_agent_response = False
        
        for role, content in response_lines:
            if role == "agent":
                final_response += content + "\n"
                has_agent_response = True
            elif role == "tool":
                final_response += content + "\n"
            elif role == "error":
                final_response += f"⚠️ {content}\n"
        
        return final_response.strip() if final_response.strip() else "Processing..."
    
    except Exception as e:
        return f"Error: {str(e)}"

# Header
st.markdown("# 🧬 Darwin Research Agent - Live Terminal")
st.markdown("💬 **Running agent.py directly in browser**")

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
        ("Search Papers", "search papers on machine learning"),
        ("List Papers", "list papers"),
        ("Download Paper", "download paper 2306.04338v1"),
        ("Read Paper", "read paper 2306.04338v1"),
        ("Create Note", "create a research note about AI for my Obsidian vault"),
    ]
    
    for label, cmd in quick_commands:
        if st.button(label, use_container_width=True, key=f"quick_{label}"):
            st.session_state.quick_cmd = cmd
    
    st.divider()
    
    with st.expander("📋 Downloads"):
        papers_path = Path("papers")
        if papers_path.exists():
            papers = list(papers_path.glob("*.pdf"))
            if papers:
                for p in papers:
                    st.text(f"📄 {p.name}")
                st.caption(f"Total: {len(papers)}")
    
    with st.expander("📚 Notes"):
        notes_path = Path("Darwin Research/Research/Incoming")
        if notes_path.exists():
            notes = list(notes_path.glob("*.md"))
            if notes:
                for n in notes:
                    st.text(f"📝 {n.name}")
                st.caption(f"Total: {len(notes)}")

# Main chat area
if not st.session_state.agent_ready:
    st.info("👈 Click 'Start Agent' to begin")
else:
    # Display chat history
    for msg in st.session_state.chat_history:
        if msg["role"] == "user":
            st.markdown(f"<div class='user-message'><b>You:</b> {msg['content']}</div>", unsafe_allow_html=True)
        elif msg["role"] == "assistant":
            # Split response into lines and format each appropriately
            lines = msg['content'].split('\n')
            for line in lines:
                if line.startswith("🔧"):
                    st.markdown(f"<div class='tool-execution'>{line}</div>", unsafe_allow_html=True)
                elif line.startswith("✓") or line.startswith("✗") or line.startswith("⚡") or line.startswith("🔒"):
                    st.markdown(f"<div class='tool-execution'>{line}</div>", unsafe_allow_html=True)
                elif line.startswith("⚠️"):
                    st.warning(line)
                elif line:
                    st.markdown(f"<div class='agent-message'><b>Agent:</b> {line}</div>", unsafe_allow_html=True)
        elif msg["role"] == "error":
            st.error(f"Error: {msg['content']}")
    
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
                "Type your command (or use quick commands →)",
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
            response = send_command_to_agent(user_input)
            
            # Add response to history
            st.session_state.chat_history.append({"role": "assistant", "content": response})
        
        st.rerun()

# Footer
st.divider()
st.markdown("""
### 📖 Available Commands

**Search & Browse:**
- `search papers on machine learning`
- `list papers`

**Download & Read:**
- `download paper 2306.04338v1`
- `download paper 2306.04338v1 without approval`
- `read paper 2306.04338v1`

**Create Notes:**
- `create a research note about AI for my Obsidian vault`
- `create a research note for paper 2306.04338v1 about data quality for Obsidian`

---
**🟢 Direct Terminal Integration** - Runs the same agent.py that works in terminal!
""")
st.markdown("**Darwin Research Agent** | Powered by ArXiv, Ollama, and MCP | Built with Streamlit")
