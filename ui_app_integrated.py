import streamlit as st
import asyncio
import json
import os
import sys
from pathlib import Path
from datetime import datetime

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

try:
    from src.agent.mcp_client import MCPClient
    from src.agent.ollama_client import OllamaClient
except ImportError as e:
    st.error(f"Import error: {e}")
    st.stop()

# Page configuration
st.set_page_config(
    page_title="Darwin Research Agent",
    page_icon="🧬",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown("""
<style>
    .main-header { font-size: 2.5em; color: #1f77b4; font-weight: bold; }
    .paper-card { background-color: #ffffff; border-left: 4px solid #1f77b4; padding: 15px; margin: 10px 0; border-radius: 5px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
    .success-message { background-color: #d4edda; padding: 15px; border-radius: 5px; color: #155724; }
    .error-message { background-color: #f8d7da; padding: 15px; border-radius: 5px; color: #721c24; }
</style>
""", unsafe_allow_html=True)

# Initialize session state
if "initialized" not in st.session_state:
    st.session_state.initialized = False
    st.session_state.mcp_client = None
    st.session_state.ollama_client = None
    st.session_state.papers = []
    st.session_state.search_results = []
    st.session_state.approved_papers = set()

async def init_clients():
    """Initialize MCP and Ollama clients"""
    try:
        # Load config
        with open("config/agent_config.json", "r") as f:
            agent_config = json.load(f)
        
        # Initialize Ollama
        st.session_state.ollama_client = OllamaClient(
            model_name=agent_config.get("model_name", "llama3.1"),
            host=agent_config.get("api_base", "http://localhost:11434"),
            system_prompt=agent_config.get("system_prompt", "")
        )
        
        # Initialize MCP
        st.session_state.mcp_client = MCPClient(config_path="config/claude_desktop_config.json")
        await st.session_state.mcp_client.connect()
        
        st.session_state.initialized = True
        return True
    except Exception as e:
        st.error(f"❌ Failed to initialize: {str(e)}")
        return False

def get_event_loop():
    """Get or create event loop"""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop

# Header
st.markdown("<h1 class='main-header'>🧬 Darwin Research Agent</h1>", unsafe_allow_html=True)
st.markdown("Your intelligent research assistant for ArXiv papers with full Obsidian integration")

# Sidebar
with st.sidebar:
    st.title("⚙️ Settings & Status")
    
    if not st.session_state.initialized:
        if st.button("🔌 Connect to Services", use_container_width=True):
            with st.spinner("Connecting..."):
                loop = get_event_loop()
                if loop.run_until_complete(init_clients()):
                    st.success("✅ Connected!")
                    st.rerun()
    else:
        st.success("✅ Connected to Ollama & MCP")
        st.divider()
        
        # System info
        col1, col2 = st.columns(2)
        with col1:
            st.metric("Model", "llama3.1")
        with col2:
            st.metric("Mode", "CPU")
        
        st.divider()
        
        with st.expander("📋 Downloaded Papers", expanded=False):
            papers_path = Path("papers")
            if papers_path.exists():
                papers = list(papers_path.glob("*.pdf"))
                if papers:
                    for paper in papers:
                        st.text(f"📄 {paper.name}")
                    st.caption(f"Total: {len(papers)} papers")
                else:
                    st.info("No papers downloaded yet")
            else:
                st.info("Papers folder not found")
        
        with st.expander("📚 Obsidian Notes", expanded=False):
            notes_path = Path("Darwin Research/Research/Incoming")
            if notes_path.exists():
                notes = list(notes_path.glob("*.md"))
                if notes:
                    for note in notes:
                        st.text(f"📝 {note.name}")
                    st.caption(f"Total: {len(notes)} notes")
                else:
                    st.info("No notes created yet")
            else:
                st.info("Notes folder not configured")

# Main Content
if not st.session_state.initialized:
    st.info("👈 Click 'Connect to Services' in the sidebar to get started")
else:
    # Create tabs
    tab1, tab2, tab3, tab4 = st.tabs(["🔍 Search", "📥 Download", "📖 Read", "📝 Create Note"])
    
    # TAB 1: Search
    with tab1:
        st.subheader("🔍 Search ArXiv Papers")
        st.write("Search for papers on any topic from ArXiv")
        
        col1, col2 = st.columns([3, 1])
        with col1:
            search_topic = st.text_input(
                "Topic to search",
                placeholder="e.g., machine learning, transformers, reinforcement learning"
            )
        with col2:
            max_results = st.number_input("Max results", min_value=1, max_value=50, value=5)
        
        if st.button("🔍 Search Now", use_container_width=True):
            if search_topic:
                with st.spinner(f"🔄 Searching for '{search_topic}'..."):
                    try:
                        loop = get_event_loop()
                        results = loop.run_until_complete(
                            st.session_state.mcp_client.call_tool("search_papers", {
                                "query": search_topic,
                                "max_results": int(max_results)
                            })
                        )
                        
                        # Parse results
                        import ast
                        if isinstance(results, str):
                            results = ast.literal_eval(results)
                        
                        st.session_state.search_results = results if isinstance(results, list) else [results]
                        st.success(f"✅ Found {len(st.session_state.search_results)} papers!")
                    except Exception as e:
                        st.error(f"❌ Search failed: {str(e)}")
        
        # Display search results
        if st.session_state.search_results:
            st.divider()
            st.subheader(f"Results ({len(st.session_state.search_results)} papers)")
            
            for i, paper in enumerate(st.session_state.search_results, 1):
                with st.container():
                    st.markdown(f"<div class='paper-card'>", unsafe_allow_html=True)
                    
                    title = paper.get("title", "Unknown Title")
                    paper_id = paper.get("id", "Unknown ID")
                    published = paper.get("published", "Unknown Date")
                    summary = paper.get("summary", "No summary available")
                    
                    st.write(f"**{i}. {title}**")
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.caption(f"🆔 ID: `{paper_id}`")
                    with col2:
                        st.caption(f"📅 {published}")
                    
                    st.write(f"_{summary[:200]}{'...' if len(summary) > 200 else ''}_")
                    st.markdown("</div>", unsafe_allow_html=True)
    
    # TAB 2: Download
    with tab2:
        st.subheader("📥 Download Papers")
        st.write("Download papers directly to your papers folder")
        
        col1, col2, col3 = st.columns([2, 1, 1])
        with col1:
            paper_id = st.text_input(
                "Paper ID",
                placeholder="e.g., 2306.04338v1"
            )
        with col2:
            auto_approve = st.checkbox("Auto-approve", value=False)
        with col3:
            pass
        
        if st.button("📥 Download", use_container_width=True):
            if paper_id:
                paper_id = paper_id.strip()
                
                with st.spinner(f"📥 Downloading paper {paper_id}..."):
                    try:
                        if not auto_approve:
                            # Show approval prompt
                            st.info("⏳ Checking approval...")
                            
                            # Call confirm_download first
                            loop = get_event_loop()
                            confirm_result = loop.run_until_complete(
                                st.session_state.mcp_client.call_tool("confirm_download", {
                                    "paper_id": paper_id,
                                    "paper_title": "Research Paper",
                                    "published_date": datetime.now().strftime("%Y-%m-%d"),
                                    "abstract": "New research paper to download"
                                })
                            )
                            
                            st.warning("👤 Approval Required")
                            col1, col2, col3 = st.columns(3)
                            with col1:
                                if st.button("✅ Approve & Download"):
                                    # Download after approval
                                    result = loop.run_until_complete(
                                        st.session_state.mcp_client.call_tool("download_paper", {
                                            "paper_id": paper_id
                                        })
                                    )
                                    st.session_state.papers.append(paper_id)
                                    st.success(f"✅ Downloaded! Saved to: {result}")
                            with col2:
                                if st.button("❌ Reject"):
                                    st.info("Download cancelled")
                        else:
                            # Auto-approve and download
                            loop = get_event_loop()
                            result = loop.run_until_complete(
                                st.session_state.mcp_client.call_tool("download_paper", {
                                    "paper_id": paper_id
                                })
                            )
                            st.session_state.papers.append(paper_id)
                            st.markdown(f"<div class='success-message'>✅ Downloaded successfully!</div>", unsafe_allow_html=True)
                            st.caption(f"📍 Saved to: {result}")
                    except Exception as e:
                        st.markdown(f"<div class='error-message'>❌ Download failed: {str(e)}</div>", unsafe_allow_html=True)
        
        if auto_approve:
            st.info("⚡ Auto-approval mode: Downloads will proceed immediately")
        else:
            st.info("👤 Approval mode: You'll be asked before each download")
    
    # TAB 3: Read
    with tab3:
        st.subheader("📖 Read Paper Content")
        st.write("Extract and display full text from downloaded papers")
        
        paper_id = st.text_input(
            "Paper ID to read",
            placeholder="e.g., 2306.04338v1",
            key="read_paper_id"
        )
        
        if st.button("📖 Read Paper", use_container_width=True):
            if paper_id:
                paper_id = paper_id.strip()
                
                with st.spinner(f"📄 Extracting content from {paper_id}..."):
                    try:
                        loop = get_event_loop()
                        content = loop.run_until_complete(
                            st.session_state.mcp_client.call_tool("read_paper", {
                                "paper_id": paper_id
                            })
                        )
                        
                        st.success(f"✅ Extracted {len(content)} characters")
                        
                        with st.expander("📄 Full Paper Text", expanded=True):
                            st.text_area(
                                "Paper content:",
                                value=content,
                                height=400,
                                disabled=True
                            )
                    except Exception as e:
                        st.error(f"❌ Failed to read paper: {str(e)}")
    
    # TAB 4: Create Note
    with tab4:
        st.subheader("📝 Create Research Note")
        st.write("Create structured notes directly in Obsidian vault")
        
        note_type = st.radio("Note type", ["Generic Note", "Paper-Specific Note"], horizontal=True)
        
        if note_type == "Generic Note":
            st.markdown("#### Generic Research Note")
            
            note_title = st.text_input(
                "Note title",
                placeholder="e.g., Machine Learning Trends"
            )
            note_content = st.text_area(
                "Note content",
                placeholder="Enter your research insights...",
                height=150
            )
            note_tags = st.text_input(
                "Tags (comma-separated)",
                placeholder="research, machine-learning, 2024"
            )
            
            if st.button("📝 Create Note", use_container_width=True):
                if note_title and note_content:
                    with st.spinner("✍️ Creating note..."):
                        try:
                            loop = get_event_loop()
                            tags = [tag.strip() for tag in note_tags.split(",") if tag.strip()]
                            
                            result = loop.run_until_complete(
                                st.session_state.mcp_client.call_tool("obsidian_create_note", {
                                    "title": note_title,
                                    "content": note_content,
                                    "tags": tags
                                })
                            )
                            
                            st.markdown("<div class='success-message'>✅ Note created successfully!</div>", unsafe_allow_html=True)
                            st.caption(f"📍 Location: {result.get('file_location', 'Obsidian vault')}")
                        except Exception as e:
                            st.error(f"❌ Failed to create note: {str(e)}")
        
        else:
            st.markdown("#### Paper-Specific Note")
            
            paper_id_note = st.text_input(
                "Paper ID",
                placeholder="e.g., 2306.04338v1",
                key="paper_id_for_note"
            )
            
            analysis = st.text_area(
                "Your analysis",
                placeholder="Your insights and analysis of this paper...",
                height=150
            )
            
            if st.button("📝 Create Paper Note", use_container_width=True):
                if paper_id_note and analysis:
                    with st.spinner("📝 Creating paper note..."):
                        try:
                            loop = get_event_loop()
                            
                            result = loop.run_until_complete(
                                st.session_state.mcp_client.call_tool("obsidian_create_paper_note", {
                                    "paper_id": paper_id_note,
                                    "title": f"Analysis: {paper_id_note}",
                                    "authors": ["Research Agent"],
                                    "abstract": analysis,
                                    "keywords": ["analysis", "research"]
                                })
                            )
                            
                            st.markdown("<div class='success-message'>✅ Paper note created!</div>", unsafe_allow_html=True)
                            st.caption(f"📍 Location: {result.get('file_location', 'Obsidian vault')}")
                        except Exception as e:
                            st.error(f"❌ Failed to create note: {str(e)}")

# Footer
st.divider()
st.markdown("""
---
### 🎯 How This Works

This is a **fully integrated GUI** that connects directly to:
- **Ollama LLM** (llama3.1) running locally
- **MCP Servers** (ArXiv, PDF Parser, Obsidian)
- **Your file system** (papers & notes folders)

No terminal needed - **everything executes from this interface!**

### ✨ Features

- 🔍 **Search**: Find papers directly
- 📥 **Download**: Get papers with approval workflow
- 📖 **Read**: Extract full paper text
- 📝 **Create Notes**: Generate Obsidian notes directly

### 📊 System Status

Check the sidebar for:
- Downloaded papers list
- Created Obsidian notes
- System connection status
""")
