#!/usr/bin/env python3
"""
Darwin Search Evaluation Module
================================
Compares two search strategies on a fixed query suite and reports metrics.

  Baseline  — raw keyword query passed directly to arXiv (no field scoping)
  Structured — Darwin's field-scoped query engine (ti:/abs: prefixes, dual-pass,
               fallback, stopword removal)

Metrics reported per strategy
------------------------------
  keyword_precision   fraction of results whose title+abstract contain ≥1 query term
  success_rate        fraction of queries that return ≥3 results
  zero_result_rate    fraction of queries that return nothing
  avg_latency_ms      mean wall-clock time per query (milliseconds)

Usage
-----
  python evaluate_search.py            # run full comparison
  python evaluate_search.py --quick    # 4 queries only, faster
"""

import argparse
import csv
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import arxiv
from src.arxiv_server.server import search_papers, _key_terms

# ---------------------------------------------------------------------------
# Fixed test suite
# ---------------------------------------------------------------------------

ALL_QUERIES = [
    {
        "query": "reward hacking in reinforcement learning",
        "expected_categories": {"cs.AI", "cs.LG"},
    },
    {
        "query": "attention mechanism transformer architecture",
        "expected_categories": {"cs.LG", "cs.CL"},
    },
    {
        "query": "federated learning privacy",
        "expected_categories": {"cs.LG", "cs.CR"},
    },
    {
        "query": "diffusion models image generation",
        "expected_categories": {"cs.CV", "cs.LG"},
    },
    {
        "query": "large language model hallucination",
        "expected_categories": {"cs.CL", "cs.AI"},
    },
    {
        "query": "graph neural network node classification",
        "expected_categories": {"cs.LG"},
    },
    {
        "query": "contrastive learning self-supervised representation",
        "expected_categories": {"cs.LG", "cs.CV"},
    },
    {
        "query": "adversarial robustness deep neural network",
        "expected_categories": {"cs.LG", "cs.CR"},
    },
    {
        "query": "knowledge distillation model compression",
        "expected_categories": {"cs.LG"},
    },
    {
        "query": "retrieval augmented generation question answering",
        "expected_categories": {"cs.CL", "cs.IR"},
    },
]

MAX_RESULTS = 8
MIN_SUCCESS_RESULTS = 3  # a query "succeeds" if it returns at least this many papers

# ---------------------------------------------------------------------------
# Baseline searcher
# ---------------------------------------------------------------------------

def baseline_search(query: str, max_results: int = MAX_RESULTS) -> list[dict]:
    """
    Naive baseline: pass the raw query directly to arXiv with no field prefixes.
    This is what a plain arxiv.Search call does — no title/abstract scoping,
    no stopword removal, no structured rewriting.
    """
    client = arxiv.Client()
    search = arxiv.Search(
        query=query,
        max_results=max_results,
        sort_by=arxiv.SortCriterion.Relevance,
    )
    results = []
    try:
        for r in client.results(search):
            authors = ", ".join(a.name for a in r.authors[:3])
            results.append({
                "id": r.get_short_id(),
                "title": r.title,
                "authors": authors,
                "categories": r.categories,
                "summary": r.summary.replace("\n", " "),
            })
    except Exception:
        pass
    return results


def structured_search(query: str, max_results: int = MAX_RESULTS) -> list[dict]:
    """Darwin's structured query engine (field-scoped, dual-pass, fallback)."""
    results = search_papers(
        query=query,
        max_results=max_results,
        categories=["cs.AI", "cs.LG", "stat.ML"],
    )
    # search_papers returns error dicts on failure — filter them out
    return [r for r in results if not r.get("error")]


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def keyword_precision(results: list[dict], query: str) -> float:
    """
    Fraction of returned papers that contain at least one meaningful query term
    in their title or abstract.  Uses the same _key_terms extractor as the
    structured engine so both strategies are judged by the same standard.
    """
    if not results:
        return 0.0
    terms = _key_terms(query)
    if not terms:
        return 1.0
    hits = sum(
        1 for r in results
        if any(t in (r.get("title", "") + " " + r.get("summary", "")).lower()
               for t in terms)
    )
    return hits / len(results)


def category_precision(results: list[dict], expected_categories: set) -> float:
    """
    Fraction of returned papers whose arXiv category list overlaps with the
    expected categories for that query topic.
    """
    if not results:
        return 0.0
    hits = sum(
        1 for r in results
        if set(r.get("categories", [])) & expected_categories
    )
    return hits / len(results)


# ---------------------------------------------------------------------------
# Per-query runner
# ---------------------------------------------------------------------------

def run_query(searcher, query: str, expected_categories: set) -> dict:
    t0 = time.perf_counter()
    results = searcher(query)
    latency_ms = (time.perf_counter() - t0) * 1000
    return {
        "query": query,
        "n_results": len(results),
        "keyword_precision": keyword_precision(results, query),
        "category_precision": category_precision(results, expected_categories),
        "latency_ms": latency_ms,
        "zero_results": len(results) == 0,
        "success": len(results) >= MIN_SUCCESS_RESULTS,
    }


# ---------------------------------------------------------------------------
# Full evaluation run
# ---------------------------------------------------------------------------

def evaluate(searcher, name: str, queries: list[dict]) -> dict:
    print(f"\n{'─' * 64}")
    print(f"  {name}")
    print(f"{'─' * 64}")

    per_query = []
    for item in queries:
        row = run_query(searcher, item["query"], item["expected_categories"])
        per_query.append(row)
        status = "✓" if row["success"] else "✗"
        print(
            f"  {status} "
            f"[{row['n_results']:2d} results | "
            f"kw={row['keyword_precision']:.2f} | "
            f"cat={row['category_precision']:.2f} | "
            f"{row['latency_ms']:.0f}ms]  "
            f"{row['query']}"
        )

    n = len(per_query)
    return {
        "name": name,
        "avg_keyword_precision": sum(r["keyword_precision"] for r in per_query) / n,
        "avg_category_precision": sum(r["category_precision"] for r in per_query) / n,
        "success_rate": sum(r["success"] for r in per_query) / n,
        "zero_result_rate": sum(r["zero_results"] for r in per_query) / n,
        "avg_latency_ms": sum(r["latency_ms"] for r in per_query) / n,
        "per_query": per_query,
    }


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def _delta_str(val: float, higher_is_better: bool, fmt: str) -> str:
    arrow = "↑" if (val > 0) == higher_is_better else "↓"
    return f"{arrow} {fmt.format(abs(val))}"


def print_report(baseline: dict, structured: dict) -> None:
    print(f"\n{'═' * 64}")
    print("  EVALUATION SUMMARY")
    print(f"{'═' * 64}")
    print(f"  {'Metric':<32} {'Baseline':>9} {'Structured':>11} {'Δ':>10}")
    print(f"  {'─' * 62}")

    rows = [
        ("Keyword Precision",    "avg_keyword_precision",  "{:.3f}", True),
        ("Category Precision",   "avg_category_precision", "{:.3f}", True),
        ("Success Rate",         "success_rate",           "{:.3f}", True),
        ("Zero-Result Rate",     "zero_result_rate",       "{:.3f}", False),
        ("Avg Latency (ms)",     "avg_latency_ms",         "{:.0f}", False),
    ]

    for label, key, fmt, higher_is_better in rows:
        b = baseline[key]
        s = structured[key]
        delta = s - b
        delta_str = _delta_str(delta, higher_is_better, fmt)
        print(
            f"  {label:<32} {fmt.format(b):>9} {fmt.format(s):>11} {delta_str:>10}"
        )

    print(f"{'═' * 64}")

    # Overall winner
    wins = sum(
        1 for _, key, _, hib in rows
        if (structured[key] > baseline[key]) == hib
    )
    print(f"\n  Structured engine wins {wins}/{len(rows)} metrics vs baseline.")


def save_results(baseline: dict, structured: dict) -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = f"eval_results_{timestamp}.csv"
    fieldnames = [
        "system", "query", "n_results",
        "keyword_precision", "category_precision",
        "latency_ms", "zero_results", "success",
    ]
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in baseline["per_query"]:
            writer.writerow({"system": "baseline", **row})
        for row in structured["per_query"]:
            writer.writerow({"system": "structured", **row})
    return path


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Darwin search evaluation")
    parser.add_argument(
        "--quick", action="store_true",
        help="Run only the first 4 queries (faster, for smoke-testing)"
    )
    parser.add_argument(
        "--no-save", action="store_true",
        help="Skip saving results to CSV"
    )
    args = parser.parse_args()

    queries = ALL_QUERIES[:4] if args.quick else ALL_QUERIES

    print("=" * 64)
    print("  Darwin Evaluation — Search Engine Comparison")
    print(f"  Queries: {len(queries)}  |  Max results per query: {MAX_RESULTS}")
    print("=" * 64)

    baseline = evaluate(baseline_search, "Baseline (raw arXiv keyword search)", queries)
    structured = evaluate(structured_search, "Structured (Darwin field-scoped engine)", queries)

    print_report(baseline, structured)

    if not args.no_save:
        path = save_results(baseline, structured)
        print(f"\n  Per-query results saved to: {path}\n")


if __name__ == "__main__":
    main()
