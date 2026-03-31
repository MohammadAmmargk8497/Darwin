import streamlit as st
import asyncio
import json
import os
from datetime import datetime
from src.agent.mcp_client import MCPClient
from src.agent.ollama_client import OllamaClient

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
    .search-box { background-color: #f0f2f6; padding: 15px; border-radius: 10px; }
    .paper-card { background-color: #ffffff; border-left: 4px solid #1f77b4; padding: 15px; margin: 10px 0; border-radius: 5px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
    .approval-prompt { background-color: #fff3cd; padding: 15px; border-radius: 5px; border-left: 4px solid #ffc107; }
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
st.markdown("Your intelligent research assistant for ArXiv papers")

# Sidebar
with st.sidebar:
    st.title("⚙️ Settings")
    
    if not st.session_state.initialized:
        if st.button("🔌 Connect to Services"):
            loop = get_event_loop()
            if loop.run_until_complete(init_clients()):
                st.success("✅ Connected!")
                st.rerun()
    else:
        st.success("✅ Connected")
        st.divider()
        
        with st.expander("📋 Downloaded Papers"):
            if st.session_state.papers:
                for paper in st.session_state.papers:
                    st.text(f"📄 {paper}")
            else:
                st.info("No papers downloaded yet")
        
        with st.expander("🔧 Approval Settings"):
            approval_mode = st.radio(
                "Download approval mode:",
                ["Ask for confirmation", "Auto-approve"],
                key="approval_mode"
            )
            st.session_state.auto_approve = approval_mode == "Auto-approve"
            
            if approval_mode == "Auto-approve":
                st.warning("⚠️ Downloads will proceed without asking")

# Main Content
if not st.session_state.initialized:
    st.info("👈 Click 'Connect to Services' in the sidebar to get started")
else:
    # Create tabs
    tab1, tab2, tab3, tab4 = st.tabs(["🔍 Search", "📥 Download", "📖 Read", "📝 Create Note"])
    
    # TAB 1: Search
    with tab1:
        st.subheader("Search ArXiv Papers")
        
        col1, col2 = st.columns([3, 1])
        with col1:
            search_query = st.text_input("Search for papers:", placeholder="e.g., reinforcement learning, transformers, deep learning")
        with col2:
            max_results = st.number_input("Max results:", min_value=1, max_value=50, value=5)
        
        if st.button("🔍 Search", use_container_width=True):
            if search_query:
                with st.spinner("Searching ArXiv..."):
                    try:
                        loop = get_event_loop()
                        results = loop.run_until_complete(
                            st.session_state.mcp_client.call_tool("search_papers", {
                                "query": search_query,
                                "max_results": max_results
                            })
                        )
                        
                        # Parse results
                        import ast
                        if isinstance(results, str):
                            results = ast.literal_eval(results)
                        
                        st.session_state.search_results = results if isinstance(results, list) else [results]
                        st.success(f"✅ Found {len(st.session_state.search_results)} papers")
                    except Exception as e:
                        st.error(f"❌ Search failed: {str(e)}")
        
        # Display search results
        if st.session_state.search_results:
            st.divider()
            for i, paper in enumerate(st.session_state.search_results):
                with st.container():
                    st.markdown(f"<div class='paper-card'>", unsafe_allow_html=True)
                    
                    # Paper info
                    title = paper.get("title", "Unknown Title")
                    paper_id = paper.get("id", "Unknown ID")
                    published = paper.get("published", "Unknown Date")
                    summary = paper.get("summary", "No summary available")
                    
                    st.write(f"**📄 {title}**")
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.caption(f"ID: `{paper_id}`")
                    with col2:
                        st.caption(f"📅 {published}")
                    with col3:
                        pass
                    
                    st.write(f"*{summary[:200]}...*" if len(summary) > 200 else f"*{summary}*")
                    st.markdown("</div>", unsafe_allow_html=True)
    
    # TAB 2: Download
    with tab2:
        st.subheader("Download Papers")
        
        col1, col2 = st.columns([2, 1])
        with col1:
            paper_id = st.text_input("Paper ID to download:", placeholder="e.g., 2306.04338v1")
        with col2:
            if st.button("📥 Download", use_container_width=True):
                if paper_id:
                    with st.spinner("Downloading..."):
                        try:
                            loop = get_event_loop()
                            result = loop.run_until_complete(
                                st.session_state.mcp_client.call_tool("download_paper", {
                                    "paper_id": paper_id
                                })
                            )
                            
                            st.markdown("<div class='success-message'>✅ Download successful!</div>", unsafe_allow_html=True)
                            st.caption(f"📍 Saved to: {result}")
                            st.session_state.papers.append(paper_id)
                        except Exception as e:
                            st.markdown(f"<div class='error-message'>❌ Download failed: {str(e)}</div>", unsafe_allow_html=True)
        
        # Download approval prompt
        if st.session_state.get("auto_approve"):
            st.info("⚡ Auto-approval mode: Downloads will proceed immediately")
        else:
            st.info("👤 Approval mode: You'll be asked before each download")
    
    # TAB 3: Read
    with tab3:
        st.subheader("Read Paper Content")
        
        paper_id = st.text_input("Paper ID to read:", placeholder="e.g., 2306.04338v1", key="read_paper_id")
        
        if st.button("📖 Read Paper", use_container_width=True):
            if paper_id:
                with st.spinner("Extracting paper content..."):
                    try:
                        loop = get_event_loop()
                        content = loop.run_until_complete(
                            st.session_state.mcp_client.call_tool("read_paper", {
                                "paper_id": paper_id
                            })
                        )
                        
                        with st.expander("📄 Full Paper Text", expanded=True):
                            st.text_area("Paper content:", value=content, height=400, disabled=True)
                    except Exception as e:
                        st.error(f"❌ Failed to read paper: {str(e)}")
    
    # TAB 4: Create Note
    with tab4:
        st.subheader("Create Research Note")
        
        col1, col2 = st.columns(2)
        with col1:
            note_type = st.radio("Note type:", ["Generic Note", "Paper-Specific Note"])
        with col2:
            pass
        
        if note_type == "Generic Note":
            note_title = st.text_input("Note title:", placeholder="e.g., Weekly RL Digest")
            note_content = st.text_area("Note content:", placeholder="Enter your research notes here...")
            note_tags = st.text_input("Tags (comma-separated):", placeholder="research, machine-learning, 2024")
            
            if st.button("📝 Create Note", use_container_width=True):
                if note_title and note_content:
                    with st.spinner("Creating note..."):
                        try:
                            loop = get_event_loop()
                            result = loop.run_until_complete(
                                st.session_state.mcp_client.call_tool("obsidian_create_note", {
                                    "title": note_title,
                                    "content": note_content,
                                    "tags": [tag.strip() for tag in note_tags.split(",") if tag.strip()]
                                })
                            )
                            
                            st.markdown("<div class='success-message'>✅ Note created successfully!</div>", unsafe_allow_html=True)
                            st.caption(f"📍 Location: {result.get('file_location', 'Obsidian vault')}")
                        except Exception as e:
                            st.markdown(f"<div class='error-message'>❌ Failed to create note: {str(e)}</div>", unsafe_allow_html=True)
        
        else:  # Paper-Specific Note
            paper_id = st.text_input("Paper ID:", placeholder="e.g., 2306.04338v1", key="note_paper_id")
            analysis = st.text_area("Your analysis:", placeholder="What did you learn from this paper?")
            
            if st.button("📝 Create Paper Note", use_container_width=True):
                if paper_id and analysis:
                    with st.spinner("Creating paper note..."):
                        try:
                            loop = get_event_loop()
                            result = loop.run_until_complete(
                                st.session_state.mcp_client.call_tool("obsidian_create_paper_note", {
                                    "paper_id": paper_id,
                                    "analysis": analysis
                                })
                            )
                            
                            st.markdown("<div class='success-message'>✅ Paper note created!</div>", unsafe_allow_html=True)
                            st.caption(f"📍 Location: {result.get('file_location', 'Obsidian vault')}")
                        except Exception as e:
                            st.markdown(f"<div class='error-message'>❌ Failed to create note: {str(e)}</div>", unsafe_allow_html=True)

# Footer
st.divider()
st.markdown("**Darwin Research Agent** | Powered by ArXiv, Ollama, and MCP | Built with Streamlit")
