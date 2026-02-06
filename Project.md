Project Architecture (Privacy-Focused)


Copy
MCP Host (Local LLM)
    ↓
MCP Client
    ↓
├─ ArXiv Server ── Searches, downloads, analyzes papers
├─ PDF Parser ── Extracts text and metadata from PDFs
└─ Obsidian Server ── Manages notes, tags, and knowledge graph
This leverages the Model Context Protocol as the "nervous system" connecting your LLM to external research tools .
Phase 1: Foundation Setup (Get all servers running)

Step 1: Local LLM & MCP Host

bash

Copy
# Install Ollama and start with a capable model
curl https://ollama.ai/install.sh | sh
ollama pull llama3.1  # 8B is good for start, 70B for better reasoning
MCP Host: Use Claude Desktop or AnythingLLM  as your interface.
Step 2: ArXiv MCP Server

Use the well-maintained community server :
bash

Copy
# Clone and install
git clone https://github.com/kelvingao/arxiv-mcp.git
cd arxiv-mcp
pip install uv
uv pip install -e .

# Configure in MCP host (claude_desktop_config.json)
{
  "mcpServers": {
    "arxiv": {
      "command": "python",
      "args": ["/path/to/arxiv-mcp/server.py"]
    }
  }
}
Key Tools Available :
search_papers: Advanced search with filters
download_paper: Converts PDF to markdown
read_paper: Read locally stored papers
list_papers: Browse downloaded research
Step 3: Obsidian MCP Server

Use the cyanheads implementation :
bash

Copy
# Install via npm
npm install -g obsidian-mcp-server

# Prerequisites: Enable "Local REST API" plugin in Obsidian settings
# Get your API key from Obsidian → Settings → Local REST API
Configuration :
JSON

Copy
{
  "mcpServers": {
    "obsidian": {
      "command": "obsidian-mcp-server",
      "env": {
        "OBSIDIAN_API_KEY": "your-api-key-here",
        "OBSIDIAN_PORT": "27123"
      }
    }
  }
}
Core Tools :
obsidian_read_note: Retrieve note content
obsidian_update_note: Add/append content
obsidian_global_search: Search your entire vault
obsidian_manage_frontmatter: Add tags, properties
obsidian_manage_tags: Link notes together
Step 4: PDF Parsing Server (Optional Enhancement)

If you need advanced PDF analysis beyond the ArXiv server's built-in extraction, create a dedicated server:
Python

Copy
from fastmcp import FastMCP
import PyPDF2
import fitz  # PyMuPDF

mcp = FastMCP("PDFParser")

@mcp.tool()
def extract_pdf_sections(pdf_path: str) -> dict:
    """Extract abstract, introduction, methods, etc."""
    doc = fitz.open(pdf_path)
    # Implementation for section extraction
    return {"abstract": "...", "figures": [...]}

@mcp.tool()
def extract_figures(pdf_path: str) -> list:
    """Extract figures and charts as images"""
    # Save figures to local folder
    return ["figure1.png", "figure2.png"]
Phase 2: Agentic Workflow (Build automation)

Now create a Research Assistant Agent that autonomously performs literature reviews.
Workflow: "Weekly Research Digest"

Goal: Automatically find recent papers, analyze them, and create structured notes.
Agentic Prompt Template :
Python

Copy
@mcp.prompt()
def research_digest():
    return """You are a research assistant. Perform a weekly literature review:

1. SEARCH: Use arxiv.search_papers with keywords from my research interests
2. FILTER: Select 5-7 most relevant papers based on abstract analysis
3. DOWNLOAD: Download selected papers locally
4. ANALYZE: Extract key findings, methods, and limitations
5. NOTE-CREATE: Create structured notes in Obsidian for each paper
6. CONNECT: Link notes to existing research in my vault
7. SUMMARIZE: Create a weekly digest note with all findings

Always ask for confirmation before downloading more than 3 papers."""

# Register this prompt in your MCP host
Example Execution Flow:

Copy
User: "Research recent papers on 'multi-agent reinforcement learning'"

Agent:
  → Calls arxiv.search_papers(query="ti:'multi-agent' AND ti:'reinforcement'", max_results=10)
  → Analyzes results (reasoning step)
  → Calls arxiv.download_paper for top 3 papers
  → Reads downloaded markdown
  → Calls obsidian_update_note for each paper
  → Calls obsidian_manage_frontmatter to add tags: ["research", "MARL", "2025-W1"]
  → Creates [[Weekly Digest]] note with links to all papers
Phase 3: Production Features (Make it reliable)

1. Human-in-the-Loop Approval

Python

Copy
@mcp.tool()
def confirm_download(paper_title: str, abstract: str) -> bool:
    """Ask user before downloading paper"""
    print(f"Download: {paper_title}?")
    print(f"Abstract: {abstract[:200]}...")
    return input("(y/n): ").lower() == 'y'
This addresses the "human approval" pattern crucial for production agents .
2. Logging & Evaluation

Python

Copy
# Add to your ArXiv server
@mcp.tool()
def log_research_action(action: str, paper_id: str, result: str):
    """Log all agent actions for evaluation"""
    with sqlite3.connect("research_log.db") as conn:
        conn.execute("""
            INSERT INTO actions (timestamp, action, paper_id, result)
            VALUES (?, ?, ?, ?)
        """, (datetime.now(), action, paper_id, result))

# Evaluate metrics:
# - Download accuracy (relevant papers / total downloads)
# - Note quality (human rating)
# - Tool success rate
3. Caching & Rate Limiting

Python

Copy
# Cache downloaded papers to avoid re-downloading
@mcp.resource("data://downloaded_papers")
def get_local_papers() -> list:
    """Expose local paper cache to LLM"""
    return os.listdir("papers/")

# Implement rate limiting for arXiv API (3s delay between requests)
4. Error Handling & Recovery

Python

Copy
@mcp.tool()
def safe_paper_download(arxiv_id: str) -> dict:
    """Wrap download with error handling"""
    try:
        return download_paper(arxiv_id)
    except RateLimitError:
        return {"error": "Rate limited. Try again in 30 seconds."}
    except PDFNotFoundError:
        return {"error": "Paper not available in PDF format."}
Complete MCP Configuration

JSON

Copy
{
  "mcpServers": {
    "arxiv": {
      "command": "python",
      "args": ["/path/to/arxiv/server.py"],
      "env": {"PAPER_STORAGE": "~/papers"}
    },
    "obsidian": {
      "command": "obsidian-mcp-server",
      "env": {
        "OBSIDIAN_API_KEY": "your-key",
        "OBSIDIAN_PORT": "27123",
        "DEFAULT_FOLDER": "Research/Incoming"
      }
    },
    "pdf_tools": {
      "command": "python",
      "args": ["/path/to/pdf_parser.py"]
    }
  }
}
Example Agent Session

User Prompt: "Find recent papers on LLM agents published in the last month, then create a literature review note in Obsidian."
Agent's Autonomous Workflow:
Search: arxiv.search_papers(query="LLM agents", date_from="2024-12-01", max_results=15)
Analyze: Reviews abstracts, filters for relevance
Download: Downloads top 5 papers (asks confirmation)
Parse: Extracts key sections from PDFs
Note Creation: For each paper:

---
title: "LLM Agent Survey 2025"
authors: [Smith, Jones]
tags: [llm, agents, survey, 2025-W3]
arxiv_id: "2501.12345"
---

# [[LLM Agent Survey 2025]]

## Key Findings
- Finding 1...

## Methods
- Methodology...

## Related Work
Links to [[Paper A]], [[Paper B]] in my vault

Connect: Uses obsidian_global_search to find related notes
Summarize: Creates [[Literature Review LLM Agents 2025]] with all connections
Evaluation Checklist

Track these metrics to measure your agent's effectiveness :

etric	How to Measure
Search Precision	# relevant papers / # total papers downloaded
Note Quality	Human rating 1-5 of generated notes
Connection Accuracy	% of correctly linked related papers
Tool Success Rate	% of successful tool calls vs errors
Human Interventions	How often approval is needed

Advanced Enhancements

Knowledge Graph Builder: Automatically create [[wikilinks]] between related papers
Custom Prompt Templates: Pre-built prompts for different research tasks 
Multi-agent Workflow: Separate agents for search, analysis, and writing 
Semantic Search: Add vector embeddings for better paper similarity matching
Docker Deployment: Containerize all servers for easy sharing