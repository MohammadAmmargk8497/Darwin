import streamlit as st
import subprocess
import json
import os
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

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
if "papers" not in st.session_state:
    st.session_state.papers = []
if "search_results" not in st.session_state:
    st.session_state.search_results = []

# Header
st.markdown("<h1 class='main-header'>🧬 Darwin Research Agent</h1>", unsafe_allow_html=True)
st.markdown("Your intelligent research assistant for ArXiv papers with Obsidian integration")

# Check if Ollama is running
def check_ollama():
    try:
        import requests
        response = requests.get("http://localhost:11434/api/tags", timeout=2)
        return response.status_code == 200
    except:
        return False

# Sidebar
with st.sidebar:
    st.title("⚙️ System Status")
    
    # Check services
    ollama_status = check_ollama()
    
    col1, col2 = st.columns(2)
    with col1:
        st.metric("Ollama", "🟢 Online" if ollama_status else "🔴 Offline")
    
    st.divider()
    
    with st.expander("📋 Downloaded Papers"):
        papers_path = Path("papers")
        if papers_path.exists():
            papers = list(papers_path.glob("*.pdf"))
            if papers:
                for paper in papers:
                    st.text(f"📄 {paper.name}")
            else:
                st.info("No papers downloaded yet")
        else:
            st.info("Papers folder not found")
    
    st.divider()
    
    with st.expander("📚 Created Notes"):
        notes_path = Path("Darwin Research/Research/Incoming")
        if notes_path.exists():
            notes = list(notes_path.glob("*.md"))
            if notes:
                for note in notes:
                    st.text(f"📝 {note.name}")
            else:
                st.info("No notes created yet")
        else:
            st.info("Notes folder not configured")

# Main Content
if not ollama_status:
    st.warning("⚠️ Ollama is not running. Please start it with: `ollama serve` or `$env:OLLAMA_GPU_DISABLED=1; ollama serve`")
else:
    # Create tabs
    tab1, tab2, tab3, tab4 = st.tabs(["🔍 Search", "📥 Download", "📖 Read", "📝 Create Note"])
    
    # TAB 1: Search
    with tab1:
        st.subheader("Search ArXiv Papers")
        st.write("Search for papers on any topic from ArXiv")
        
        col1, col2 = st.columns([3, 1])
        with col1:
            search_topic = st.text_input(
                "Topic to search",
                placeholder="e.g., machine learning, transformers, reinforcement learning",
                key="search_query"
            )
        with col2:
            max_results = st.number_input("Max results", min_value=1, max_value=50, value=5)
        
        if st.button("🔍 Search", use_container_width=True, key="search_btn"):
            if search_topic:
                # Clean input - remove "search papers on" if user typed it
                query = search_topic.replace("search papers on ", "").strip()
                
                st.info("🔄 Searching... (via agent)")
                st.markdown(f"""
                **Search Command:**
                ```
                search papers on {query}
                ```
                
                👉 **Copy this command and run it in the agent terminal** to get results!
                """)
                
                st.divider()
                st.write("**How to use:**")
                st.markdown("""
                1. Copy the command from above
                2. Paste it in the Darwin Research Agent terminal
                3. Agent will find papers and return results
                4. Copy the paper IDs from results
                5. Use the other tabs (Download, Read, Create Note) to work with papers
                """)
    
    # TAB 2: Download
    with tab2:
        st.subheader("Download Papers")
        st.write("Download papers by ID from ArXiv")
        
        col1, col2 = st.columns([3, 1])
        with col1:
            paper_id = st.text_input(
                "Paper ID (without 'download paper' prefix)",
                placeholder="e.g., 2306.04338v1",
                key="download_id"
            )
        with col2:
            download_mode = st.selectbox("Mode", ["With Approval", "Auto-Approve"])
        
        if st.button("📥 Download", use_container_width=True, key="download_btn"):
            if paper_id:
                # Clean input
                paper_id = paper_id.replace("download paper ", "").strip()
                
                if download_mode == "With Approval":
                    st.info("🔄 Downloading with approval...")
                    st.markdown(f"""
                    **Download Command:**
                    ```
                    download paper {paper_id}
                    ```
                    
                    👉 **Paste in agent terminal and respond with 'yes' when asked!**
                    """)
                else:
                    st.info("⚡ Auto-downloading...")
                    st.markdown(f"""
                    **Auto-Download Command:**
                    ```
                    download paper {paper_id} without approval
                    ```
                    
                    👉 **Paste in agent terminal!**
                    """)
    
    # TAB 3: Read
    with tab3:
        st.subheader("Read Paper Content")
        st.write("Extract and display full paper text")
        
        paper_id = st.text_input(
            "Paper ID (without 'read paper' prefix)",
            placeholder="e.g., 2306.04338v1",
            key="read_id"
        )
        
        if st.button("📖 Read Paper", use_container_width=True, key="read_btn"):
            if paper_id:
                # Clean input
                paper_id = paper_id.replace("read paper ", "").strip()
                
                st.info("📖 Reading paper...")
                st.markdown(f"""
                **Read Command:**
                ```
                read paper {paper_id}
                ```
                
                👉 **Paste in agent terminal to see the full paper text!**
                """)
    
    # TAB 4: Create Note
    with tab4:
        st.subheader("Create Research Note")
        st.write("Create structured notes in your Obsidian vault")
        
        note_type = st.radio("Note Type", ["Generic Note", "Paper-Specific Note"], horizontal=True)
        
        if note_type == "Generic Note":
            st.markdown("#### Generic Research Note")
            
            note_topic = st.text_input(
                "Note topic",
                placeholder="e.g., machine learning trends, AI safety",
                key="note_topic"
            )
            
            if st.button("📝 Create Generic Note", use_container_width=True):
                if note_topic:
                    st.info("✍️ Creating note...")
                    st.markdown(f"""
                    **Create Note Command:**
                    ```
                    create a research note about {note_topic} for my Obsidian vault
                    ```
                    
                    👉 **Paste in agent terminal!**
                    
                    The note will include:
                    - Structured sections (Overview, Key Points, Analysis, References)
                    - YAML frontmatter with metadata
                    - Auto-linked to Obsidian vault
                    - Searchable by topic tags
                    """)
        
        else:
            st.markdown("#### Paper-Specific Note")
            
            paper_id_note = st.text_input(
                "Paper ID",
                placeholder="e.g., 2306.04338v1",
                key="paper_id_note"
            )
            
            analysis_topic = st.text_input(
                "Analysis focus",
                placeholder="e.g., data quality challenges, model performance impact",
                key="analysis_topic"
            )
            
            if st.button("📝 Create Paper Note", use_container_width=True):
                if paper_id_note and analysis_topic:
                    # Clean input
                    paper_id_note = paper_id_note.replace("create a research note for paper ", "").strip()
                    
                    st.info("📝 Creating paper-specific note...")
                    st.markdown(f"""
                    **Create Paper Note Command:**
                    ```
                    create a research note for paper {paper_id_note} about {analysis_topic} for Obsidian
                    ```
                    
                    👉 **Paste in agent terminal!**
                    
                    The note will include:
                    - Paper metadata (ID, title, authors)
                    - Abstract and key sections
                    - Your analysis on: {analysis_topic}
                    - Methods, findings, and discussion
                    - Structured for knowledge base links
                    """)

# Footer
st.divider()
st.markdown("""
---
### 💡 Quick Start Guide

1. **Search Papers**: Use the Search tab to find papers on any topic
2. **Download**: Use the Download tab to get papers (with or without approval)
3. **Read**: Extract text from downloaded papers in the Read tab
4. **Create Notes**: Generate Obsidian notes in the Create Note tab

### ⚡ Pro Tips

- Use the **Agent Terminal** to execute commands (this is the primary interface)
- This GUI acts as a **command builder** and **status dashboard**
- All actual processing happens in the agent terminal
- Check the sidebar for downloaded papers and created notes

### 📞 Support

For issues or questions:
- Check Ollama is running: `ollama serve` or `$env:OLLAMA_GPU_DISABLED=1; ollama serve`
- Review README.md for more information
- Check agent terminal for detailed logs
""")
