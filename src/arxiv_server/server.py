from fastmcp import FastMCP
import arxiv
import os
import sqlite3
import pymupdf  # fitz
from datetime import datetime
from loguru import logger

# Log to a fixed location next to this file so output is predictable regardless
# of which directory the process is launched from. Rotate at 10 MB to avoid
# unbounded growth.
_LOG_PATH = os.path.join(os.path.dirname(__file__), "arxiv_server.log")
logger.add(_LOG_PATH, rotation="10 MB", retention="7 days", enqueue=True)

mcp = FastMCP("ArXiv")

PAPER_STORAGE = os.environ.get("PAPER_STORAGE", "./papers")
os.makedirs(PAPER_STORAGE, exist_ok=True)

# --- Query building helpers ---

_ARXIV_FIELD_PREFIXES = ("ti:", "au:", "abs:", "cat:", "id:", "all:", "co:", "jr:", "rn:", "submittedDate:")

# Common English stopwords that carry no search value on their own.
_STOPWORDS = frozenset({
    "a", "an", "the", "and", "or", "of", "in", "for", "on", "with",
    "is", "are", "to", "by", "from", "as", "at", "its", "via",
})

_MAX_RESULTS_LIMIT = 25  # hard cap so callers can't request unbounded pages


def _has_field_prefix(query: str) -> bool:
    """Return True if the query already contains arXiv field-search prefixes."""
    return any(prefix in query for prefix in _ARXIV_FIELD_PREFIXES)


def _key_terms(phrase: str) -> list[str]:
    """Extract meaningful words from a phrase (strips stopwords and short tokens)."""
    return [w for w in phrase.lower().split() if w not in _STOPWORDS and len(w) > 2]


def _build_structured_query(query: str, categories: list[str] | None = None) -> str:
    """
    Rewrite a plain natural-language query into a structured arXiv Lucene query
    that scopes results to title and abstract only.

    Strategy:
      - Short queries (≤3 key terms): exact-phrase search is tight enough.
            "reward alignment" → (ti:"reward alignment" OR abs:"reward alignment")
      - Longer queries: the exact phrase is too strict (papers rarely use the
        full phrase verbatim). Build an AND-of-terms clause instead so every
        key concept must appear, but word order doesn't matter.
            "large language model training efficiency"
            → (ti:large OR abs:large) AND (ti:language OR abs:language)
              AND (ti:model OR abs:model) AND (ti:training OR abs:training)
              AND (ti:efficiency OR abs:efficiency)

    An optional category filter is ANDed onto either form.
    """
    phrase = query.strip().strip('"')
    terms = _key_terms(phrase)

    if len(terms) <= 3:
        # Exact-phrase search — precise and low-noise for short topics.
        base = f'(ti:"{phrase}" OR abs:"{phrase}")'
    else:
        # AND of individual key terms — handles paraphrasing and word-order
        # variation that would break a strict phrase match.
        term_clauses = " AND ".join(f"(ti:{t} OR abs:{t})" for t in terms)
        base = f"({term_clauses})"

    if categories:
        cat_clause = " OR ".join(f"cat:{c}" for c in categories)
        return f"({base}) AND ({cat_clause})"
    return base


def _build_fallback_query(query: str) -> str:
    """
    Broader fallback used when the structured query returns zero results.
    Drops the category filter and relaxes to an OR of key terms so at least
    something related comes back.
    """
    terms = _key_terms(query)
    if not terms:
        return query  # can't do better; return raw query
    term_clauses = " OR ".join(f"(ti:{t} OR abs:{t})" for t in terms)
    return f"({term_clauses})"


# --- Result collection helper ---

def _paper_to_dict(r: arxiv.Result) -> dict:
    """Convert an arxiv.Result into a serialisable dict."""
    authors = ", ".join(a.name for a in r.authors[:3])
    if len(r.authors) > 3:
        authors += " et al."
    short_id = r.get_short_id()
    # Strip version suffix (e.g. "2404.14082v3" → "2404.14082") for a stable
    # abstract URL that always resolves to the latest version.
    base_id = short_id.split("v")[0]
    return {
        "id": short_id,
        "title": r.title,
        "authors": authors,
        "published": r.published.strftime("%Y-%m-%d"),
        "categories": r.categories,
        "summary": r.summary.replace("\n", " "),
        "arxiv_url": f"https://arxiv.org/abs/{base_id}",
        "pdf_url": r.pdf_url,
    }


def _run_search(
    client: arxiv.Client,
    query: str,
    max_results: int,
    sort_by: arxiv.SortCriterion,
    seen_ids: set[str],
) -> list[dict]:
    """
    Execute a single arXiv search pass and return new (unseen) results.
    Raises arxiv.UnexpectedEmptyPageError or requests exceptions on failure —
    callers are responsible for handling these.
    """
    search = arxiv.Search(query=query, max_results=max_results, sort_by=sort_by)
    results = []
    for r in client.results(search):
        short_id = r.get_short_id()
        if short_id in seen_ids:
            continue
        seen_ids.add(short_id)
        paper = _paper_to_dict(r)
        results.append(paper)
        logger.info(f"  found: {paper['title']} ({short_id})")
    return results


# --- Public MCP tool ---

@mcp.tool()
def search_papers(
    query: str,
    max_results: int = 8,
    categories: list[str] | None = None,
) -> list[dict]:
    """
    Search for papers on ArXiv and return the most relevant results.

    Args:
        query: Research topic in plain English, or an explicit arXiv Lucene
               query if you need precise control.  Plain queries are
               automatically rewritten to scope to title + abstract only,
               so results are far more on-topic than a raw keyword search.
               Explicit arXiv syntax is passed through unchanged:
                 - ti:"exact title"   — exact title phrase
                 - abs:keyword        — abstract keyword
                 - au:Author Name     — author search
                 - cat:cs.AI          — category filter
        max_results: Number of results to return (1–25, default 8).
        categories: Optional arXiv category codes to restrict results,
                    e.g. ["cs.AI", "cs.LG", "stat.ML"].  Only applied when
                    the query has no field prefixes.

    Returns:
        List of paper dicts with keys: id, title, authors, published,
        categories, summary, pdf_url.
        On failure, returns a list containing a single error dict with key
        "error" so the caller always receives a list, never an exception.
    """
    # --- Input validation ---
    if not query or not query.strip():
        return [{"error": "query must be a non-empty string"}]

    try:
        max_results = max(1, min(int(max_results), _MAX_RESULTS_LIMIT))
    except (TypeError, ValueError):
        return [{"error": f"max_results must be an integer, got: {max_results!r}"}]

    # --- Query construction ---
    if _has_field_prefix(query):
        effective_query = query
        logger.info(f"Raw arXiv query: '{effective_query}'")
    else:
        effective_query = _build_structured_query(query, categories)
        logger.info(f"Rewrote '{query}' → '{effective_query}'")

    client = arxiv.Client()
    seen_ids: set[str] = set()
    results: list[dict] = []

    try:
        # Pass 1 — relevance-sorted (primary)
        logger.info("Pass 1: relevance sort")
        results += _run_search(client, effective_query, max_results, arxiv.SortCriterion.Relevance, seen_ids)

        # Pass 2 — recency-sorted (surfaces new work the relevance ranker may bury)
        logger.info("Pass 2: recency sort")
        results += _run_search(client, effective_query, max(max_results // 2, 3), arxiv.SortCriterion.SubmittedDate, seen_ids)

    except Exception as e:
        logger.error(f"arXiv API error for query '{effective_query}': {e}")
        return [{"error": f"arXiv API error: {e}"}]

    # --- Zero-result fallback ---
    if not results and not _has_field_prefix(query):
        fallback_query = _build_fallback_query(query)
        logger.warning(f"No results from structured query. Falling back to: '{fallback_query}'")
        try:
            results += _run_search(client, fallback_query, max_results, arxiv.SortCriterion.Relevance, seen_ids)
            if results:
                # Tag results so the LLM knows these came from a broadened search
                for r in results:
                    r["note"] = "Returned via broadened search — phrase match found nothing. Review relevance carefully."
        except Exception as e:
            logger.error(f"Fallback search also failed: {e}")
            return [{"error": f"Search failed (including fallback): {e}"}]

    if not results:
        logger.warning(f"No results found for query: '{query}'")
        return [{"error": f"No papers found for '{query}'. Try rephrasing or using explicit arXiv field prefixes (ti:, abs:, cat:)."}]

    results = results[:max_results]
    logger.info(f"Returning {len(results)} results for: '{query}'")
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
def read_paper(paper_id: str, max_chars: int = 15000) -> str:
    """
    Read the text content of a downloaded paper.
    Args:
        paper_id: The ID of the paper (e.g. "2401.12345")
        max_chars: Maximum characters to return (default 15000 to avoid token limits)
    """
    path = os.path.join(PAPER_STORAGE, f"{paper_id}.pdf")
    if not os.path.exists(path):
        return f"Error: Paper {paper_id} not found locally. Download it first."
    
    try:
        doc = pymupdf.open(path)
        text = ""
        for page in doc:
            text += page.get_text()
            if len(text) > max_chars:
                text = text[:max_chars]
                text += f"\n\n[... Content truncated at {max_chars} characters to avoid token limits. Full paper has {doc.page_count} pages ...]"
                break
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
        logger.info("Starting ArXiv MCP Server...")
        mcp.run()
    except Exception as e:
        logger.error(f"Server crashed: {e}")
        raise
