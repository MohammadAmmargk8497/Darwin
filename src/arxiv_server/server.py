"""ArXiv MCP server.

Exposes a focused set of tools for searching, downloading, and reading papers
from arXiv. Query rewriting, retry/backoff, rate limiting, and action logging
are applied here so downstream consumers (the agent, the Obsidian server) can
treat arXiv as a reliable data source.
"""

from __future__ import annotations

import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import arxiv
from fastmcp import FastMCP
from loguru import logger
from tenacity import (
    RetryError,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

# Make ``src.common`` importable regardless of how this file is launched
# (FastMCP spawns us as a plain script via ``python src/arxiv_server/server.py``).
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.common.exceptions import ArxivEmptyResultError, ArxivError  # noqa: E402
from src.common.logging_config import configure_logging  # noqa: E402
from src.common.pdf_sections import extract_pdf_text  # noqa: E402
from src.common.rate_limit import RateLimiter  # noqa: E402
from src.common.settings import load_settings  # noqa: E402

_settings = load_settings()
configure_logging("arxiv_server", _settings.log_dir, _settings.log_level)

mcp = FastMCP("ArXiv")

PAPER_STORAGE = Path(_settings.paper_storage)
PAPER_STORAGE.mkdir(parents=True, exist_ok=True)

# A shared rate limiter so concurrent tool calls still respect arXiv's
# polite-use minimum — the `arxiv` lib's per-Client delay doesn't help us
# when we spin up a new Client per request.
_arxiv_limiter = RateLimiter(_settings.arxiv_rate_limit_seconds)


def _make_client() -> arxiv.Client:
    return arxiv.Client(
        page_size=_settings.arxiv_page_size,
        delay_seconds=_settings.arxiv_rate_limit_seconds,
        num_retries=_settings.arxiv_max_retries,
    )


# ---------------------------------------------------------------------------
# Query building
# ---------------------------------------------------------------------------

_ARXIV_FIELD_PREFIXES = (
    "ti:", "au:", "abs:", "cat:", "id:", "all:", "co:", "jr:", "rn:", "submittedDate:",
)

_STOPWORDS = frozenset(
    {
        "a", "an", "the", "and", "or", "of", "in", "for", "on", "with",
        "is", "are", "to", "by", "from", "as", "at", "its", "via",
    }
)

_MAX_RESULTS_LIMIT = 25


def _has_field_prefix(query: str) -> bool:
    return any(prefix in query for prefix in _ARXIV_FIELD_PREFIXES)


def _key_terms(phrase: str) -> list[str]:
    return [w for w in phrase.lower().split() if w not in _STOPWORDS and len(w) > 2]


def _build_structured_query(query: str, categories: list[str] | None = None) -> str:
    """Rewrite a plain query into a structured arXiv Lucene query.

    Short queries (≤3 key terms) use exact-phrase search, which is tight and
    low-noise. Longer queries use AND-of-terms so paraphrasing and word order
    don't torpedo the match.
    """
    phrase = query.strip().strip('"')
    terms = _key_terms(phrase)

    if len(terms) <= 3:
        base = f'(ti:"{phrase}" OR abs:"{phrase}")'
    else:
        term_clauses = " AND ".join(f"(ti:{t} OR abs:{t})" for t in terms)
        base = f"({term_clauses})"

    if categories:
        cat_clause = " OR ".join(f"cat:{c}" for c in categories)
        return f"({base}) AND ({cat_clause})"
    return base


def _build_fallback_query(query: str) -> str:
    """Broadened OR-of-terms fallback when the structured query returns nothing."""
    terms = _key_terms(query)
    if not terms:
        return query
    term_clauses = " OR ".join(f"(ti:{t} OR abs:{t})" for t in terms)
    return f"({term_clauses})"


# ---------------------------------------------------------------------------
# Result marshalling
# ---------------------------------------------------------------------------


def _paper_to_dict(r: arxiv.Result) -> dict:
    authors = ", ".join(a.name for a in r.authors[:3])
    if len(r.authors) > 3:
        authors += " et al."
    short_id = r.get_short_id()
    base_id = short_id.split("v")[0]  # stable abstract URL
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


# ---------------------------------------------------------------------------
# Retrying search helpers
# ---------------------------------------------------------------------------

_RETRYABLE_EXCEPTIONS: tuple[type[BaseException], ...] = (
    arxiv.UnexpectedEmptyPageError,
    ConnectionError,
    TimeoutError,
)


def _run_search_raw(
    client: arxiv.Client,
    query: str,
    max_results: int,
    sort_by: arxiv.SortCriterion,
) -> list[arxiv.Result]:
    """Execute one arXiv search pass. Retries on transient network failures."""
    _arxiv_limiter.wait()

    @retry(
        reraise=True,
        stop=stop_after_attempt(_settings.arxiv_max_retries),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        retry=retry_if_exception_type(_RETRYABLE_EXCEPTIONS),
    )
    def _fetch() -> list[arxiv.Result]:
        search = arxiv.Search(query=query, max_results=max_results, sort_by=sort_by)
        return list(client.results(search))

    try:
        return _fetch()
    except RetryError as e:  # pragma: no cover — tenacity wraps repeated failures
        raise ArxivError(f"arXiv search failed after retries: {e}") from e


def _run_search(
    client: arxiv.Client,
    query: str,
    max_results: int,
    sort_by: arxiv.SortCriterion,
    seen_ids: set[str],
) -> list[dict]:
    """Run a search pass and return new (unseen) results as dicts."""
    results: list[dict] = []
    for r in _run_search_raw(client, query, max_results, sort_by):
        short_id = r.get_short_id()
        if short_id in seen_ids:
            continue
        seen_ids.add(short_id)
        paper = _paper_to_dict(r)
        results.append(paper)
        logger.info(f"  found: {paper['title']} ({short_id})")
    return results


# ---------------------------------------------------------------------------
# Public MCP tools
# ---------------------------------------------------------------------------


@mcp.tool()
def search_papers(
    query: str,
    max_results: int = 8,
    categories: list[str] | None = None,
) -> list[dict]:
    """
    Search arXiv and return the most relevant results.

    Args:
        query: Plain-English topic, or an explicit arXiv Lucene query. Plain
               queries are rewritten to scope title + abstract only; explicit
               field-prefixed queries (``ti:``, ``abs:``, ``cat:``, ``au:``,
               ``id:``) are passed through unchanged.
        max_results: Number of results (1–25, default 8).
        categories: Optional arXiv category codes, e.g. ``["cs.AI", "cs.LG"]``.

    Returns a list of paper dicts with keys ``id, title, authors, published,
    categories, summary, arxiv_url, pdf_url``. On failure returns a single-item
    list ``[{"error": "..."}]`` so the caller always gets a list.
    """
    if not query or not query.strip():
        return [{"error": "query must be a non-empty string"}]

    try:
        max_results = max(1, min(int(max_results), _MAX_RESULTS_LIMIT))
    except (TypeError, ValueError):
        return [{"error": f"max_results must be an integer, got: {max_results!r}"}]

    if _has_field_prefix(query):
        effective_query = query
        logger.info(f"Raw arXiv query: '{effective_query}'")
    else:
        effective_query = _build_structured_query(query, categories)
        logger.info(f"Rewrote '{query}' → '{effective_query}'")

    client = _make_client()
    seen_ids: set[str] = set()
    results: list[dict] = []

    try:
        logger.info("Pass 1: relevance sort")
        results += _run_search(
            client, effective_query, max_results, arxiv.SortCriterion.Relevance, seen_ids,
        )
        logger.info("Pass 2: recency sort")
        results += _run_search(
            client, effective_query, max(max_results // 2, 3),
            arxiv.SortCriterion.SubmittedDate, seen_ids,
        )
    except ArxivError as e:
        logger.error(f"arXiv API error for query '{effective_query}': {e}")
        return [{"error": f"arXiv API error: {e}"}]
    except Exception as e:  # pragma: no cover — defensive
        logger.exception(f"Unexpected error during arXiv search")
        return [{"error": f"Unexpected error: {e}"}]

    if not results and not _has_field_prefix(query):
        fallback_query = _build_fallback_query(query)
        logger.warning(f"No results from structured query. Falling back to: '{fallback_query}'")
        try:
            results += _run_search(
                client, fallback_query, max_results,
                arxiv.SortCriterion.Relevance, seen_ids,
            )
            if results:
                for r in results:
                    r["note"] = (
                        "Returned via broadened search — phrase match found nothing. "
                        "Review relevance carefully."
                    )
        except Exception as e:
            logger.error(f"Fallback search also failed: {e}")
            return [{"error": f"Search failed (including fallback): {e}"}]

    if not results:
        logger.warning(f"No results found for query: '{query}'")
        return [
            {
                "error": (
                    f"No papers found for '{query}'. Try rephrasing or using explicit "
                    "arXiv field prefixes (ti:, abs:, cat:)."
                )
            }
        ]

    results = results[:max_results]
    logger.info(f"Returning {len(results)} results for: '{query}'")
    return results


@retry(
    reraise=True,
    stop=stop_after_attempt(_settings.arxiv_max_retries),
    wait=wait_exponential(multiplier=2, min=2, max=30),
    retry=retry_if_exception_type(_RETRYABLE_EXCEPTIONS),
)
def _fetch_single_paper(paper_id: str) -> arxiv.Result:
    _arxiv_limiter.wait()
    client = _make_client()
    search = arxiv.Search(id_list=[paper_id])
    try:
        return next(client.results(search))
    except StopIteration as e:
        raise ArxivEmptyResultError(f"No paper found with id {paper_id}") from e


@mcp.tool()
def download_paper(paper_id: str) -> str:
    """
    Download a paper by its ArXiv ID (e.g. ``"2401.12345"``). Returns the
    absolute path to the cached PDF. If the paper is already present locally,
    the existing path is returned without re-downloading.
    """
    logger.info(f"Downloading {paper_id}...")

    for filename in os.listdir(PAPER_STORAGE):
        if filename.startswith(paper_id) and filename.endswith(".pdf"):
            return str((PAPER_STORAGE / filename).resolve())

    try:
        paper = _fetch_single_paper(paper_id)
    except ArxivEmptyResultError as e:
        return f"Error: {e}"
    except Exception as e:
        logger.error(f"Failed to fetch metadata for {paper_id}: {e}")
        return f"Error fetching paper metadata: {e}"

    try:
        path = paper.download_pdf(dirpath=str(PAPER_STORAGE), filename=f"{paper_id}.pdf")
        abs_path = str(Path(path).resolve())
        logger.info(f"Downloaded to {abs_path}")
        return abs_path
    except Exception as e:
        logger.error(f"PDF download failed for {paper_id}: {e}")
        return f"Error downloading PDF: {e}"


@mcp.tool()
def list_papers() -> list[str]:
    """List filenames of all downloaded papers."""
    return sorted(f for f in os.listdir(PAPER_STORAGE) if f.endswith(".pdf"))


@mcp.tool()
def read_paper(paper_id: str, max_chars: int = 15000) -> str:
    """
    Read the text content of a downloaded paper.

    Args:
        paper_id: ArXiv ID (e.g. ``"2401.12345"``).
        max_chars: Maximum characters to return (default 15000, keeps token
                   usage bounded for small-context LLMs).
    """
    path = PAPER_STORAGE / f"{paper_id}.pdf"
    if not path.exists():
        return f"Error: Paper {paper_id} not found locally. Download it first."

    try:
        text = extract_pdf_text(path)
    except Exception as e:
        return f"Error reading PDF: {e}"

    if len(text) <= max_chars:
        return text
    return (
        text[:max_chars]
        + f"\n\n[... Content truncated at {max_chars} characters to avoid token limits.]"
    )


# ---------------------------------------------------------------------------
# Human-in-the-loop gate and action logging
# ---------------------------------------------------------------------------


@mcp.tool()
def confirm_download(
    paper_title: str,
    paper_id: str,
    published_date: str,
    abstract: str,
) -> dict[str, Any]:
    """
    Surface a download confirmation card for human review.

    The agent (or the UI) is responsible for actually collecting approval;
    this tool just formats the details in a consistent way and logs the
    request for auditing.
    """
    logger.info(f"Preparing confirmation for download: {paper_title}")

    abstract_preview = abstract[:300] + "..." if len(abstract) > 300 else abstract

    return {
        "status": "awaiting_confirmation",
        "paper_id": paper_id,
        "paper_title": paper_title,
        "published_date": published_date,
        "abstract_preview": abstract_preview,
        "message": (
            f"PAPER DOWNLOAD CONFIRMATION\n\n"
            f"Title: {paper_title}\nPaper ID: {paper_id}\nPublished: {published_date}\n\n"
            f"Abstract Preview:\n{abstract_preview}\n\n"
            f"Respond with 'yes' to download, 'no' to skip, or 'skip' to move to next paper."
        ),
    }


@mcp.tool()
def log_research_action(action: str, paper_id: str, result: str) -> dict[str, str]:
    """Log an agent action to the research_log SQLite DB for later evaluation."""
    db_path = str(_settings.research_log_db)
    try:
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS actions "
                "(timestamp TEXT, action TEXT, paper_id TEXT, result TEXT)"
            )
            conn.execute(
                "INSERT INTO actions (timestamp, action, paper_id, result) VALUES (?, ?, ?, ?)",
                (datetime.now().isoformat(), action, paper_id, str(result)),
            )
        logger.info(f"Logged action: {action}")
        return {"status": "logged", "action": action}
    except sqlite3.DatabaseError as e:
        logger.error(f"Failed to log action: {e}")
        return {"status": "error", "error": str(e)}


if __name__ == "__main__":
    try:
        logger.info("Starting ArXiv MCP Server...")
        mcp.run()
    except Exception as e:
        logger.exception(f"Server crashed: {e}")
        raise
