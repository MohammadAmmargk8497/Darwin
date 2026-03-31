from fastmcp import FastMCP
import httpx
import arxiv
import os
import sqlite3
import pymupdf  # fitz
from datetime import datetime
import logging

logging.basicConfig(level=logging.INFO)


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
    logging.info(f"Searching for {query}...")
    client = arxiv.Client()
    search = arxiv.Search(
        query=query,
        max_results=int(max_results),
        sort_by=arxiv.SortCriterion.Relevance
    )

    results = []
    logging.info(f"Search query: '{query}'")
    for r in client.results(search):
        # Debug printing
        logging.info(f"Found paper: {r.title} ({r.get_short_id()})")
        results.append({
            "id": r.get_short_id(),
            "title": r.title,
            "published": r.published.strftime("%Y-%m-%d"),
            "summary": r.summary.replace("\n", " "),
            "pdf_url": r.pdf_url
        })
    logging.info(f"Returning {len(results)} results")
    return results

@mcp.tool()
def download_paper(paper_id: str) -> str:
    """
    Download a paper by its ArXiv ID (e.g., "2401.12345").
    Returns the file path.
    """
    logging.info(f"Downloading {paper_id}...")

    # Check if already exists
    for filename in os.listdir(PAPER_STORAGE):
        if filename.startswith(paper_id) and filename.endswith(".pdf"):
             return os.path.join(PAPER_STORAGE, filename)

    client = arxiv.Client()
    paper = next(client.results(arxiv.Search(id_list=[paper_id])))

    # Download
    path = paper.download_pdf(dirpath=PAPER_STORAGE, filename=f"{paper_id}.pdf")
    abs_path = os.path.abspath(path)
    logging.info(f"Downloaded to {abs_path}")
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
def confirm_download(paper_title: str, paper_id: str, published_date: str, abstract: str) -> dict:
    """
    Prepare paper download confirmation data (Human-in-the-Loop).
    Returns paper details for user review before download approval.
    
    Args:
        paper_title: Full title of the paper
        paper_id: ArXiv ID
        published_date: Publication date
        abstract: Paper abstract (will be truncated for display)
    """
    logging.info(f"Preparing confirmation for download: {paper_title}")
    
    # Create paper information response
    abstract_preview = abstract[:300] + "..." if len(abstract) > 300 else abstract
    
    return {
        "status": "awaiting_confirmation",
        "paper_id": paper_id,
        "paper_title": paper_title,
        "published_date": published_date,
        "abstract_preview": abstract_preview,
        "message": f"PAPER DOWNLOAD CONFIRMATION\n\nTitle: {paper_title}\nPaper ID: {paper_id}\nPublished: {published_date}\n\nAbstract Preview:\n{abstract_preview}\n\nRespond with 'yes' to download, 'no' to skip, or 'skip' to move to next paper."
    }

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
    logging.info(f"Logged action: {action}")

if __name__ == "__main__":
    try:
        logging.info("Starting ArXiv MCP Server...")
        mcp.run()

    except Exception as e:
        logging.error(f"Server crashed: {e}")
        raise
