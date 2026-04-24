"""PDF parser MCP server.

Thin wrapper exposing the shared ``src.common.pdf_sections`` logic as MCP
tools. All heavy lifting lives in the common module so the Obsidian server
can import the same helpers without duplication.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pymupdf
from fastmcp import FastMCP
from loguru import logger

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.common.logging_config import configure_logging  # noqa: E402
from src.common.pdf_sections import (  # noqa: E402
    PER_SECTION_LIMIT,
    extract_pdf_text,
    get_page_count,
    split_sections,
)
from src.common.settings import load_settings  # noqa: E402

_settings = load_settings()
configure_logging("pdf_parser", _settings.log_dir, _settings.log_level)

mcp = FastMCP("PDFParser")


def _resolve_pdf_path(pdf_path: str) -> Path:
    """If ``pdf_path`` is relative, resolve it against the configured paper dir."""
    p = Path(pdf_path)
    if not p.is_absolute():
        p = _settings.paper_storage / p.name
    return p


@mcp.tool()
def extract_pdf_sections(pdf_path: str, max_chars: int = 10000) -> dict:
    """
    Extract structured sections (abstract, introduction, methods, results,
    conclusion, …) from a PDF.

    Args:
        pdf_path:  Absolute or paper-storage-relative path to the PDF.
        max_chars: Character budget for the ``full_text_preview`` field.

    Returns a dict with canonical section keys plus
    ``full_text_preview``, ``total_pages``, ``total_chars``, and
    ``sections_found``. On failure returns ``{"error": "..."}``.
    """
    try:
        resolved = _resolve_pdf_path(pdf_path)
        if not resolved.exists():
            return {"error": f"File not found: {resolved}"}

        text = extract_pdf_text(resolved)
        sections: dict = dict(split_sections(text, PER_SECTION_LIMIT))

        sections["full_text_preview"] = text[:max_chars]
        sections["total_pages"] = get_page_count(resolved)
        sections["total_chars"] = len(text)
        sections["sections_found"] = [
            k
            for k in sections
            if k not in ("full_text_preview", "total_pages", "total_chars", "sections_found")
        ]
        return sections
    except Exception as e:
        logger.exception(f"Failed to extract sections from {pdf_path}")
        return {"error": str(e)}


@mcp.tool()
def extract_figures(pdf_path: str) -> list[dict]:
    """Extract figure metadata (page number, xref, dimensions) from a PDF."""
    try:
        resolved = _resolve_pdf_path(pdf_path)
        if not resolved.exists():
            return [{"error": f"File not found: {resolved}"}]

        doc = pymupdf.open(resolved)
        try:
            figures: list[dict] = []
            for page_num, page in enumerate(doc, start=1):
                for img in page.get_images(full=True):
                    figures.append(
                        {
                            "page": page_num,
                            "xref": img[0],
                            "width": img[2],
                            "height": img[3],
                        }
                    )
        finally:
            doc.close()
        return figures if figures else [{"message": "No figures detected"}]
    except Exception as e:
        logger.exception(f"Failed to extract figures from {pdf_path}")
        return [{"error": str(e)}]


if __name__ == "__main__":
    try:
        logger.info("Starting PDF Parser MCP Server...")
        mcp.run()
    except Exception as e:
        logger.exception(f"Server crashed: {e}")
        raise
