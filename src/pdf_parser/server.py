from fastmcp import FastMCP
import pymupdf
import re
import os

mcp = FastMCP("PDFParser")

# ── Section detection ──────────────────────────────────────────────────────────
# Matches common academic paper section headers (numbered or plain).
# Examples: "Abstract", "1. Introduction", "2 Methods", "II. RESULTS"
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

# Maps raw section name → canonical key returned in the dict
_CANONICAL = {
    "abstract":                     "abstract",
    "introduction":                 "introduction",
    "related work":                 "related_work",
    "background":                   "related_work",
    "preliminaries":                "related_work",
    "method":                       "methods",
    "methods":                      "methods",
    "methodology":                  "methods",
    "approach":                     "methods",
    "model":                        "methods",
    "framework":                    "methods",
    "architecture":                 "methods",
    "experiments":                  "experiments",
    "experiment":                   "experiments",
    "experimental setup":           "experiments",
    "evaluation":                   "experiments",
    "results":                      "results",
    "results and discussion":       "results",
    "experiments and results":      "results",
    "discussion":                   "discussion",
    "conclusion":                   "conclusion",
    "conclusions":                  "conclusion",
    "conclusions and future work":  "conclusion",
    "future work":                  "conclusion",
    "acknowledgments":              None,   # skip
    "acknowledgements":             None,
    "acknowledgment":               None,
    "acknowledgement":              None,
}

PER_SECTION_LIMIT = 3000  # chars per section


def _canonicalize(raw_name: str):
    norm = re.sub(r'\s+', ' ', raw_name.lower().strip())
    if norm in _CANONICAL:
        return _CANONICAL[norm]
    for key, val in _CANONICAL.items():
        if norm.startswith(key) or key.startswith(norm):
            return val
    return None


def _extract_sections(full_text: str) -> dict:
    """
    Split full PDF text into canonical sections using header detection.
    Returns a dict of {canonical_name: text_content}.
    """
    sections = {}
    matches   = list(_SECTION_RE.finditer(full_text))

    for i, match in enumerate(matches):
        raw_name  = match.group(1)
        canonical = _canonicalize(raw_name)
        if canonical is None:
            continue  # skip acknowledged / unwanted sections

        start = match.end()
        end   = matches[i + 1].start() if i + 1 < len(matches) else len(full_text)

        content = full_text[start:end].strip()
        if not content:
            continue

        # Truncate long sections
        if len(content) > PER_SECTION_LIMIT:
            content = content[:PER_SECTION_LIMIT] + "\n[... truncated]"

        # Merge if canonical already seen (e.g. subsections that got detected as headers)
        if canonical in sections:
            combined = sections[canonical] + "\n\n" + content
            sections[canonical] = combined[:PER_SECTION_LIMIT]
        else:
            sections[canonical] = content

    return sections


@mcp.tool()
def extract_pdf_sections(pdf_path: str, max_chars: int = 10000) -> dict:
    """
    Extract structured sections (abstract, introduction, methods, results,
    conclusion, etc.) from an arXiv PDF.

    Args:
        pdf_path:  Path to the PDF file (absolute, or relative to papers/).
        max_chars: Maximum characters for the full_text_preview field.

    Returns a dict with keys: abstract, introduction, related_work, methods,
    experiments, results, discussion, conclusion, full_text_preview,
    total_pages, total_chars, sections_found.
    """
    try:
        # Resolve relative paths against the papers directory
        if not os.path.isabs(pdf_path):
            papers_dir = os.path.join(os.path.dirname(__file__), "../../papers")
            pdf_path   = os.path.join(papers_dir, os.path.basename(pdf_path))

        if not os.path.exists(pdf_path):
            return {"error": f"File not found: {pdf_path}"}

        doc       = pymupdf.open(pdf_path)
        full_text = "".join(page.get_text() for page in doc)
        doc.close()

        # Extract structured sections from the full text
        sections = _extract_sections(full_text)

        # If abstract was not found by header, try the first 1500 chars
        if "abstract" not in sections:
            text_lower = full_text.lower()
            abs_start  = text_lower.find("abstract")
            if abs_start != -1:
                intro_start = text_lower.find("introduction", abs_start)
                abs_end     = intro_start if intro_start != -1 else abs_start + 1500
                sections["abstract"] = full_text[abs_start:abs_end].strip()[:PER_SECTION_LIMIT]

        sections["full_text_preview"] = full_text[:max_chars]
        sections["total_pages"]       = pymupdf.open(pdf_path).page_count
        sections["total_chars"]       = len(full_text)
        sections["sections_found"]    = [
            k for k in sections
            if k not in ("full_text_preview", "total_pages", "total_chars", "sections_found")
        ]

        return sections

    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def extract_figures(pdf_path: str) -> list:
    """Extract figure metadata from a PDF (page number and bounding box)."""
    try:
        if not os.path.isabs(pdf_path):
            papers_dir = os.path.join(os.path.dirname(__file__), "../../papers")
            pdf_path   = os.path.join(papers_dir, os.path.basename(pdf_path))

        if not os.path.exists(pdf_path):
            return [{"error": f"File not found: {pdf_path}"}]

        doc     = pymupdf.open(pdf_path)
        figures = []
        for page_num, page in enumerate(doc, start=1):
            for img in page.get_images(full=True):
                figures.append({
                    "page":    page_num,
                    "xref":    img[0],
                    "width":   img[2],
                    "height":  img[3],
                })
        doc.close()
        return figures if figures else [{"message": "No figures detected"}]
    except Exception as e:
        return [{"error": str(e)}]


if __name__ == "__main__":
    mcp.run()
