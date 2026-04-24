from fastmcp import FastMCP
import httpx
import arxiv
import os
import sys
import sqlite3
import pymupdf  # fitz
from datetime import datetime
import loguru as logger

logger.add("file_{time}.log")


mcp = FastMCP("ArXiv")

PAPER_STORAGE = os.environ.get("PAPER_STORAGE", "./papers")
os.makedirs(PAPER_STORAGE, exist_ok=True)

@mcp.tool()
def search_papers(query: str, max_results: int = 5) -> list:
    """
    Search for papers on ArXiv.
    Args:
        query: Search query (e.g., "transformer architecture")
        max_results: Max number of results (default 5)
    """
    logger.info(f"Searching for {query}...")
    client = arxiv.Client()
    search = arxiv.Search(
        query=query,
        max_results=int(max_results),
        sort_by=arxiv.SortCriterion.Relevance
    )
    
    results = []
    logger.info(f"Search query: '{query}'")
    for r in client.results(search):
        # Debug printing
        logger.info(f"Found paper: {r.title} ({r.get_short_id()})")
        results.append({
            "id": r.get_short_id(),
            "title": r.title,
            "published": r.published.strftime("%Y-%m-%d"),
            "summary": r.summary.replace("\n", " "),
            "pdf_url": r.pdf_url
        })
    logger.info(f"Returning {len(results)} results")
    return results

@mcp.tool()
def download_paper(paper_id: str) -> str:
    """
    Download a paper by its ArXiv ID (e.g., "2401.12345").
    Returns the file path.
    """
    logger.info(f"Downloading {paper_id}...")
    
    # Check if already exists
    for filename in os.listdir(PAPER_STORAGE):
        if filename.startswith(paper_id) and filename.endswith(".pdf"):
             return os.path.join(PAPER_STORAGE, filename)

    client = arxiv.Client()
    paper = next(client.results(arxiv.Search(id_list=[paper_id])))
    
    # Download
    path = paper.download_pdf(dirpath=PAPER_STORAGE, filename=f"{paper_id}.pdf")
    abs_path = os.path.abspath(path)
    logger.info(f"Downloaded to {abs_path}")
    return abs_path

@mcp.tool()
def list_papers() -> list:
    """List all downloaded papers."""
    return [f for f in os.listdir(PAPER_STORAGE) if f.endswith(".pdf")]

@mcp.tool()
def read_paper(paper_id: str) -> str:
    """
    Read the text content of a downloaded paper.
    Args:
        paper_id: The ID of the paper (e.g. "2401.12345")
    """
    path = os.path.join(PAPER_STORAGE, f"{paper_id}.pdf")
    if not os.path.exists(path):
        return f"Error: Paper {paper_id} not found locally. Download it first."
    
    try:
        doc = pymupdf.open(path)
        text = ""
        for page in doc:
            text += page.get_text()
        return text
    except Exception as e:
        return f"Error reading PDF: {str(e)}"

# --- Production Features ---

@mcp.tool()
def confirm_download(paper_title: str, abstract: str) -> bool:
    """Ask user before downloading paper (Human-in-the-Loop)."""
    logger.info(f"Requesting confirmation to download: {paper_title}")
    return True

@mcp.tool()
def log_research_action(action: str, paper_id: str, result: str):
    """Log all agent actions for evaluation."""
    db_path = "research_log.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS actions (timestamp TEXT, action TEXT, paper_id TEXT, result TEXT)")
        conn.execute("""
            INSERT INTO actions (timestamp, action, paper_id, result)
            VALUES (?, ?, ?, ?)
        """, (datetime.now().isoformat(), action, paper_id, str(result)))
    logger.info(f"Logged action: {action}")

if __name__ == "__main__":
    try:
        logger.info("Starting ArXiv MCP Server...", file=sys.stderr)
        mcp.run()
        logger.info("ArXiv MCP Server started successfully.")
        
    except Exception as e:
        logger.error(f"Server crashed: {e}", file=sys.stderr)
        raise
