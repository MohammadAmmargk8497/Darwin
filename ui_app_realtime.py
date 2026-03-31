import streamlit as st
import asyncio
import json
import os
import sys
from pathlib import Path
from datetime import datetime
import requests
import time

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

# Page configuration
st.set_page_config(
    page_title="Darwin Research Agent - Real-Time",
    page_icon="🧬",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS with real-time updates
st.markdown("""
<style>
    .main-header { font-size: 2.5em; color: #1f77b4; font-weight: bold; }
    .paper-card { background-color: #ffffff; border-left: 4px solid #1f77b4; padding: 15px; margin: 10px 0; border-radius: 5px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
    .success-message { background-color: #d4edda; padding: 15px; border-radius: 5px; color: #155724; }
    .error-message { background-color: #f8d7da; padding: 15px; border-radius: 5px; color: #721c24; }
    .loading-message { background-color: #cfe2ff; padding: 15px; border-radius: 5px; color: #084298; }
    .agent-thinking { background-color: #e7f3ff; padding: 15px; border-left: 4px solid #0066cc; border-radius: 5px; }
</style>
""", unsafe_allow_html=True)

# Initialize session state
if "initialized" not in st.session_state:
    st.session_state.initialized = False
    st.session_state.mcp_client = None
    st.session_state.ollama_client = None
    st.session_state.papers = []
    st.session_state.search_results = []
    st.session_state.messages = []

# Initialize clients
async def init_clients():
    """Initialize MCP and Ollama clients with proper async handling"""
    try:
        with open("config/agent_config.json", "r") as f:
            agent_config = json.load(f)
        
        # Import after sys.path is set
        from src.agent.mcp_client import MCPClient
        from src.agent.ollama_client import OllamaClient
        
        # Initialize Ollama
        ollama = OllamaClient(
            model_name=agent_config.get("model_name", "llama3.1"),
            host=agent_config.get("api_base", "http://localhost:11434"),
            system_prompt=agent_config.get("system_prompt", "")
        )
        
        # Initialize MCP
        mcp = MCPClient(config_path="config/claude_desktop_config.json")
        await mcp.connect()
        
        st.session_state.ollama_client = ollama
        st.session_state.mcp_client = mcp
        st.session_state.initialized = True
        return True, "Connected!"
    except Exception as e:
        return False, str(e)

def get_loop():
    """Get or create event loop"""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop

# Check Ollama
def check_ollama():
    """Check if Ollama is running"""
    try:
        response = requests.get("http://localhost:11434/api/tags", timeout=2)
        return response.status_code == 200
    except:
        return False

# Header
st.markdown("<h1 class='main-header'>🧬 Darwin Research Agent - Real-Time</h1>", unsafe_allow_html=True)
st.markdown("🔴 Live connection to Ollama + MCP servers + ArXiv")

# Sidebar
with st.sidebar:
    st.title("⚙️ System Control")
    
    ollama_status = check_ollama()
    
    col1, col2 = st.columns(2)
    with col1:
        if ollama_status:
            st.success("✅ Ollama Online")
        else:
            st.error("❌ Ollama Offline")
    with col2:
        if st.session_state.initialized:
            st.success("✅ MCP Ready")
        else:
            st.warning("⏳ MCP Init...")
    
    st.divider()
    
    # Connection button
    if not st.session_state.initialized and ollama_status:
        if st.button("🔌 Initialize Connection", use_container_width=True):
            with st.spinner("Connecting to MCP servers..."):
                loop = get_loop()
                success, msg = loop.run_until_complete(init_clients())
                if success:
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)
    
    st.divider()
    
    # System info
    with st.expander("📊 System Info"):
        st.write(f"**Ollama**: {'🟢 Running' if ollama_status else '🔴 Stopped'}")
        st.write(f"**MCP**: {'🟢 Connected' if st.session_state.initialized else '🔴 Not Connected'}")
        st.write(f"**Model**: llama3.1 (CPU Mode)")
        
        if st.session_state.initialized:
            try:
                response = requests.get("http://localhost:11434/api/tags", timeout=2)
                if response.status_code == 200:
                    models = response.json().get("models", [])
                    st.write(f"**Available Models**: {len(models)}")
            except:
                pass
    
    with st.expander("📋 Downloaded Papers"):
        papers_path = Path("papers")
        if papers_path.exists():
            papers = list(papers_path.glob("*.pdf"))
            if papers:
                for paper in papers[:10]:
                    st.text(f"📄 {paper.name}")
                if len(papers) > 10:
                    st.caption(f"... and {len(papers) - 10} more")
                st.caption(f"**Total: {len(papers)} papers**")
            else:
                st.info("No papers yet")
    
    with st.expander("📚 Obsidian Notes"):
        notes_path = Path("Darwin Research/Research/Incoming")
        if notes_path.exists():
            notes = list(notes_path.glob("*.md"))
            if notes:
                for note in notes[:10]:
                    st.text(f"📝 {note.name}")
                if len(notes) > 10:
                    st.caption(f"... and {len(notes) - 10} more")
                st.caption(f"**Total: {len(notes)} notes**")
            else:
                st.info("No notes yet")

# Main content
if not ollama_status:
    st.error("🚨 **Ollama is not running!**")
    st.markdown("""
    Start Ollama:
    ```powershell
    $env:OLLAMA_GPU_DISABLED=1; ollama serve
    ```
    """)
    st.stop()

if not st.session_state.initialized:
    st.info("👈 Click '🔌 Initialize Connection' in the sidebar to connect")
    st.stop()

# Main tabs
tab1, tab2, tab3, tab4 = st.tabs(["🔍 Search", "📥 Download", "📖 Read", "📝 Create Note"])

# TAB 1: Search Papers
with tab1:
    st.subheader("🔍 Search ArXiv Papers - Live")
    st.write("Real-time search powered by agent + ArXiv")
    
    col1, col2 = st.columns([3, 1])
    with col1:
        search_topic = st.text_input(
            "What papers do you want to find?",
            placeholder="e.g., machine learning, transformers, reinforcement learning"
        )
    with col2:
        max_results = st.number_input("Results", 1, 50, 5)
    
    if st.button("🔍 Search Real-Time", use_container_width=True, key="search_btn"):
        if search_topic:
            progress_container = st.container()
            result_container = st.container()
            
            with progress_container:
                progress = st.progress(0)
                status = st.empty()
            
            try:
                # Real-time search via MCP
                with result_container:
                    status.text("🔍 Agent searching ArXiv...")
                    progress.progress(25)
                    
                    loop = get_loop()
                    results = loop.run_until_complete(
                        st.session_state.mcp_client.call_tool("search_papers", {
                            "query": search_topic,
                            "max_results": int(max_results)
                        })
                    )
                    
                    progress.progress(75)
                    status.text("📊 Processing results...")
                    
                    # Parse results
                    import ast
                    if isinstance(results, str):
                        results = ast.literal_eval(results)
                    
                    st.session_state.search_results = results if isinstance(results, list) else [results]
                    
                    progress.progress(100)
                    status.text("✅ Search complete!")
                    time.sleep(0.5)
                    progress.empty()
                    status.empty()
                    
                    st.success(f"✅ Found {len(st.session_state.search_results)} papers!")
                    
            except Exception as e:
                st.error(f"❌ Search error: {str(e)}")
    
    # Display results in real-time
    if st.session_state.search_results:
        st.divider()
        st.subheader(f"📄 Results ({len(st.session_state.search_results)} papers)")
        
        for i, paper in enumerate(st.session_state.search_results, 1):
            with st.container():
                st.markdown(f"<div class='paper-card'>", unsafe_allow_html=True)
                
                title = paper.get("title", "Unknown")
                paper_id = paper.get("id", "Unknown")
                published = paper.get("published", "Unknown")
                summary = paper.get("summary", "No summary")
                
                st.write(f"**{i}. {title}**")
                
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.caption(f"🆔 `{paper_id}`")
                with col2:
                    st.caption(f"📅 {published}")
                with col3:
                    if st.button("📥 Download", key=f"dl_{i}"):
                        with st.spinner("Downloading..."):
                            try:
                                result = loop.run_until_complete(
                                    st.session_state.mcp_client.call_tool("download_paper", {
                                        "paper_id": paper_id
                                    })
                                )
                                st.success(f"✅ Downloaded!")
                            except Exception as e:
                                st.error(f"❌ {str(e)}")
                with col4:
                    if st.button("📖 Read", key=f"rd_{i}"):
                        st.session_state.current_read = paper_id
                
                st.write(f"_{summary[:300]}..._")
                st.markdown("</div>", unsafe_allow_html=True)

# TAB 2: Download
with tab2:
    st.subheader("📥 Download Papers - Real-Time")
    
    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        dl_paper_id = st.text_input("Paper ID", placeholder="2306.04338v1")
    with col2:
        approve_auto = st.checkbox("Auto-approve", False)
    with col3:
        pass
    
    if st.button("📥 Download Now", use_container_width=True):
        if dl_paper_id:
            dl_paper_id = dl_paper_id.strip()
            
            with st.spinner(f"⏳ Downloading {dl_paper_id}..."):
                try:
                    loop = get_loop()
                    
                    if not approve_auto:
                        # Show approval UI
                        st.info("🔒 Approval required")
                        col1, col2 = st.columns(2)
                        with col1:
                            if st.button("✅ Approve", key="approve_dl"):
                                proceed = True
                            else:
                                proceed = False
                        with col2:
                            if st.button("❌ Reject", key="reject_dl"):
                                st.info("Download cancelled")
                                proceed = False
                    else:
                        proceed = True
                    
                    if proceed:
                        result = loop.run_until_complete(
                            st.session_state.mcp_client.call_tool("download_paper", {
                                "paper_id": dl_paper_id
                            })
                        )
                        st.success(f"✅ Downloaded: {dl_paper_id}")
                        st.caption(f"📍 {result}")
                        
                except Exception as e:
                    st.error(f"❌ Failed: {str(e)}")

# TAB 3: Read
with tab3:
    st.subheader("📖 Read Paper - Real-Time Extraction")
    
    read_id = st.text_input("Paper ID", placeholder="2306.04338v1", key="read_tab_id")
    
    if st.button("📖 Extract Text", use_container_width=True):
        if read_id:
            read_id = read_id.strip()
            
            with st.spinner(f"📄 Extracting text from {read_id}..."):
                try:
                    loop = get_loop()
                    content = loop.run_until_complete(
                        st.session_state.mcp_client.call_tool("read_paper", {
                            "paper_id": read_id
                        })
                    )
                    
                    st.success(f"✅ Extracted {len(content)} characters")
                    
                    with st.expander(f"📄 {read_id} - Full Text", expanded=True):
                        st.text_area("Content", content, height=400, disabled=True)
                        
                        # Quick actions
                        col1, col2 = st.columns(2)
                        with col1:
                            if st.button("💾 Save to Note"):
                                os.makedirs("Darwin Research/Research/Incoming", exist_ok=True)
                                filename = f"Darwin Research/Research/Incoming/{read_id}_extracted.md"
                                with open(filename, 'w', encoding='utf-8') as f:
                                    f.write(f"# {read_id}\n\n{content}")
                                st.success(f"✅ Saved as note")
                        
                except Exception as e:
                    st.error(f"❌ Failed: {str(e)}")

# TAB 4: Create Note
with tab4:
    st.subheader("📝 Create Research Note - Live")
    
    note_type = st.radio("Note Type", ["Generic Research", "Paper Analysis"], horizontal=True)
    
    if note_type == "Generic Research":
        st.write("Create a general research note")
        
        nt = st.text_input("Title", placeholder="AI Safety Research")
        nc = st.text_area("Content", placeholder="Your insights...", height=150)
        ntags = st.text_input("Tags", placeholder="AI, safety, research")
        
        if st.button("📝 Create Note", use_container_width=True):
            if nt and nc:
                with st.spinner("Creating note..."):
                    try:
                        loop = get_loop()
                        result = loop.run_until_complete(
                            st.session_state.mcp_client.call_tool("obsidian_create_note", {
                                "title": nt,
                                "content": nc,
                                "tags": [t.strip() for t in ntags.split(",") if t.strip()]
                            })
                        )
                        st.success("✅ Note created in Obsidian!")
                    except Exception as e:
                        st.error(f"❌ Failed: {str(e)}")
    
    else:
        st.write("Create analysis for specific paper")
        
        pid = st.text_input("Paper ID", placeholder="2306.04338v1")
        analysis = st.text_area("Your Analysis", placeholder="Key insights...", height=150)
        
        if st.button("📝 Create Paper Note", use_container_width=True):
            if pid and analysis:
                with st.spinner("Creating paper note..."):
                    try:
                        loop = get_loop()
                        result = loop.run_until_complete(
                            st.session_state.mcp_client.call_tool("obsidian_create_paper_note", {
                                "paper_id": pid,
                                "title": f"Analysis: {pid}",
                                "authors": ["You"],
                                "abstract": analysis,
                                "keywords": ["analysis"]
                            })
                        )
                        st.success("✅ Paper note created!")
                    except Exception as e:
                        st.error(f"❌ Failed: {str(e)}")

# Footer
st.divider()
st.markdown("""
### 🚀 Real-Time Features

✅ **Live Search** - Direct ArXiv search via agent
✅ **Real-Time Download** - Instant paper retrieval
✅ **Smart Extraction** - AI-powered text extraction
✅ **Obsidian Integration** - Direct note creation
✅ **One-Click Actions** - Download, Read, Analyze buttons

### 📊 System

- **Backend**: Darwin Research Agent (llama3.1 + MCP)
- **LLM**: Ollama (CPU Mode)
- **Storage**: Papers folder + Obsidian vault
- **Status**: 🟢 Real-time ready
""")
