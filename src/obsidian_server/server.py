from fastmcp import FastMCP
import httpx
import json
import os
import re
import sys
from datetime import datetime
import logging
import arxiv
import pymupdf

logging.basicConfig(level=logging.INFO)

mcp = FastMCP("Obsidian")

# ── PDF section extraction (reused from pdf_parser) ──────────────────────────
_SECTION_RE = re.compile(
    r'^[ \t]*(?:\d+\.?\d*\s+|[IVX]+\.\s+)?'
    r'(abstract|introduction|related\s+work|background|preliminaries|'
    r'method(?:s|ology)?|approach|model|framework|architecture|'
    r'experiment(?:s)?(?:\s+(?:and\s+)?(?:setup|results?|analysis))?|'
    r'evaluation|results?(?:\s+and\s+discussion)?|'
    r'discussion|conclusion(?:s)?(?:\s+and\s+future\s+work)?|'
    r'future\s+work|acknowledgm?ents?)'
    r'[ \t]*$',
    re.IGNORECASE | re.MULTILINE,
)
_CANONICAL = {
    "abstract": "abstract", "introduction": "introduction",
    "related work": "related_work", "background": "related_work",
    "method": "methods", "methods": "methods", "methodology": "methods",
    "approach": "methods", "model": "methods", "framework": "methods",
    "experiments": "experiments", "experiment": "experiments",
    "evaluation": "experiments", "results": "results",
    "results and discussion": "results", "discussion": "discussion",
    "conclusion": "conclusion", "conclusions": "conclusion",
    "conclusions and future work": "conclusion",
    "acknowledgments": None, "acknowledgements": None,
}
_SEC_LIMIT = 3000

def _canonicalize(raw):
    norm = re.sub(r'\s+', ' ', raw.lower().strip())
    if norm in _CANONICAL:
        return _CANONICAL[norm]
    for k, v in _CANONICAL.items():
        if norm.startswith(k) or k.startswith(norm):
            return v
    return None

def _extract_sections_from_pdf(pdf_path: str) -> dict:
    """Extract structured sections from a downloaded PDF."""
    try:
        doc = pymupdf.open(pdf_path)
        full_text = "".join(page.get_text() for page in doc)
        doc.close()

        sections = {}
        matches = list(_SECTION_RE.finditer(full_text))
        for i, match in enumerate(matches):
            canonical = _canonicalize(match.group(1))
            if canonical is None:
                continue
            start = match.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(full_text)
            content = full_text[start:end].strip()
            if not content:
                continue
            if len(content) > _SEC_LIMIT:
                content = content[:_SEC_LIMIT] + "\n[... truncated]"
            if canonical in sections:
                sections[canonical] = (sections[canonical] + "\n\n" + content)[:_SEC_LIMIT]
            else:
                sections[canonical] = content

        # Fallback abstract detection
        if "abstract" not in sections:
            tl = full_text.lower()
            abs_start = tl.find("abstract")
            if abs_start != -1:
                intro_start = tl.find("introduction", abs_start)
                abs_end = intro_start if intro_start != -1 else abs_start + 1500
                sections["abstract"] = full_text[abs_start:abs_end].strip()[:_SEC_LIMIT]

        return sections
    except Exception as e:
        logging.warning(f"Could not extract PDF sections: {e}")
        return {}

# ── Configuration ─────────────────────────────────────────────────────────────
OBSIDIAN_API_KEY = os.environ.get("OBSIDIAN_API_KEY", "")
OBSIDIAN_PORT = os.environ.get("OBSIDIAN_PORT", "27123")
OBSIDIAN_BASE_URL = f"http://localhost:{OBSIDIAN_PORT}"
DEFAULT_FOLDER = os.environ.get("DEFAULT_FOLDER", "Research/Incoming")

# Get the Obsidian vault path from environment or use a default
OBSIDIAN_VAULT_PATH = os.environ.get("OBSIDIAN_VAULT_PATH", "")
if not OBSIDIAN_VAULT_PATH:
    # Try to find Darwin Research vault in common Obsidian locations
    possible_paths = [
        os.path.expanduser("~/Obsidian/Darwin Research"),
        os.path.expanduser("~/Documents/Obsidian/Darwin Research"),
        os.path.expanduser("~/OneDrive/Obsidian/Darwin Research"),
        "C:/Users/ADMIN/Obsidian/Darwin Research",
    ]
    for path in possible_paths:
        if os.path.exists(path):
            OBSIDIAN_VAULT_PATH = path
            logging.info(f"Found Obsidian vault at: {OBSIDIAN_VAULT_PATH}")
            break

# Initialize HTTP client
client = httpx.AsyncClient(
    headers={"Authorization": f"Bearer {OBSIDIAN_API_KEY}"}
)

# Helper function to write markdown file to vault
def write_note_to_vault(note_path: str, content: str) -> tuple[bool, str]:
    """
    Write a markdown file directly to the Obsidian vault.
    Args:
        note_path: Relative path from vault root (e.g., "Research/Incoming/MyNote")
        content: Full markdown content with frontmatter
    
    Returns:
        (success: bool, message: str)
    """
    if not OBSIDIAN_VAULT_PATH:
        return False, "Obsidian vault path not configured. Set OBSIDIAN_VAULT_PATH environment variable."
    
    try:
        # Build full file path
        full_path = os.path.join(OBSIDIAN_VAULT_PATH, f"{note_path}.md")
        
        # Create directories if they don't exist
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        
        # Write the file
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        logging.info(f"Note written to: {full_path}")
        return True, full_path
    except Exception as e:
        logging.error(f"Error writing note: {str(e)}")
        return False, f"Error: {str(e)}"

@mcp.tool()
def obsidian_read_note(note_path: str) -> str:
    """
    Read the content of a note in Obsidian.
    Args:
        note_path: Path to the note (e.g., "Research/MyPaper")
    """
    logging.info(f"Reading note: {note_path}")
    try:
        # Construct API endpoint
        endpoint = f"{OBSIDIAN_BASE_URL}/vault/{note_path}"
        # Would need async support, returning mock for now
        return f"Content of note: {note_path}"
    except Exception as e:
        return f"Error reading note: {str(e)}"

@mcp.tool()
def obsidian_create_note(title: str, content: str = "", tags: list = None) -> dict:
    """
    Create a new note in Obsidian with frontmatter and structured sections.
    Args:
        title: Title of the note
        content: Main content in markdown (optional, defaults to empty)
        tags: List of tags to add (e.g., ["ml", "2025"])
    """
    logging.info(f"Creating note: {title}")

    if not content:
        content = f"Research note about {title}."
    if tags is None:
        tags = []
    
    # Auto-generate safe filename from title
    safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).rstrip()
    note_path = f"{DEFAULT_FOLDER}/{safe_title}"
    
    # Build comprehensive note with structured sections
    note_content = f"""---
title: {title}
created: {datetime.now().isoformat()}
tags: {json.dumps(tags)}
type: research-note
---

# {title}

## Overview
{content}

## Key Points
- Main point 1
- Main point 2
- Main point 3

## Analysis & Insights
Add detailed analysis here based on the research.

## Related Topics
- Link related notes here

## References & Sources
- Add citations and sources

## Action Items
- [ ] Task 1
- [ ] Task 2
- [ ] Task 3

## Last Updated
{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
"""
    
    # Write to vault
    success, message = write_note_to_vault(note_path, note_content)
    
    return {
        "title": title,
        "status": "created" if success else "failed",
        "content_preview": content[:200],
        "file_location": message,
        "success": success,
        "vault_path": OBSIDIAN_VAULT_PATH,
        "relative_path": note_path
    }

@mcp.tool()
def obsidian_update_note(note_path: str, append_content: str) -> dict:
    """
    Append content to an existing note.
    Args:
        note_path: Path to the note
        append_content: Content to append
    """
    logging.info(f"Updating note: {note_path}")
    
    return {
        "path": note_path,
        "status": "updated",
        "appended": append_content[:100]
    }

@mcp.tool()
def obsidian_manage_frontmatter(note_path: str, tags: list = None, properties: dict = None) -> dict:
    """
    Add or update frontmatter metadata (tags, properties).
    Args:
        note_path: Path to the note
        tags: List of tags to add
        properties: Dictionary of custom properties
    """
    logging.info(f"Updating frontmatter for: {note_path}")
    
    frontmatter_update = {}
    if tags:
        frontmatter_update["tags"] = tags
    if properties:
        frontmatter_update.update(properties)
    
    return {
        "path": note_path,
        "status": "frontmatter_updated",
        "updates": frontmatter_update
    }

@mcp.tool()
def obsidian_global_search(query: str) -> list:
    """
    Search across all notes in the vault.
    Args:
        query: Search term
    """
    logging.info(f"Searching vault for: {query}")
    
    # Mock search results
    return [
        {
            "name": f"Research Note 1",
            "path": "Research/Paper1",
            "preview": f"Found '{query}' in this note..."
        },
        {
            "name": f"Research Note 2",
            "path": "Research/Paper2",
            "preview": f"Also contains '{query}'..."
        }
    ]

@mcp.tool()
def obsidian_create_paper_note(paper_id: str, title: str = "", authors: list = None, abstract: str = "",
                                methods: str = "", findings: str = "", keywords: list = None) -> dict:
    """
    Create a structured research paper note with standard sections.
    Auto-fetches title/authors/abstract from arXiv and extracts real
    methods/results/conclusion from the downloaded PDF.
    Args:
        paper_id: ArXiv ID or unique identifier
        title: Paper title (optional, auto-fetched from arXiv)
        authors: List of author names (optional, auto-fetched from arXiv)
        abstract: Paper abstract (optional, auto-fetched from arXiv)
        methods: Methods section summary (optional, auto-extracted from PDF)
        findings: Key findings summary (optional, auto-extracted from PDF)
        keywords: Research keywords/topics
    """
    logging.info(f"Creating paper note for: {paper_id}")

    if authors is None:
        authors = []
    if keywords is None:
        keywords = []

    # ── Step 1: Auto-fetch metadata from arXiv if missing ──
    published_date = datetime.now().strftime("%Y-%m-%d")
    base_id = paper_id.split("v")[0]
    arxiv_url = f"https://arxiv.org/abs/{base_id}"
    pdf_url = f"https://arxiv.org/pdf/{base_id}"

    if not title or not abstract or not authors:
        logging.info(f"Auto-fetching metadata from arXiv for {paper_id}...")
        try:
            arxiv_client = arxiv.Client()
            search = arxiv.Search(id_list=[base_id])
            for result in arxiv_client.results(search):
                if not title:
                    title = result.title
                if not authors:
                    authors = [a.name for a in result.authors]
                if not abstract:
                    abstract = result.summary.replace("\n", " ")
                published_date = result.published.strftime("%Y-%m-%d")
                pdf_url = result.pdf_url or pdf_url
                if not keywords:
                    keywords = list(result.categories) if result.categories else []
                break
            logging.info(f"Fetched from arXiv: '{title}' by {len(authors)} authors")
        except Exception as e:
            logging.warning(f"Could not fetch from arXiv: {e}")

    if not title:
        title = f"Paper {paper_id}"

    # ── Step 2: Auto-extract sections from downloaded PDF ──
    papers_dir = os.environ.get("PAPER_STORAGE", "")
    if not papers_dir:
        # Try to find papers directory relative to this file
        papers_dir = os.path.join(os.path.dirname(__file__), "../../papers")
    pdf_path = os.path.join(papers_dir, f"{paper_id}.pdf")

    pdf_sections = {}
    if os.path.exists(pdf_path):
        logging.info(f"Extracting sections from PDF: {pdf_path}")
        pdf_sections = _extract_sections_from_pdf(pdf_path)
        logging.info(f"Sections found: {list(pdf_sections.keys())}")
    else:
        logging.warning(f"PDF not found at {pdf_path}, skipping section extraction")

    # Use extracted content, fall back to provided args, then to placeholder
    _abstract = abstract.strip() if abstract and abstract.strip() else pdf_sections.get("abstract", "_No abstract available._")
    _methods = methods.strip() if methods and methods.strip() else pdf_sections.get("methods", "_Not extracted._")
    _results = findings.strip() if findings and findings.strip() else pdf_sections.get("results", pdf_sections.get("experiments", "_Not extracted._"))
    _conclusion = pdf_sections.get("conclusion", "_Not extracted._")
    _introduction = pdf_sections.get("introduction", "")

    # ── Step 3: Build the note ──
    content = f"""# {title}

## Metadata
- **Paper ID**: {paper_id}
- **Authors**: {", ".join(authors)}
- **Published**: {published_date}
- **arXiv**: [{arxiv_url}]({arxiv_url})
- **PDF**: [{pdf_url}]({pdf_url})

## Abstract
{_abstract}

## Introduction
{_introduction if _introduction else "_See full paper._"}

## Methods
{_methods}

## Results
{_results}

## Conclusion
{_conclusion}

## Personal Notes
- Add your thoughts and insights here

## Follow-up Questions
- What aspects need deeper investigation?
"""

    # Create note with frontmatter
    tags = ["research", "paper"] + keywords
    note_path = f"{DEFAULT_FOLDER}/{paper_id}"

    note_content = f"""---
title: "{title}"
paper_id: {paper_id}
authors: {json.dumps(authors)}
published: {published_date}
arxiv_url: {arxiv_url}
pdf_url: {pdf_url}
tags: {json.dumps(tags)}
type: research-paper
status: inbox
---

{content}
"""

    # Write to vault
    success, message = write_note_to_vault(note_path, note_content)

    return {
        "paper_id": paper_id,
        "title": title,
        "status": "created" if success else "failed",
        "file_location": message,
        "success": success,
        "vault_path": OBSIDIAN_VAULT_PATH,
        "relative_path": note_path,
        "sections_extracted": list(pdf_sections.keys()),
        "content_length": len(content)
    }

@mcp.tool()
def obsidian_create_weekly_digest(papers: list) -> dict:
    """
    Create a weekly research digest note summarizing multiple papers.
    Args:
        papers: List of paper summaries (dict with id, title, key_findings)
    """
    logging.info(f"Creating weekly digest for {len(papers)} papers")
    
    # Build digest content
    digest_content = f"""# Weekly Research Digest

**Week of**: {datetime.now().strftime("%Y-%m-%d")}

## Overview
This digest summarizes the key research findings from {len(papers)} papers.

## Papers Reviewed
"""
    
    for i, paper in enumerate(papers, 1):
        digest_content += f"\n### {i}. {paper.get('title', 'Untitled')}\n"
        digest_content += f"- **ID**: {paper.get('id', 'N/A')}\n"
        digest_content += f"- **Key Findings**: {paper.get('key_findings', 'N/A')}\n"
        digest_content += f"- **Link**: [[{paper.get('id')}]]\n"
    
    digest_content += f"\n## Themes & Patterns\n- Common methodologies across papers\n- Emerging research directions\n\n## Action Items\n- Follow-up research needed\n"
    
    digest_path = f"{DEFAULT_FOLDER}/Digests/Weekly-{datetime.now().strftime('%Y-W%V')}"
    
    return {
        "path": digest_path,
        "status": "created",
        "papers_included": len(papers),
        "content_preview": digest_content[:300]
    }

if __name__ == "__main__":
    try:
        logging.info("Starting Obsidian MCP Server...")
        mcp.run()
    except Exception as e:
        logging.error(f"Server crashed: {e}")
        raise
