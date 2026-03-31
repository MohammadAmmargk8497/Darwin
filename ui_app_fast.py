import streamlit as st
import asyncio
import json
import os
import sys
from pathlib import Path
from datetime import datetime
import requests

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
    .loading-message { background-color: #cfe2ff; padding: 15px; border-radius: 5px; color: #084298; }
</style>
""", unsafe_allow_html=True)

# Initialize session state
if "initialized" not in st.session_state:
    st.session_state.initialized = False
    st.session_state.mcp_client = None
    st.session_state.ollama_client = None
    st.session_state.papers = []
    st.session_state.search_results = []

# Check Ollama connection
def check_ollama():
    """Check if Ollama is running"""
    try:
        response = requests.get("http://localhost:11434/api/tags", timeout=3)
        return response.status_code == 200
    except:
        return False

# Header
st.markdown("<h1 class='main-header'>🧬 Darwin Research Agent</h1>", unsafe_allow_html=True)
st.markdown("Your intelligent research assistant for ArXiv papers with Obsidian integration")

# Sidebar
with st.sidebar:
    st.title("⚙️ System Status")
    
    ollama_running = check_ollama()
    
    if ollama_running:
        st.success("✅ Ollama Online")
    else:
        st.error("❌ Ollama Offline")
        st.warning("""
        **Ollama is not running!**
        
        Start it with:
        ```powershell
        $env:OLLAMA_GPU_DISABLED=1; ollama serve
        ```
        """)
    
    st.divider()
    
    with st.expander("📋 Downloaded Papers"):
        papers_path = Path("papers")
        if papers_path.exists():
            papers = list(papers_path.glob("*.pdf"))
            if papers:
                for paper in papers:
                    st.text(f"📄 {paper.name}")
                st.caption(f"Total: {len(papers)} papers")
            else:
                st.info("No papers downloaded yet")
    
    with st.expander("📚 Obsidian Notes"):
        notes_path = Path("Darwin Research/Research/Incoming")
        if notes_path.exists():
            notes = list(notes_path.glob("*.md"))
            if notes:
                for note in notes:
                    st.text(f"📝 {note.name}")
                st.caption(f"Total: {len(notes)} notes")
            else:
                st.info("No notes created yet")

# Main Content
if not ollama_running:
    st.error("🚨 **Ollama is not running!**")
    st.markdown("""
    ### Start Ollama First
    
    Open a terminal and run:
    ```powershell
    $env:OLLAMA_GPU_DISABLED=1; ollama serve
    ```
    
    Then refresh this page.
    """)
    st.stop()

# Create tabs
tab1, tab2, tab3, tab4 = st.tabs(["🔍 Search", "📥 Download", "📖 Read", "📝 Create Note"])

# TAB 1: Search
with tab1:
    st.subheader("🔍 Search ArXiv Papers")
    
    col1, col2 = st.columns([3, 1])
    with col1:
        search_topic = st.text_input(
            "Search topic",
            placeholder="e.g., machine learning, transformers"
        )
    with col2:
        max_results = st.number_input("Max", min_value=1, max_value=50, value=5)
    
    if st.button("🔍 Search", use_container_width=True):
        if search_topic:
            st.markdown("<div class='loading-message'>⏳ Searching... this may take 30 seconds</div>", unsafe_allow_html=True)
            
            try:
                # Try direct curl to arxiv (simpler alternative)
                import subprocess
                
                # Create a simple Python script to search (avoids MCP complexity)
                search_cmd = f"""
import arxiv
results = arxiv.Client().results(arxiv.Search(query='{search_topic}', max_results={int(max_results)}, sort_by=arxiv.SortCriterion.SubmittedDate))
import json
papers = []
for paper in results:
    papers.append({{'id': paper.entry_id.split('/abs/')[-1], 'title': paper.title, 'published': paper.published.strftime('%Y-%m-%d'), 'summary': paper.summary[:200]}})
print(json.dumps(papers))
"""
                
                result = subprocess.run([sys.executable, "-c", search_cmd], capture_output=True, text=True, timeout=30)
                
                if result.returncode == 0:
                    try:
                        papers = json.loads(result.stdout)
                        st.session_state.search_results = papers
                        st.success(f"✅ Found {len(papers)} papers!")
                    except json.JSONDecodeError:
                        st.error("Failed to parse results")
                else:
                    st.error(f"Search failed: {result.stderr}")
                    
            except Exception as e:
                st.error(f"❌ Error: {str(e)}")
    
    # Display results
    if st.session_state.search_results:
        st.divider()
        for i, paper in enumerate(st.session_state.search_results, 1):
            with st.container():
                st.markdown(f"<div class='paper-card'>", unsafe_allow_html=True)
                st.write(f"**{i}. {paper.get('title', 'Unknown')}**")
                col1, col2 = st.columns(2)
                with col1:
                    st.caption(f"🆔 {paper.get('id', 'Unknown')}")
                with col2:
                    st.caption(f"📅 {paper.get('published', 'Unknown')}")
                st.write(f"_{paper.get('summary', 'No summary')}..._")
                st.markdown("</div>", unsafe_allow_html=True)

# TAB 2: Download
with tab2:
    st.subheader("📥 Download Papers")
    
    col1, col2 = st.columns([2, 1])
    with col1:
        paper_id = st.text_input("Paper ID", placeholder="2306.04338v1")
    with col2:
        auto_mode = st.checkbox("Auto-approve", value=False)
    
    if st.button("📥 Download", use_container_width=True):
        if paper_id:
            paper_id = paper_id.strip()
            st.markdown("<div class='loading-message'>⏳ Downloading...</div>", unsafe_allow_html=True)
            
            try:
                import subprocess
                
                # Use simple subprocess to download
                download_cmd = f"""
import arxiv
import requests
import os

# Get paper
paper = next(arxiv.Client().results(arxiv.Search(paper_id='{paper_id}', max_results=1)))
pdf_url = paper.pdf_url

# Download
os.makedirs('papers', exist_ok=True)
filename = f'papers/{paper_id}.pdf'
response = requests.get(pdf_url)
with open(filename, 'wb') as f:
    f.write(response.content)
print(f'SUCCESS: {{filename}}')
"""
                
                result = subprocess.run([sys.executable, "-c", download_cmd], capture_output=True, text=True, timeout=60)
                
                if "SUCCESS" in result.stdout:
                    st.success(f"✅ Downloaded: {paper_id}.pdf")
                else:
                    st.error(f"Download failed: {result.stderr}")
                    
            except Exception as e:
                st.error(f"❌ Error: {str(e)}")

# TAB 3: Read
with tab3:
    st.subheader("📖 Read Paper Content")
    
    paper_id = st.text_input("Paper ID", placeholder="2306.04338v1", key="read_id")
    
    if st.button("📖 Read", use_container_width=True):
        if paper_id:
            paper_id = paper_id.strip()
            st.markdown("<div class='loading-message'>⏳ Reading paper...</div>", unsafe_allow_html=True)
            
            try:
                pdf_path = Path(f"papers/{paper_id}.pdf")
                
                if not pdf_path.exists():
                    st.error(f"❌ Paper not found: {pdf_path}")
                else:
                    # Use PyPDF2 to read
                    import subprocess
                    
                    read_cmd = f"""
from PyPDF2 import PdfReader
pdf = PdfReader('{pdf_path}')
text = ''
for page in pdf.pages:
    text += page.extract_text()
print(text[:5000])
"""
                    
                    result = subprocess.run([sys.executable, "-c", read_cmd], capture_output=True, text=True, timeout=30)
                    
                    if result.returncode == 0:
                        with st.expander("📄 Paper Text (first 5000 chars)", expanded=True):
                            st.text_area("Content:", value=result.stdout, height=400, disabled=True)
                    else:
                        st.error(f"Failed to read: {result.stderr}")
                        
            except Exception as e:
                st.error(f"❌ Error: {str(e)}")

# TAB 4: Create Note
with tab4:
    st.subheader("📝 Create Research Note")
    
    note_type = st.radio("Type", ["Generic Note", "Paper Note"], horizontal=True)
    
    if note_type == "Generic Note":
        title = st.text_input("Title", placeholder="ML Trends")
        content = st.text_area("Content", placeholder="Your notes...", height=150)
        tags = st.text_input("Tags", placeholder="research, ml, 2024")
        
        if st.button("📝 Create", use_container_width=True):
            if title and content:
                try:
                    os.makedirs("Darwin Research/Research/Incoming", exist_ok=True)
                    
                    filename = f"Darwin Research/Research/Incoming/{title.replace(' ', '_')}.md"
                    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
                    
                    note_text = f"""---
title: {title}
created: {datetime.now().isoformat()}
tags: {json.dumps(tag_list)}
type: research-note
---

# {title}

## Overview
{content}

## Key Points
- Point 1
- Point 2
- Point 3

## Analysis
Add detailed analysis here.

## References
- Add sources here

## Last Updated
{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
                    
                    with open(filename, 'w', encoding='utf-8') as f:
                        f.write(note_text)
                    
                    st.success(f"✅ Created: {title}")
                    
                except Exception as e:
                    st.error(f"❌ Failed: {str(e)}")
    
    else:
        paper_id = st.text_input("Paper ID", placeholder="2306.04338v1", key="paper_note_id")
        analysis = st.text_area("Analysis", placeholder="Your analysis...", height=150)
        
        if st.button("📝 Create Paper Note", use_container_width=True):
            if paper_id and analysis:
                try:
                    os.makedirs("Darwin Research/Research/Incoming", exist_ok=True)
                    
                    filename = f"Darwin Research/Research/Incoming/{paper_id}.md"
                    
                    note_text = f"""---
title: Analysis of {paper_id}
paper_id: {paper_id}
created: {datetime.now().isoformat()}
tags: ["paper", "research"]
type: research-paper
---

# Paper Analysis: {paper_id}

## Paper ID
{paper_id}

## Your Analysis
{analysis}

## Key Findings
- Finding 1
- Finding 2

## Discussion
Add discussion here.

## References
- Link to paper

## Last Updated
{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
                    
                    with open(filename, 'w', encoding='utf-8') as f:
                        f.write(note_text)
                    
                    st.success(f"✅ Created: Paper note for {paper_id}")
                    
                except Exception as e:
                    st.error(f"❌ Failed: {str(e)}")

st.divider()
st.markdown("**💡 Tip:** If search is slow, make sure Ollama is running with: `$env:OLLAMA_GPU_DISABLED=1; ollama serve`")
