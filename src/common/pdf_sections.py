"""Shared PDF section extraction.

Previously duplicated in ``pdf_parser/server.py`` and
``obsidian_server/server.py``. This module owns the canonical regex,
canonicalisation rules, and splitting logic.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import pymupdf

from .exceptions import PDFParseError


# Matches common academic section headers, numbered or plain:
#   "Abstract", "1. Introduction", "2 Methods", "II. RESULTS"
_SECTION_RE = re.compile(
    r"^[ \t]*(?:\d+\.?\d*\s+|[IVX]+\.\s+)?"
    r"(abstract|introduction|related\s+work|background|preliminaries|"
    r"method(?:s|ology)?|approach|model|framework|architecture|"
    r"experiment(?:s)?(?:\s+(?:and\s+)?(?:setup|results?|analysis))?|"
    r"evaluation|results?(?:\s+and\s+discussion)?|"
    r"discussion|conclusion(?:s)?(?:\s+and\s+future\s+work)?|"
    r"future\s+work|acknowledgm?ents?)"
    r"[ \t]*$",
    re.IGNORECASE | re.MULTILINE,
)

# Raw header name → canonical key returned to callers. ``None`` means skip.
_CANONICAL: dict[str, Optional[str]] = {
    "abstract": "abstract",
    "introduction": "introduction",
    "related work": "related_work",
    "background": "related_work",
    "preliminaries": "related_work",
    "method": "methods",
    "methods": "methods",
    "methodology": "methods",
    "approach": "methods",
    "model": "methods",
    "framework": "methods",
    "architecture": "methods",
    "experiments": "experiments",
    "experiment": "experiments",
    "experimental setup": "experiments",
    "evaluation": "experiments",
    "results": "results",
    "results and discussion": "results",
    "experiments and results": "results",
    "discussion": "discussion",
    "conclusion": "conclusion",
    "conclusions": "conclusion",
    "conclusions and future work": "conclusion",
    "future work": "conclusion",
    "acknowledgments": None,
    "acknowledgements": None,
    "acknowledgment": None,
    "acknowledgement": None,
}

PER_SECTION_LIMIT = 3000


def canonicalize(raw_name: str) -> Optional[str]:
    """Map a detected section header to its canonical key, or ``None`` to skip."""
    norm = re.sub(r"\s+", " ", raw_name.lower().strip())
    if norm in _CANONICAL:
        return _CANONICAL[norm]
    for key, val in _CANONICAL.items():
        if norm.startswith(key) or key.startswith(norm):
            return val
    return None


def split_sections(text: str, per_section_limit: int = PER_SECTION_LIMIT) -> dict[str, str]:
    """Split a raw PDF text dump into canonical sections.

    Uses ``_SECTION_RE`` to locate header lines, then extracts the span between
    each header and the next. Long sections are truncated with a marker so the
    token budget stays bounded. If no ``abstract`` header is found, falls back
    to a positional search near the top of the document.
    """
    sections: dict[str, str] = {}
    matches = list(_SECTION_RE.finditer(text))

    for i, match in enumerate(matches):
        canonical = canonicalize(match.group(1))
        if canonical is None:
            continue
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        content = text[start:end].strip()
        if not content:
            continue
        if len(content) > per_section_limit:
            content = content[:per_section_limit] + "\n[... truncated]"
        if canonical in sections:
            sections[canonical] = (sections[canonical] + "\n\n" + content)[:per_section_limit]
        else:
            sections[canonical] = content

    if "abstract" not in sections:
        tl = text.lower()
        abs_start = tl.find("abstract")
        if abs_start != -1:
            intro_start = tl.find("introduction", abs_start)
            abs_end = intro_start if intro_start != -1 else abs_start + 1500
            sections["abstract"] = text[abs_start:abs_end].strip()[:per_section_limit]

    return sections


def extract_pdf_text(pdf_path: str | Path) -> str:
    """Read raw text from a PDF; raises ``PDFParseError`` on failure."""
    try:
        doc = pymupdf.open(pdf_path)
        try:
            return "".join(page.get_text() for page in doc)
        finally:
            doc.close()
    except Exception as e:
        raise PDFParseError(f"Failed to extract text from {pdf_path}: {e}") from e


def get_page_count(pdf_path: str | Path) -> int:
    """Return the number of pages in the PDF."""
    try:
        doc = pymupdf.open(pdf_path)
        try:
            return doc.page_count
        finally:
            doc.close()
    except Exception as e:
        raise PDFParseError(f"Failed to read page count from {pdf_path}: {e}") from e


def extract_sections(
    pdf_path: str | Path,
    per_section_limit: int = PER_SECTION_LIMIT,
) -> dict[str, str]:
    """Extract canonical sections from a PDF file."""
    return split_sections(extract_pdf_text(pdf_path), per_section_limit)
