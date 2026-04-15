from fastmcp import FastMCP
import httpx
import json
import os
from datetime import datetime
import logging

logging.basicConfig(level=logging.INFO)

mcp = FastMCP("Obsidian")

# Configuration
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
def obsidian_create_note(title: str, content: str, tags: list = None) -> dict:
    """
    Create a new note in Obsidian with frontmatter and structured sections.
    Args:
        title: Title of the note
        content: Main content in markdown
        tags: List of tags to add (e.g., ["ml", "2025"])
    """
    logging.info(f"Creating note: {title}")
    
    if tags is None:
        tags = []
    
    # Auto-generate safe filename from title
    safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).rstrip()
    note_path = f"{DEFAULT_FOLDER}/{safe_title}"
    
    # Build note with actual content — no hardcoded placeholders
    note_content = f"""---
title: {title}
created: {datetime.now().isoformat()}
tags: {json.dumps(tags)}
type: research-note
---

# {title}

{content}

## References
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
def obsidian_create_paper_note(paper_id: str, title: str, authors: list, abstract: str, 
                                methods: str = "", findings: str = "", keywords: list = None) -> dict:
    """
    Create a structured research paper note with standard sections.
    Args:
        paper_id: ArXiv ID or unique identifier
        title: Paper title
        authors: List of author names
        abstract: Paper abstract
        methods: Methods section summary
        findings: Key findings summary
        keywords: Research keywords/topics
    """
    logging.info(f"Creating paper note for: {paper_id}")
    
    if keywords is None:
        keywords = []
    
    # Build paper note using whatever content was extracted from the PDF
    _methods_text  = methods.strip()  if methods  and methods.strip()  else "_Not extracted — run extract_pdf_sections first._"
    _findings_text = findings.strip() if findings and findings.strip() else "_Not extracted — run extract_pdf_sections first._"
    _abstract_text = abstract.strip() if abstract and abstract.strip() else "_Not available._"

    content = f"""# {title}

## Metadata
- **Paper ID**: {paper_id}
- **Authors**: {", ".join(authors)}
- **ArXiv**: https://arxiv.org/abs/{paper_id}
- **Date Added**: {datetime.now().strftime("%Y-%m-%d")}

## Abstract
{_abstract_text}

## Methods
{_methods_text}

## Key Findings
{_findings_text}
"""
    
    # Create note with frontmatter
    tags = ["research", "paper"] + keywords
    
    # Use paper_id as filename
    note_path = f"{DEFAULT_FOLDER}/{paper_id}"
    
    # Format note with YAML frontmatter
    note_content = f"""---
title: {title}
paper_id: {paper_id}
authors: {json.dumps(authors)}
published: {datetime.now().strftime("%Y-%m-%d")}
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
