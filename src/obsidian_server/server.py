"""Obsidian MCP server.

All vault I/O goes through ``src.common.vault.Vault`` so path resolution,
frontmatter parsing, and traversal defence live in one place. Paper-note
creation auto-fetches metadata from arXiv and extracts structured sections
from the cached PDF.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import arxiv
from fastmcp import FastMCP
from loguru import logger

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.common.exceptions import (  # noqa: E402
    NoteNotFoundError,
    ObsidianError,
    VaultNotConfiguredError,
)
from src.common.logging_config import configure_logging  # noqa: E402
from src.common.pdf_sections import extract_sections  # noqa: E402
from src.common.settings import load_settings  # noqa: E402
from src.common.vault import Vault  # noqa: E402

_settings = load_settings()
configure_logging("obsidian_server", _settings.log_dir, _settings.log_level)

mcp = FastMCP("Obsidian")


# ---------------------------------------------------------------------------
# Vault handle (lazy — don't crash the process if the vault is missing; only
# surface the error when a tool is actually invoked).
# ---------------------------------------------------------------------------


_vault_path = _settings.obsidian_vault_path
if _vault_path is None:
    # Best-effort discovery so users don't have to configure anything in the
    # common single-machine case where the vault sits next to the project.
    for candidate in (
        _REPO_ROOT / "Darwin Research",
        Path.home() / "Obsidian" / "Darwin Research",
        Path.home() / "Documents" / "Obsidian" / "Darwin Research",
    ):
        if candidate.exists():
            _vault_path = candidate
            logger.info(f"Auto-detected Obsidian vault at {candidate}")
            break


def _get_vault() -> Vault:
    """Return a Vault handle, or raise ``VaultNotConfiguredError``."""
    if _vault_path is None:
        raise VaultNotConfiguredError(
            "OBSIDIAN_VAULT_PATH is not set and no default vault could be located."
        )
    return Vault(_vault_path)


def _error_response(message: str) -> dict:
    return {"success": False, "status": "failed", "error": message}


_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9 _\-]+")


def _safe_filename(title: str) -> str:
    """Strip characters that cause pain in cross-platform filesystems."""
    cleaned = _SAFE_FILENAME_RE.sub("", title).strip()
    return cleaned or "untitled"


# ---------------------------------------------------------------------------
# Note CRUD
# ---------------------------------------------------------------------------


@mcp.tool()
def obsidian_read_note(note_path: str) -> dict:
    """
    Read a note's full markdown content.

    Args:
        note_path: Vault-relative path (with or without ``.md``).
    """
    logger.info(f"Reading note: {note_path}")
    try:
        vault = _get_vault()
        content = vault.read_note(note_path)
        return {
            "success": True,
            "path": note_path,
            "content": content,
            "length": len(content),
        }
    except NoteNotFoundError as e:
        return _error_response(str(e))
    except VaultNotConfiguredError as e:
        return _error_response(str(e))
    except Exception as e:
        logger.exception("Unexpected error reading note")
        return _error_response(f"Unexpected error: {e}")


@mcp.tool()
def obsidian_create_note(title: str, content: str = "", tags: list | None = None) -> dict:
    """
    Create a new research note with standard frontmatter and sections.

    Args:
        title:   Note title (also used to derive the filename).
        content: Body content for the Overview section (optional).
        tags:    List of tag strings to add to the frontmatter.
    """
    logger.info(f"Creating note: {title}")
    tags = list(tags or [])
    overview = content.strip() or f"Research note about {title}."

    safe_title = _safe_filename(title)
    note_path = f"{_settings.obsidian_default_folder}/{safe_title}"

    created = datetime.now()
    frontmatter_tags = list(dict.fromkeys(["research", *tags]))
    frontmatter = (
        "---\n"
        f"title: {json.dumps(title)}\n"
        f"created: {created.isoformat()}\n"
        f"tags: {json.dumps(frontmatter_tags)}\n"
        f"type: research-note\n"
        "---\n"
    )

    body = (
        f"# {title}\n\n"
        f"## Overview\n{overview}\n\n"
        "## Key Points\n- \n\n"
        "## Analysis & Insights\n\n"
        "## Related Topics\n\n"
        "## References & Sources\n\n"
        "## Action Items\n- [ ] \n\n"
        f"## Last Updated\n{created.strftime('%Y-%m-%d %H:%M:%S')}\n"
    )

    try:
        vault = _get_vault()
        full = vault.write_note(note_path, frontmatter + body)
        return {
            "success": True,
            "status": "created",
            "title": title,
            "file_location": str(full),
            "relative_path": note_path,
            "vault_path": str(vault.root),
            "content_preview": overview[:200],
        }
    except VaultNotConfiguredError as e:
        return _error_response(str(e))
    except Exception as e:
        logger.exception("Failed to create note")
        return _error_response(str(e))


@mcp.tool()
def obsidian_update_note(note_path: str, append_content: str) -> dict:
    """
    Append markdown content to an existing note's body (after any frontmatter).
    """
    logger.info(f"Updating note: {note_path}")
    try:
        vault = _get_vault()
        full = vault.append_note(note_path, append_content)
        return {
            "success": True,
            "status": "updated",
            "path": note_path,
            "file_location": str(full),
            "appended_chars": len(append_content),
        }
    except NoteNotFoundError as e:
        return _error_response(str(e))
    except VaultNotConfiguredError as e:
        return _error_response(str(e))
    except Exception as e:
        logger.exception("Failed to update note")
        return _error_response(str(e))


@mcp.tool()
def obsidian_manage_frontmatter(
    note_path: str,
    tags: list | None = None,
    properties: dict | None = None,
) -> dict:
    """
    Merge tags and properties into an existing note's YAML frontmatter.
    Existing tags are preserved; new tags are appended and de-duplicated.
    Property keys overwrite existing ones.
    """
    logger.info(f"Updating frontmatter for: {note_path}")
    try:
        vault = _get_vault()
        full = vault.update_frontmatter(
            note_path,
            tags=list(tags) if tags else None,
            properties=dict(properties) if properties else None,
        )
        return {
            "success": True,
            "status": "frontmatter_updated",
            "path": note_path,
            "file_location": str(full),
            "tags_added": list(tags or []),
            "properties_set": list((properties or {}).keys()),
        }
    except NoteNotFoundError as e:
        return _error_response(str(e))
    except VaultNotConfiguredError as e:
        return _error_response(str(e))
    except Exception as e:
        logger.exception("Failed to update frontmatter")
        return _error_response(str(e))


@mcp.tool()
def obsidian_global_search(query: str, max_results: int = 20) -> list:
    """
    Search across all notes in the vault by substring match.
    Returns a list of ``{name, path, snippet}`` dicts or an error dict.
    """
    logger.info(f"Searching vault for: {query}")
    if not query or not query.strip():
        return [{"error": "query must be a non-empty string"}]
    try:
        vault = _get_vault()
        hits = vault.search(query.strip(), case_sensitive=False, max_results=max_results)
        if not hits:
            return [{"message": f"No matches for '{query}'"}]
        return hits
    except VaultNotConfiguredError as e:
        return [{"error": str(e)}]
    except Exception as e:
        logger.exception("Vault search failed")
        return [{"error": str(e)}]


# ---------------------------------------------------------------------------
# Paper note creation (auto-fetch + auto-extract)
# ---------------------------------------------------------------------------


def _fetch_arxiv_metadata(paper_id: str) -> dict:
    """Fetch title/authors/abstract/published/categories from arXiv."""
    base_id = paper_id.split("v")[0]
    try:
        client = arxiv.Client()
        result = next(client.results(arxiv.Search(id_list=[base_id])))
        return {
            "title": result.title,
            "authors": [a.name for a in result.authors],
            "abstract": result.summary.replace("\n", " "),
            "published": result.published.strftime("%Y-%m-%d"),
            "pdf_url": result.pdf_url,
            "categories": list(result.categories) if result.categories else [],
        }
    except Exception as e:
        logger.warning(f"Could not fetch arXiv metadata for {paper_id}: {e}")
        return {}


@mcp.tool()
def obsidian_create_paper_note(
    paper_id: str,
    title: str = "",
    authors: list | None = None,
    abstract: str = "",
    methods: str = "",
    findings: str = "",
    keywords: list | None = None,
) -> dict:
    """
    Create a structured research-paper note.

    Auto-fetches title/authors/abstract from arXiv when any of those are
    omitted, and auto-extracts methods/results/conclusion from the cached
    PDF (if present at ``<paper_storage>/<paper_id>.pdf``). Caller-supplied
    values always take precedence over auto-extracted ones.
    """
    logger.info(f"Creating paper note for: {paper_id}")
    authors = list(authors or [])
    keywords = list(keywords or [])

    base_id = paper_id.split("v")[0]
    arxiv_url = f"https://arxiv.org/abs/{base_id}"
    pdf_url = f"https://arxiv.org/pdf/{base_id}"
    published_date = datetime.now().strftime("%Y-%m-%d")

    # Auto-fetch missing metadata
    if not title or not abstract or not authors:
        logger.info(f"Auto-fetching metadata from arXiv for {paper_id}")
        meta = _fetch_arxiv_metadata(paper_id)
        if meta:
            title = title or meta.get("title", "")
            authors = authors or meta.get("authors", [])
            abstract = abstract or meta.get("abstract", "")
            published_date = meta.get("published", published_date)
            pdf_url = meta.get("pdf_url", pdf_url)
            if not keywords:
                keywords = meta.get("categories", [])

    if not title:
        title = f"Paper {paper_id}"

    # Auto-extract structured sections from the PDF if it's on disk
    pdf_path = _settings.paper_storage / f"{paper_id}.pdf"
    pdf_sections: dict = {}
    if pdf_path.exists():
        try:
            logger.info(f"Extracting sections from {pdf_path}")
            pdf_sections = extract_sections(pdf_path)
        except Exception as e:
            logger.warning(f"PDF section extraction failed: {e}")
    else:
        logger.info(f"PDF not found at {pdf_path}, skipping section extraction")

    _abstract = abstract.strip() or pdf_sections.get("abstract", "_No abstract available._")
    _methods = methods.strip() or pdf_sections.get("methods", "_Not extracted._")
    _results = (
        findings.strip()
        or pdf_sections.get("results")
        or pdf_sections.get("experiments", "_Not extracted._")
    )
    _conclusion = pdf_sections.get("conclusion", "_Not extracted._")
    _introduction = pdf_sections.get("introduction") or "_See full paper._"

    body = (
        f"# {title}\n\n"
        "## Metadata\n"
        f"- **Paper ID**: {paper_id}\n"
        f"- **Authors**: {', '.join(authors)}\n"
        f"- **Published**: {published_date}\n"
        f"- **arXiv**: [{arxiv_url}]({arxiv_url})\n"
        f"- **PDF**: [{pdf_url}]({pdf_url})\n\n"
        f"## Abstract\n{_abstract}\n\n"
        f"## Introduction\n{_introduction}\n\n"
        f"## Methods\n{_methods}\n\n"
        f"## Results\n{_results}\n\n"
        f"## Conclusion\n{_conclusion}\n\n"
        "## Personal Notes\n- \n\n"
        "## Follow-up Questions\n- \n"
    )

    tags = list(dict.fromkeys(["research", "paper", *keywords]))
    frontmatter = (
        "---\n"
        f"title: {json.dumps(title)}\n"
        f"paper_id: {paper_id}\n"
        f"authors: {json.dumps(authors)}\n"
        f"published: {published_date}\n"
        f"arxiv_url: {arxiv_url}\n"
        f"pdf_url: {pdf_url}\n"
        f"tags: {json.dumps(tags)}\n"
        "type: research-paper\n"
        "status: inbox\n"
        "---\n\n"
    )

    note_path = f"{_settings.obsidian_default_folder}/{paper_id}"

    try:
        vault = _get_vault()
        full = vault.write_note(note_path, frontmatter + body)
        return {
            "success": True,
            "status": "created",
            "paper_id": paper_id,
            "title": title,
            "file_location": str(full),
            "relative_path": note_path,
            "vault_path": str(vault.root),
            "sections_extracted": list(pdf_sections.keys()),
            "content_length": len(body),
        }
    except VaultNotConfiguredError as e:
        return _error_response(str(e))
    except Exception as e:
        logger.exception("Failed to create paper note")
        return _error_response(str(e))


@mcp.tool()
def obsidian_create_weekly_digest(papers: list) -> dict:
    """
    Create a weekly research-digest note summarising multiple papers.

    ``papers`` is a list of dicts with any of ``id``, ``title``, and
    ``key_findings``. The digest is written to
    ``<default_folder>/Digests/Weekly-YYYY-Www.md``.
    """
    logger.info(f"Creating weekly digest for {len(papers)} papers")
    now = datetime.now()
    week_tag = now.strftime("%Y-W%V")

    lines = [
        "# Weekly Research Digest",
        "",
        f"**Week of**: {now.strftime('%Y-%m-%d')}",
        "",
        "## Overview",
        f"This digest summarises the key research findings from {len(papers)} papers.",
        "",
        "## Papers Reviewed",
        "",
    ]
    for i, paper in enumerate(papers, start=1):
        pid = paper.get("id", "N/A")
        title = paper.get("title", "Untitled")
        findings = paper.get("key_findings") or paper.get("summary", "N/A")
        lines.extend(
            [
                f"### {i}. {title}",
                f"- **ID**: {pid}",
                f"- **Key Findings**: {findings}",
                f"- **Link**: [[{pid}]]",
                "",
            ]
        )
    lines.extend(
        [
            "## Themes & Patterns",
            "- ",
            "",
            "## Action Items",
            "- [ ] ",
            "",
        ]
    )

    digest_body = "\n".join(lines)
    frontmatter = (
        "---\n"
        f"title: \"Weekly Research Digest — {week_tag}\"\n"
        f"created: {now.isoformat()}\n"
        f"tags: [\"research\", \"digest\", \"{week_tag}\"]\n"
        "type: weekly-digest\n"
        "---\n\n"
    )

    digest_path = f"{_settings.obsidian_default_folder}/Digests/Weekly-{week_tag}"
    try:
        vault = _get_vault()
        full = vault.write_note(digest_path, frontmatter + digest_body)
        return {
            "success": True,
            "status": "created",
            "path": digest_path,
            "file_location": str(full),
            "papers_included": len(papers),
            "content_preview": digest_body[:300],
        }
    except VaultNotConfiguredError as e:
        return _error_response(str(e))
    except Exception as e:
        logger.exception("Failed to create weekly digest")
        return _error_response(str(e))


if __name__ == "__main__":
    try:
        logger.info("Starting Obsidian MCP Server...")
        mcp.run()
    except Exception as e:
        logger.exception(f"Server crashed: {e}")
        raise
