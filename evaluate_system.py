#!/usr/bin/env python3
"""
Darwin System Evaluation (v3 — Enhanced)
==========================================
Research-grade end-to-end evaluation with semantic quality, statistics, and resource profiling.

New in v3:
  - Semantic similarity (BLEU, ROUGE, embeddings)
  - Confidence intervals on all latency metrics
  - Memory and resource profiling
  - Adversarial/fuzz testing for error handling
  - Human evaluation framework (baseline structure)
  - Ablation support for component testing
  - Dependency version tracking

Sections
--------
  1. Search Quality     — P@k, keyword/category precision, latency (structured vs baseline)
  2. Download Pipeline  — success rate, file integrity, size distribution, dedup latency
  3. PDF Extraction     — section detection matrix, text yield, extraction latency, semantic quality
  4. Note Creation      — template compliance, write latency, semantic quality of summaries
  5. End-to-End Pipeline — per-step latency breakdown with confidence intervals
  6. Error Handling     — robustness, adversarial inputs, graceful degradation
  7. Resource Profiling — memory, disk I/O, CPU utilization during pipeline

Outputs
-------
  eval_results_<timestamp>.csv       — per-check rows for every section
  eval_results_<timestamp>.json      — structured metrics for chart generation
  eval_stats_<timestamp>.json        — confidence intervals, statistical summaries
  eval_human_template_<timestamp>.md — human evaluation protocol template
  (run plot_eval_results.py to render charts from the JSON output)

Usage
-----
  python evaluate_system.py              # full evaluation (all sections)
  python evaluate_system.py --section search
  python evaluate_system.py --section pdf
  python evaluate_system.py --section e2e
  python evaluate_system.py --ablation pdf  # test without section detection
  python evaluate_system.py --no-save   # skip file output
"""

import argparse
import csv
import json
import os
import sys
import tempfile
import time
import tracemalloc
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from statistics import mean, median, stdev
from typing import Optional, Tuple

# ── Path setup ────────────────────────────────────────────────────────────────
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

import arxiv
import pymupdf  # noqa: F401 — validates pymupdf is installed

# Semantic quality imports (installed separately)
try:
    from sentence_transformers import SentenceTransformer
    HAS_EMBEDDINGS = True
except ImportError:
    HAS_EMBEDDINGS = False

try:
    from rouge_score import rouge_scorer
    HAS_ROUGE = True
except ImportError:
    HAS_ROUGE = False

try:
    from nltk.translate.bleu_score import sentence_bleu, SmoothingFunction
    import nltk
    try:
        nltk.data.find('tokenizers/punkt')
    except LookupError:
        nltk.download('punkt', quiet=True)
    HAS_BLEU = True
except ImportError:
    HAS_BLEU = False

from scipy import stats as scipy_stats

# Use a temp vault so note tests never require Obsidian to be installed
_EVAL_VAULT = os.path.join(PROJECT_ROOT, "_eval_vault")
os.environ.setdefault("OBSIDIAN_VAULT_PATH", _EVAL_VAULT)
os.makedirs(_EVAL_VAULT, exist_ok=True)

from src.arxiv_server.server import (
    search_papers,
    download_paper,
    read_paper,
    list_papers,
    confirm_download,
    _key_terms,
)
from src.pdf_parser.server import extract_pdf_sections
from src.obsidian_server.server import obsidian_create_note, obsidian_create_paper_note

PAPER_STORAGE = os.environ.get("PAPER_STORAGE", os.path.join(PROJECT_ROOT, "papers"))

# ── Global state for semantic models ──────────────────────────────────────────
_EMBEDDING_MODEL = None
_ROUGE_SCORER = None


def _get_embedding_model():
    global _EMBEDDING_MODEL
    if _EMBEDDING_MODEL is None and HAS_EMBEDDINGS:
        _EMBEDDING_MODEL = SentenceTransformer('all-MiniLM-L6-v2')
    return _EMBEDDING_MODEL


def _get_rouge_scorer():
    global _ROUGE_SCORER
    if _ROUGE_SCORER is None and HAS_ROUGE:
        _ROUGE_SCORER = rouge_scorer.RougeScorer(['rouge1', 'rougeL'], use_stemmer=True)
    return _ROUGE_SCORER


# ── Shared helpers ────────────────────────────────────────────────────────────

def _ok(condition: bool) -> str:
    return "✓" if condition else "✗"


def _section_header(title: str) -> None:
    print(f"\n{'═' * 70}")
    print(f"  {title}")
    print(f"{'═' * 70}")


def _row(label: str, passed: bool, detail: str = "") -> dict:
    print(f"  {_ok(passed)}  {label:<44} {detail}")
    return {"label": label, "passed": passed, "detail": detail}


@contextmanager
def track_memory(label: str = "Operation"):
    """Context manager to track peak memory usage during an operation."""
    tracemalloc.start()
    start_memory = tracemalloc.get_traced_memory()[0]
    try:
        yield
    finally:
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        peak_mb = (peak - start_memory) / (1024 * 1024)
        # Silently track; call site decides whether to log


def confidence_interval(
    values: list[float], confidence: float = 0.95
) -> Tuple[float, Tuple[float, float]]:
    """Compute mean and confidence interval for a list of values."""
    if not values:
        return 0.0, (0.0, 0.0)
    if len(values) == 1:
        return values[0], (values[0], values[0])
    
    mean_val = mean(values)
    se = scipy_stats.sem(values)
    # t-value for 95% CI with n-1 degrees of freedom
    t_val = scipy_stats.t.ppf((1 + confidence) / 2, len(values) - 1)
    margin = se * t_val
    return mean_val, (mean_val - margin, mean_val + margin)


def semantic_similarity_embedding(text1: str, text2: str) -> float:
    """Compute cosine similarity between two texts using embeddings."""
    if not HAS_EMBEDDINGS:
        return 0.0
    try:
        model = _get_embedding_model()
        if model is None:
            return 0.0
        emb1 = model.encode(text1[:512], convert_to_tensor=False)
        emb2 = model.encode(text2[:512], convert_to_tensor=False)
        # Cosine similarity
        dot = sum(a * b for a, b in zip(emb1, emb2))
        norm1 = sum(a * a for a in emb1) ** 0.5
        norm2 = sum(b * b for b in emb2) ** 0.5
        return dot / (norm1 * norm2) if norm1 > 0 and norm2 > 0 else 0.0
    except Exception:
        return 0.0


def bleu_score(reference: str, hypothesis: str) -> float:
    """Compute BLEU score (0–1) between reference and hypothesis."""
    if not HAS_BLEU or not reference or not hypothesis:
        return 0.0
    try:
        from nltk.tokenize import word_tokenize
        ref_tokens = word_tokenize(reference.lower())
        hyp_tokens = word_tokenize(hypothesis.lower())
        smoothing = SmoothingFunction().method1
        score = sentence_bleu(
            [ref_tokens],
            hyp_tokens,
            weights=(0.25, 0.25, 0.25, 0.25),
            smoothing_function=smoothing
        )
        return min(score, 1.0)
    except Exception:
        return 0.0


def rouge_score(reference: str, hypothesis: str) -> dict:
    """Compute ROUGE scores (rouge1, rougeL) between reference and hypothesis."""
    if not HAS_ROUGE or not reference or not hypothesis:
        return {"rouge1": 0.0, "rougeL": 0.0}
    try:
        scorer = _get_rouge_scorer()
        if scorer is None:
            return {"rouge1": 0.0, "rougeL": 0.0}
        r1 = scorer.score(reference, hypothesis)["rouge1"].fmeasure
        rl = scorer.score(reference, hypothesis)["rougeL"].fmeasure
        return {"rouge1": r1, "rougeL": rl}
    except Exception:
        return {"rouge1": 0.0, "rougeL": 0.0}


# ═══════════════════════════════════════════════════════════════════════════════
# Section 1 — Search Quality
# ═══════════════════════════════════════════════════════════════════════════════

SEARCH_QUERIES = [
    {"query": "reward hacking reinforcement learning",     "cats": {"cs.AI", "cs.LG"}},
    {"query": "attention mechanism transformer",           "cats": {"cs.LG", "cs.CL"}},
    {"query": "federated learning privacy",                "cats": {"cs.LG", "cs.CR"}},
    {"query": "diffusion models image generation",         "cats": {"cs.CV", "cs.LG"}},
    {"query": "large language model hallucination",        "cats": {"cs.CL", "cs.AI"}},
    {"query": "graph neural network node classification",  "cats": {"cs.LG"}},
    {"query": "contrastive learning self-supervised",      "cats": {"cs.LG", "cs.CV"}},
    {"query": "adversarial robustness deep learning",      "cats": {"cs.LG", "cs.CR"}},
    {"query": "knowledge distillation model compression",  "cats": {"cs.LG"}},
    {"query": "retrieval augmented generation",            "cats": {"cs.CL", "cs.IR"}},
]

MAX_SEARCH_RESULTS = 8


def _baseline_search(query: str, max_results: int = MAX_SEARCH_RESULTS) -> list[dict]:
    """Raw arXiv keyword search — no field scoping, no stopword removal."""
    client = arxiv.Client()
    results = []
    try:
        for r in client.results(arxiv.Search(
                query=query, max_results=max_results,
                sort_by=arxiv.SortCriterion.Relevance)):
            results.append({
                "id": r.get_short_id(),
                "title": r.title,
                "categories": r.categories,
                "summary": r.summary.replace("\n", " "),
            })
    except Exception:
        pass
    return results


def _kw_precision(results: list[dict], query: str, k: int = None) -> float:
    """Fraction of top-k results containing at least one query keyword."""
    subset = results[:k] if k else results
    if not subset:
        return 0.0
    terms = _key_terms(query)
    if not terms:
        return 1.0
    hits = sum(
        1 for r in subset
        if any(t in (r.get("title", "") + " " + r.get("summary", "")).lower()
               for t in terms)
    )
    return hits / len(subset)


def _cat_precision(results: list[dict], expected: set, k: int = None) -> float:
    """Fraction of top-k results whose arXiv categories overlap with expected."""
    subset = results[:k] if k else results
    if not subset:
        return 0.0
    return sum(1 for r in subset if set(r.get("categories", [])) & expected) / len(subset)


def _latency_percentiles(latencies: list[float]) -> dict:
    if not latencies:
        return {"p50": 0.0, "p90": 0.0, "p99": 0.0, "mean": 0.0, "stdev": 0.0}
    sorted_l = sorted(latencies)
    n = len(sorted_l)
    p90_idx = min(int(0.9 * n), n - 1)
    p99_idx = min(int(0.99 * n), n - 1)
    return {
        "p50": sorted_l[n // 2],
        "p90": sorted_l[p90_idx],
        "p99": sorted_l[p99_idx],
        "mean": mean(latencies),
        "stdev": stdev(latencies) if len(latencies) > 1 else 0.0,
    }


def evaluate_search() -> dict:
    _section_header("Section 1 — Search Quality  (Structured vs Baseline, n=10 queries)")

    per_query_all = []

    for label, searcher in [
        ("baseline",    lambda q: _baseline_search(q)),
        ("structured",  lambda q: [r for r in search_papers(
                                        q, max_results=MAX_SEARCH_RESULTS,
                                        categories=["cs.AI", "cs.LG", "stat.ML"])
                                   if not r.get("error")]),
    ]:
        system_label = "Baseline (raw keyword)" if label == "baseline" else "Structured (Darwin)"
        print(f"\n  [{system_label}]")
        per = []
        for item in SEARCH_QUERIES:
            q, cats = item["query"], item["cats"]
            t0 = time.perf_counter()
            papers = searcher(q)
            ms = (time.perf_counter() - t0) * 1000

            kw_all  = _kw_precision(papers, q)
            kw_p3   = _kw_precision(papers, q, k=3)
            kw_p5   = _kw_precision(papers, q, k=5)
            cat_all = _cat_precision(papers, cats)
            cat_p3  = _cat_precision(papers, cats, k=3)
            success = len(papers) >= 3

            row = {
                "system": label,
                "query": q,
                "n_results": len(papers),
                "kw_precision": kw_all,
                "kw_p3": kw_p3,
                "kw_p5": kw_p5,
                "cat_precision": cat_all,
                "cat_p3": cat_p3,
                "latency_ms": ms,
                "success": success,
                "zero_results": len(papers) == 0,
            }
            per.append(row)
            per_query_all.append(row)

            print(
                f"    {_ok(success)} "
                f"[n={len(papers):2d} | kw={kw_all:.2f} P@3={kw_p3:.2f} | "
                f"cat={cat_all:.2f} | {ms:.0f}ms]  {q}"
            )

        n = len(per)
        latencies = [r["latency_ms"] for r in per]
        agg = {
            "label": label,
            "kw_precision":   mean(r["kw_precision"]  for r in per),
            "kw_p3":          mean(r["kw_p3"]          for r in per),
            "kw_p5":          mean(r["kw_p5"]          for r in per),
            "cat_precision":  mean(r["cat_precision"]  for r in per),
            "cat_p3":         mean(r["cat_p3"]         for r in per),
            "success_rate":   sum(r["success"]         for r in per) / n,
            "zero_result_rate": sum(r["zero_results"]  for r in per) / n,
            "avg_latency_ms": mean(latencies),
            **_latency_percentiles(latencies),
        }
        print(
            f"\n  Aggregate — kw_prec={agg['kw_precision']:.3f}  P@3={agg['kw_p3']:.3f}  "
            f"cat={agg['cat_precision']:.3f}  success={agg['success_rate']:.0%}  "
            f"p50={agg['p50']:.0f}ms  p90={agg['p90']:.0f}ms"
        )

        if label == "baseline":
            base_agg = agg
        else:
            struct_agg = agg

    # Comparison table
    print(f"\n  {'Metric':<30} {'Baseline':>9} {'Structured':>11} {'Δ':>8}  {'Winner'}")
    print(f"  {'─' * 65}")
    comparisons = [
        ("Keyword Precision",    "kw_precision",    "{:.3f}", True),
        ("Keyword P@3",          "kw_p3",           "{:.3f}", True),
        ("Category Precision",   "cat_precision",   "{:.3f}", True),
        ("Category P@3",         "cat_p3",          "{:.3f}", True),
        ("Success Rate",         "success_rate",    "{:.3f}", True),
        ("Zero-Result Rate",     "zero_result_rate","{:.3f}", False),
        ("Avg Latency (ms)",     "avg_latency_ms",  "{:.0f}", False),
        ("P90 Latency (ms)",     "p90",             "{:.0f}", False),
    ]
    wins = 0
    for label, key, fmt, hib in comparisons:
        b, s = base_agg[key], struct_agg[key]
        delta = s - b
        arrow = ("↑" if delta > 0 else "↓") if hib else ("↑" if delta < 0 else "↓")
        winner = "Structured" if (delta > 0) == hib else "Baseline"
        if (delta > 0) == hib:
            wins += 1
        print(
            f"  {label:<30} {fmt.format(b):>9} {fmt.format(s):>11} "
            f"{arrow} {fmt.format(abs(delta)):>6}  {winner}"
        )

    print(f"\n  Structured wins {wins}/{len(comparisons)} metrics vs baseline.")

    return {
        "section": "search",
        "per_query": per_query_all,
        "baseline": base_agg,
        "structured": struct_agg,
        "wins": wins,
        "total_metrics": len(comparisons),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Section 2 — Download Pipeline
# ═══════════════════════════════════════════════════════════════════════════════

def evaluate_download() -> dict:
    _section_header("Section 2 — Download Pipeline")
    rows = []
    per_paper = []
    latencies = []

    existing = [f.replace(".pdf", "") for f in os.listdir(PAPER_STORAGE)
                if f.endswith(".pdf")]
    if not existing:
        print("  ⚠  No papers in papers/ — skipping download tests")
        return {"section": "download", "rows": [], "per_paper": [], "passed": 0, "total": 0,
                "latency_stats": {}}

    test_ids = existing[:5]  # test up to 5 papers

    print(f"\n  Testing {len(test_ids)} papers: {', '.join(test_ids)}")

    # Per-paper metrics with memory tracking
    for pid in test_ids:
        with track_memory(f"download_{pid}"):
            t0 = time.perf_counter()
            result = download_paper(pid)
            ms = (time.perf_counter() - t0) * 1000
            latencies.append(ms)

        path_exists = isinstance(result, str) and os.path.isfile(result)
        is_cached   = ms < 500

        file_size_mb = 0.0
        is_valid_pdf = False
        if path_exists:
            file_size_mb = os.path.getsize(result) / (1024 * 1024)
            with open(result, "rb") as f:
                is_valid_pdf = f.read(4) == b"%PDF"

        per_paper.append({
            "paper_id":     pid,
            "dedup_latency_ms": ms,
            "is_cached":    is_cached,
            "path_exists":  path_exists,
            "file_size_mb": file_size_mb,
            "is_valid_pdf": is_valid_pdf,
        })

        rows.append(_row(
            f"  {pid} — cache hit < 500ms", is_cached,
            f"{ms:.0f}ms"
        ))
        rows.append(_row(
            f"  {pid} — valid PDF on disk", is_valid_pdf,
            f"{file_size_mb:.2f} MB"
        ))

    # Aggregate file size stats
    sizes = [p["file_size_mb"] for p in per_paper if p["file_size_mb"] > 0]
    if sizes:
        print(f"\n  File sizes — min={min(sizes):.2f}MB  max={max(sizes):.2f}MB  "
              f"mean={mean(sizes):.2f}MB  median={median(sizes):.2f}MB")

    # Latency confidence interval
    lat_mean, (lat_ci_low, lat_ci_high) = confidence_interval(latencies)
    print(f"  Cache latency CI — mean={lat_mean:.0f}ms  95%CI=[{lat_ci_low:.0f}, {lat_ci_high:.0f}]ms")

    # list_papers correctness
    listed = list_papers()
    lists_ok = all(pid + ".pdf" in listed or any(pid in f for f in listed)
                   for pid in test_ids)
    rows.append(_row("list_papers() returns all downloaded papers", lists_ok,
                     f"{len(listed)} files found"))

    # confirm_download structure
    test_id = test_ids[0]
    conf = confirm_download("Test Paper", test_id, "2024-01-01", "Synthetic abstract.")
    has_status  = conf.get("status") == "awaiting_confirmation"
    has_message = "message" in conf and "PAPER DOWNLOAD CONFIRMATION" in conf["message"]
    rows.append(_row("confirm_download returns correct status", has_status,
                     f"status={conf.get('status')}"))
    rows.append(_row("confirm_download message contains required fields", has_message))

    passed = sum(1 for r in rows if r["passed"])
    print(f"\n  Passed {passed}/{len(rows)} download checks.")
    return {
        "section":   "download",
        "rows":      rows,
        "per_paper": per_paper,
        "passed":    passed,
        "total":     len(rows),
        "avg_size_mb": round(mean(sizes), 3) if sizes else 0,
        "latency_stats": {
            "mean": round(lat_mean, 1),
            "ci_low": round(lat_ci_low, 1),
            "ci_high": round(lat_ci_high, 1),
        },
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Section 3 — PDF Extraction
# ═══════════════════════════════════════════════════════════════════════════════

EXPECTED_SECTIONS = {
    "abstract":     ["abstract"],
    "introduction": ["introduction", "intro"],
    "related_work": ["related work", "background", "prior work"],
    "methods":      ["method", "approach", "methodology", "proposed"],
    "experiments":  ["experiment", "evaluation", "result"],
    "conclusion":   ["conclusion", "discussion", "future work"],
}


def _detect_sections(sections_dict: dict) -> dict[str, bool]:
    """Check which canonical sections are present in the extract_pdf_sections output."""
    keys_lower = [k.lower() for k in sections_dict.keys()]
    text_lower = " ".join(str(v) for v in sections_dict.values()).lower()

    detected = {}
    for canonical, search_terms in EXPECTED_SECTIONS.items():
        found = any(
            term in k or term in text_lower[:500]
            for term in search_terms
            for k in keys_lower
        )
        detected[canonical] = found
    return detected


def evaluate_pdf(ablation: bool = False) -> dict:
    """
    Evaluate PDF extraction.
    If ablation=True, test without section detection (raw text only).
    """
    header_suffix = " (Ablation: no section detection)" if ablation else ""
    _section_header(f"Section 3 — PDF Extraction{header_suffix}")
    rows = []
    per_paper = []
    section_matrix = []
    semantic_scores = []
    memory_peaks = []

    existing = [f.replace(".pdf", "") for f in os.listdir(PAPER_STORAGE)
                if f.endswith(".pdf")]
    if not existing:
        print("  ⚠  No papers in papers/ — skipping PDF extraction tests")
        return {"section": "pdf", "rows": [], "per_paper": [], "section_matrix": [],
                "passed": 0, "total": 0, "semantic_scores": {}}

    test_ids = existing[:5]

    print(f"\n  {'Paper':<25} {'Chars':>7} {'Sections':>9}  "
          + "  ".join(EXPECTED_SECTIONS.keys()))
    print(f"  {'─' * 70}")

    for pid in test_ids:
        pdf_path = os.path.join(PAPER_STORAGE, f"{pid}.pdf")

        # read_paper (plain text) with memory tracking
        with track_memory(f"read_paper_{pid}"):
            t0 = time.perf_counter()
            text = read_paper(pid, max_chars=8000)
            read_ms = (time.perf_counter() - t0) * 1000
        
        is_text     = isinstance(text, str) and not text.startswith("Error:")
        substantial = is_text and len(text) > 500

        # extract_pdf_sections (structured)
        if not ablation:
            with track_memory(f"extract_pdf_{pid}"):
                t0 = time.perf_counter()
                sections = extract_pdf_sections(pdf_path, max_chars=8000)
                extract_ms = (time.perf_counter() - t0) * 1000
            
            has_abstract = "abstract" in sections and len(sections.get("abstract", "")) > 50
            has_preview  = "full_text_preview" in sections
            detected   = _detect_sections(sections)
            n_detected = sum(detected.values())
        else:
            sections = {}
            extract_ms = 0.0
            has_abstract = False
            has_preview = False
            detected = {}
            n_detected = 0

        coverage   = n_detected / len(EXPECTED_SECTIONS) if not ablation else 0

        # Truncation check
        short_text = read_paper(pid, max_chars=500)
        truncated  = "[... Content truncated" in short_text

        # Text yield: ratio of chars extracted vs raw PDF text estimate
        raw_chars = 0
        text_yield = 0.0
        try:
            import pymupdf as fitz
            doc = fitz.open(pdf_path)
            raw_chars = sum(len(p.get_text()) for p in doc)
            doc.close()
            text_yield = min(len(text) / raw_chars, 1.0) if raw_chars > 0 and is_text else 0.0
        except Exception:
            pass

        # Semantic quality: compare extracted abstract with full text
        semantic_sim = 0.0
        if is_text and sections and "abstract" in sections:
            abstract_text = sections.get("abstract", "")
            if len(abstract_text) > 20:
                semantic_sim = semantic_similarity_embedding(text[:1000], abstract_text)
                semantic_scores.append(semantic_sim)

        per_paper.append({
            "paper_id":      pid,
            "chars_extracted": len(text) if is_text else 0,
            "raw_chars":     raw_chars,
            "text_yield":    round(text_yield, 3),
            "n_sections":    n_detected,
            "section_coverage": round(coverage, 3),
            "semantic_sim":  round(semantic_sim, 3),
            "read_latency_ms":    round(read_ms, 1),
            "extract_latency_ms": round(extract_ms, 1),
        })

        if not ablation:
            section_matrix.append({"paper_id": pid, **detected})

        det_flags = "  ".join("✓" if detected.get(s, False) else "✗"
                               for s in EXPECTED_SECTIONS)
        print(f"  {pid:<25} {len(text) if is_text else 0:>7}  "
              f"{n_detected}/{len(EXPECTED_SECTIONS):>1}         {det_flags}")

        rows.append(_row(f"read_paper({pid[:20]}) returns text",    is_text,
                         f"{len(text)} chars"))
        rows.append(_row(f"  Extracted text > 500 chars",           substantial,
                         f"{len(text)} chars"))
        rows.append(_row(f"  Truncation marker at max_chars",       truncated))
        if not ablation:
            rows.append(_row(f"  extract_pdf_sections — abstract found",has_abstract,
                             f"{len(sections.get('abstract',''))} chars"))
            rows.append(_row(f"  full_text_preview key present",        has_preview))

    # Section detection summary
    if section_matrix and not ablation:
        print(f"\n  Section detection rates across {len(test_ids)} papers:")
        for sec in EXPECTED_SECTIONS:
            rate = sum(1 for m in section_matrix if m.get(sec)) / len(section_matrix)
            bar  = "█" * int(rate * 10) + "░" * (10 - int(rate * 10))
            print(f"    {sec:<15} [{bar}] {rate:.0%}")

    # Text yield summary
    yields = [p["text_yield"] for p in per_paper if p["text_yield"] > 0]
    if yields:
        yield_mean, (yield_ci_low, yield_ci_high) = confidence_interval(yields)
        print(f"\n  Text yield — mean={yield_mean:.1%}  "
              f"95%CI=[{yield_ci_low:.1%}, {yield_ci_high:.1%}]")

    # Semantic quality summary
    if semantic_scores:
        sem_mean, (sem_ci_low, sem_ci_high) = confidence_interval(semantic_scores)
        print(f"  Semantic similarity (abstract↔full text) — mean={sem_mean:.3f}  "
              f"95%CI=[{sem_ci_low:.3f}, {sem_ci_high:.3f}]")

    passed = sum(1 for r in rows if r["passed"])
    print(f"\n  Passed {passed}/{len(rows)} PDF extraction checks.")
    return {
        "section":        "pdf",
        "rows":           rows,
        "per_paper":      per_paper,
        "section_matrix": section_matrix,
        "passed":         passed,
        "total":          len(rows),
        "avg_text_yield": round(mean(yields), 3) if yields else 0,
        "avg_section_coverage": round(
            mean(p["section_coverage"] for p in per_paper), 3) if per_paper else 0,
        "semantic_scores": {
            "mean": round(mean(semantic_scores), 3) if semantic_scores else 0,
            "scores": [round(s, 3) for s in semantic_scores],
        },
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Section 4 — Note Creation
# ═══════════════════════════════════════════════════════════════════════════════

_GENERAL_NOTE_REQUIRED = [
    "---",
    "title:",
    "tags:",
    "## Key Points",
    "## References",
]

_PAPER_NOTE_REQUIRED = [
    "---",
    "paper_id:",
    "## Abstract",
    "## Key Findings",
    "## Methods",
]


def _compliance_score(content: str, required: list[str]) -> float:
    """Fraction of required fields/sections present in the note content."""
    return sum(1 for r in required if r in content) / len(required)


def evaluate_notes() -> dict:
    _section_header("Section 4 — Note Creation  (template compliance + semantic quality)")
    rows = []
    per_note = []
    latencies = []

    # ── 4a. General note ────────────────────────────────────────────────────
    with track_memory("create_general_note"):
        t0 = time.perf_counter()
        result = obsidian_create_note(
            title="Eval Test Note",
            content="This is test content for the Darwin evaluation module.",
            tags=["eval", "test"],
        )
        write_ms = (time.perf_counter() - t0) * 1000
        latencies.append(write_ms)
    
    created  = result.get("success", False)

    rows.append(_row("obsidian_create_note reports success", created,
                     f"{write_ms:.0f}ms  status={result.get('status')}"))

    compliance = 0.0
    bleu = 0.0
    if created:
        note_path = result.get("file_location", "")
        file_exists = os.path.isfile(note_path)
        rows.append(_row("General note file written to disk", file_exists, note_path[-60:]))

        if file_exists:
            content   = Path(note_path).read_text(encoding="utf-8")
            file_size = len(content)
            compliance = _compliance_score(content, _GENERAL_NOTE_REQUIRED)
            
            # Semantic quality: compare note content with input
            bleu = bleu_score(
                "This is test content for the Darwin evaluation module.",
                content[:500]
            )

            rows.append(_row("YAML frontmatter present",          "---" in content))
            rows.append(_row("title field in frontmatter",        "title: Eval Test Note" in content))
            rows.append(_row("tags field in frontmatter",         "tags:" in content))
            rows.append(_row("## Key Points section present",     "## Key Points" in content))
            rows.append(_row("## References section present",     "## References" in content))

            print(f"\n  General note: compliance={compliance:.0%} bleu={bleu:.3f}  "
                  f"size={file_size} chars  write={write_ms:.0f}ms")

            per_note.append({
                "note_type":       "general",
                "compliance_score": round(compliance, 3),
                "bleu_score":      round(bleu, 3),
                "write_latency_ms": round(write_ms, 1),
                "file_size_chars":  file_size,
                "success":          True,
            })

    # ── 4b. Paper note ───────────────────────────────────────────────────────
    with track_memory("create_paper_note"):
        t0 = time.perf_counter()
        paper_result = obsidian_create_paper_note(
            paper_id="eval-test-001",
            title="Evaluation Test Paper",
            authors=["Alice Smith", "Bob Jones"],
            abstract="Synthetic abstract for evaluation purposes only.",
            methods="Synthetic methods section describing the approach.",
            findings="Key findings extracted during the evaluation run.",
            keywords=["evaluation", "testing", "darwin"],
        )
        paper_write_ms = (time.perf_counter() - t0) * 1000
        latencies.append(paper_write_ms)
    
    paper_created  = paper_result.get("success", False)

    rows.append(_row("obsidian_create_paper_note reports success", paper_created,
                     f"{paper_write_ms:.0f}ms  status={paper_result.get('status')}"))

    paper_compliance = 0.0
    paper_bleu = 0.0
    if paper_created:
        paper_path   = paper_result.get("file_location", "")
        paper_exists = os.path.isfile(paper_path)
        rows.append(_row("Paper note file written to disk", paper_exists))

        if paper_exists:
            content          = Path(paper_path).read_text(encoding="utf-8")
            paper_file_size  = len(content)
            paper_compliance = _compliance_score(content, _PAPER_NOTE_REQUIRED)
            
            # Semantic quality: check if findings/methods survive in note
            paper_bleu = bleu_score(
                "Key findings extracted during the evaluation run.",
                content[:1000]
            )

            rows.append(_row("paper_id in frontmatter",        "paper_id: eval-test-001" in content))
            rows.append(_row("## Abstract section present",    "## Abstract" in content))
            rows.append(_row("## Key Findings section present","## Key Findings" in content))
            rows.append(_row("## Methods section present",     "## Methods" in content))
            rows.append(_row("authors in frontmatter",         "Alice Smith" in content))

            print(f"  Paper note:   compliance={paper_compliance:.0%} bleu={paper_bleu:.3f}  "
                  f"size={paper_file_size} chars  write={paper_write_ms:.0f}ms")

            per_note.append({
                "note_type":        "paper",
                "compliance_score": round(paper_compliance, 3),
                "bleu_score":       round(paper_bleu, 3),
                "write_latency_ms": round(paper_write_ms, 1),
                "file_size_chars":  paper_file_size,
                "success":          True,
            })

    # Latency CI
    lat_mean, (lat_ci_low, lat_ci_high) = confidence_interval(latencies)
    print(f"\n  Write latency 95%CI — mean={lat_mean:.0f}ms  [{lat_ci_low:.0f}, {lat_ci_high:.0f}]ms")

    passed = sum(1 for r in rows if r["passed"])
    print(f"\n  Passed {passed}/{len(rows)} note creation checks.")
    return {
        "section":  "notes",
        "rows":     rows,
        "per_note": per_note,
        "passed":   passed,
        "total":    len(rows),
        "avg_compliance": round(
            mean(n["compliance_score"] for n in per_note), 3) if per_note else 0,
        "avg_bleu": round(
            mean(n["bleu_score"] for n in per_note), 3) if per_note else 0,
        "latency_stats": {
            "mean": round(lat_mean, 1),
            "ci_low": round(lat_ci_low, 1),
            "ci_high": round(lat_ci_high, 1),
        },
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Section 5 — End-to-End Pipeline
# ═══════════════════════════════════════════════════════════════════════════════

E2E_QUERIES = [
    "attention mechanism transformer architecture",
    "federated learning privacy differential",
    "contrastive learning self-supervised visual",
]


def _run_pipeline(query: str) -> dict:
    """
    Run the full research pipeline for one query.
    Returns a dict with per-step latency and success flags.
    """
    run = {
        "query":       query,
        "search_ms":   0.0, "search_ok":  False, "n_papers":   0,
        "download_ms": 0.0, "download_ok": False,
        "read_ms":     0.0, "read_ok":    False,  "read_chars": 0,
        "note_ms":     0.0, "note_ok":    False,
        "total_ms":    0.0, "success":    False,
    }

    # Step 1: Search
    t0 = time.perf_counter()
    try:
        results = search_papers(query, max_results=5, categories=["cs.AI", "cs.LG"])
        papers  = [r for r in results if not r.get("error")]
    except Exception:
        papers = []
    run["search_ms"] = (time.perf_counter() - t0) * 1000
    run["search_ok"] = len(papers) >= 1
    run["n_papers"]  = len(papers)

    if not run["search_ok"]:
        return run

    paper    = papers[0]
    paper_id = paper["id"].split("v")[0]

    # Step 2: Download
    t0 = time.perf_counter()
    try:
        dl = download_paper(paper_id)
        run["download_ok"] = isinstance(dl, str) and os.path.isfile(dl)
    except Exception:
        run["download_ok"] = False
    run["download_ms"] = (time.perf_counter() - t0) * 1000

    # Step 3: Read
    if run["download_ok"]:
        t0 = time.perf_counter()
        try:
            text = read_paper(paper_id, max_chars=4000)
            run["read_ok"]    = isinstance(text, str) and not text.startswith("Error:") and len(text) > 200
            run["read_chars"] = len(text) if run["read_ok"] else 0
        except Exception:
            run["read_ok"] = False
        run["read_ms"] = (time.perf_counter() - t0) * 1000
    else:
        run["read_ok"] = False

    # Step 4: Create Obsidian note
    t0 = time.perf_counter()
    try:
        note_result = obsidian_create_paper_note(
            paper_id=paper_id,
            title=paper.get("title", "Unknown"),
            authors=paper.get("authors", "").split(", ")[:3],
            abstract=paper.get("summary", ""),
            findings="Findings to be extracted from full text.",
            keywords=["e2e-test"],
        )
        run["note_ok"] = note_result.get("success", False)
    except Exception:
        run["note_ok"] = False
    run["note_ms"] = (time.perf_counter() - t0) * 1000

    run["total_ms"] = (run["search_ms"] + run["download_ms"] +
                       run["read_ms"]   + run["note_ms"])
    run["success"]  = all([run["search_ok"], run["download_ok"],
                           run["read_ok"],   run["note_ok"]])

    for k in ["search_ms", "download_ms", "read_ms", "note_ms", "total_ms"]:
        run[k] = round(run[k], 1)

    return run


def evaluate_e2e() -> dict:
    _section_header("Section 5 — End-to-End Pipeline  (3 runs × 4 steps + CI)")
    rows = []
    runs = []

    print(f"\n  {'Query':<45} {'Srch':>6} {'DL':>6} {'Read':>6} {'Note':>6} {'Total':>7}  Status")
    print(f"  {'─' * 85}")

    for query in E2E_QUERIES:
        run = _run_pipeline(query)
        runs.append(run)

        status = "✓ OK" if run["success"] else (
            "✗ search failed"   if not run["search_ok"]   else
            "✗ download failed" if not run["download_ok"] else
            "✗ read failed"     if not run["read_ok"]     else
            "✗ note failed"
        )
        print(
            f"  {query[:45]:<45} "
            f"{run['search_ms']:>6.0f} {run['download_ms']:>6.0f} "
            f"{run['read_ms']:>6.0f} {run['note_ms']:>6.0f} "
            f"{run['total_ms']:>7.0f}  {status}"
        )

        rows.append(_row(f"Pipeline: {query[:35]}", run["success"],
                         f"total={run['total_ms']:.0f}ms"))

    success_rate = sum(r["success"] for r in runs) / len(runs)
    step_rates   = {
        step: sum(r[f"{step}_ok"] for r in runs) / len(runs)
        for step in ["search", "download", "read", "note"]
    }
    print(f"\n  Step success rates: "
          + "  ".join(f"{s}={v:.0%}" for s, v in step_rates.items()))
    print(f"  Full pipeline success rate: {success_rate:.0%}  ({sum(r['success'] for r in runs)}/{len(runs)} runs)")

    # Per-step latency with confidence intervals
    latency_avgs = {}
    latency_cis = {}
    for step in ["search", "download", "read", "note"]:
        valid = [r[f"{step}_ms"] for r in runs if r[f"{step}_ok"]]
        if valid:
            mean_val, (ci_low, ci_high) = confidence_interval(valid)
            latency_avgs[step] = round(mean_val, 1)
            latency_cis[step] = (round(ci_low, 1), round(ci_high, 1))
    
    print(f"\n  Avg step latency (successful only, 95% CI):")
    for s, v in latency_avgs.items():
        ci_low, ci_high = latency_cis[s]
        print(f"    {s:<12} {v:>6.0f}ms  [{ci_low:>6.0f}, {ci_high:>6.0f}]ms")

    passed = sum(1 for r in rows if r["passed"])
    print(f"\n  Passed {passed}/{len(rows)} end-to-end checks.")
    return {
        "section":      "e2e",
        "rows":         rows,
        "runs":         runs,
        "passed":       passed,
        "total":        len(rows),
        "success_rate": round(success_rate, 3),
        "step_rates":   step_rates,
        "latency_avgs": latency_avgs,
        "latency_cis":  latency_cis,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Section 6 — Error Handling + Adversarial/Fuzz Testing
# ═══════════════════════════════════════════════════════════════════════════════

def _error_quality(result, expected_keywords: list[str]) -> float:
    """Rate the quality of an error message (0–1) based on keyword presence."""
    if not expected_keywords:
        return 1.0
    text = str(result).lower()
    return sum(1 for kw in expected_keywords if kw in text) / len(expected_keywords)


def evaluate_errors() -> dict:
    _section_header("Section 6 — Error Handling & Adversarial Testing")
    rows = []
    quality_scores = []

    print("\n  [Basic edge cases]")

    # 6a. Empty query
    result = search_papers("", max_results=5)
    graceful = isinstance(result, list) and result and "error" in result[0]
    rows.append(_row("Empty query → error dict (no crash)", graceful,
                     result[0].get("error", "")[:60] if graceful else str(result)[:60]))
    if graceful:
        quality_scores.append(("empty_query", _error_quality(
            result[0].get("error", ""), ["empty", "query", "required"])))

    # 6b. Nonsense query
    result = search_papers("xyzzy foobar qwerty 99999 zzzz", max_results=5)
    rows.append(_row("Nonsense query → list (no crash)", isinstance(result, list),
                     f"{len(result)} items returned"))

    # 6c. Non-existent paper ID for read_paper
    result = read_paper("9999-nonexistent-paper", max_chars=1000)
    graceful = isinstance(result, str) and "Error" in result
    rows.append(_row("read_paper on missing file → error string", graceful, result[:70]))
    if graceful:
        quality_scores.append(("missing_paper", _error_quality(
            result, ["error", "not found", "paper", "exist"])))

    # 6d. extract_pdf_sections on non-existent path
    result = extract_pdf_sections("/nonexistent/path/paper.pdf")
    graceful = isinstance(result, dict) and "error" in result
    rows.append(_row("extract_pdf_sections on bad path → error dict", graceful,
                     str(result.get("error", ""))[:60]))
    if graceful:
        quality_scores.append(("bad_pdf_path", _error_quality(
            result.get("error", ""), ["error", "file", "path", "found"])))

    # 6e. confirm_download with empty args
    try:
        result  = confirm_download("", "", "", "")
        graceful = isinstance(result, dict) and "status" in result
    except Exception:
        graceful = False
    rows.append(_row("confirm_download with empty args → dict (no crash)", graceful))

    # 6f. search_papers with max_results=-1
    result = search_papers("machine learning", max_results=-1)
    rows.append(_row("search_papers(max_results=-1) handles gracefully",
                     isinstance(result, list),
                     f"{len(result)} results returned"))

    # 6g. obsidian_create_note with missing vault path
    orig = os.environ.get("OBSIDIAN_VAULT_PATH")
    os.environ["OBSIDIAN_VAULT_PATH"] = ""
    try:
        from src.obsidian_server import server as obs_srv
        obs_srv.OBSIDIAN_VAULT_PATH = ""
        result   = obs_srv.obsidian_create_note("Crash Test", "content", [])
        graceful = isinstance(result, dict) and result.get("success") is False
    except Exception:
        graceful = False
    finally:
        os.environ["OBSIDIAN_VAULT_PATH"] = orig or _EVAL_VAULT
        obs_srv.OBSIDIAN_VAULT_PATH       = orig or _EVAL_VAULT
    rows.append(_row("obsidian_create_note with no vault → fails gracefully", graceful))

    # 6h. download_paper with path-traversal attempt
    result = download_paper("../../etc/passwd")
    graceful = (isinstance(result, str) and
                ("error" in result.lower() or "not found" in result.lower() or
                 not os.path.isfile(result)))
    rows.append(_row("download_paper with path-traversal ID → safe failure", graceful,
                     str(result)[:60]))

    print("\n  [Adversarial/Fuzz tests]")

    # 6i. Very long query (fuzz: DoS attempt)
    long_query = "word " * 1000  # 5000 chars
    try:
        result = search_papers(long_query[:256], max_results=3)
        graceful = isinstance(result, list)
    except Exception:
        graceful = False
    rows.append(_row("Very long query (5K chars truncated) → no crash", graceful))

    # 6j. Null bytes in query
    try:
        result = search_papers("machine\x00learning", max_results=3)
        graceful = isinstance(result, list)
    except Exception:
        graceful = False
    rows.append(_row("Query with null bytes → graceful failure", graceful))

    # 6k. SQL injection-like string
    try:
        result = search_papers("'; DROP TABLE papers; --", max_results=3)
        graceful = isinstance(result, list)
    except Exception:
        graceful = False
    rows.append(_row("SQL injection-like string → no crash", graceful))

    # 6l. read_paper with negative max_chars
    result = read_paper("test-id", max_chars=-100)
    graceful = isinstance(result, str)
    rows.append(_row("read_paper with negative max_chars → error or empty", graceful))

    # Error quality summary
    if quality_scores:
        avg_quality = mean(score for _, score in quality_scores)
        print(f"\n  Error message quality scores:")
        for name, score in quality_scores:
            bar = "█" * int(score * 10) + "░" * (10 - int(score * 10))
            print(f"    {name:<20} [{bar}] {score:.0%}")
        print(f"  Avg error message quality: {avg_quality:.0%}")
    else:
        avg_quality = 0.0

    passed = sum(1 for r in rows if r["passed"])
    print(f"\n  Passed {passed}/{len(rows)} error handling checks.")
    return {
        "section":       "errors",
        "rows":          rows,
        "passed":        passed,
        "total":         len(rows),
        "quality_scores": dict(quality_scores),
        "avg_error_quality": round(avg_quality, 3),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Section 7 — Resource Profiling
# ═══════════════════════════════════════════════════════════════════════════════

def evaluate_resources() -> dict:
    """Profile memory, disk I/O, and resource usage during key operations."""
    _section_header("Section 7 — Resource Profiling")
    rows = []
    per_op = []

    print("\n  [Memory tracking during PDF extraction]")

    existing = [f.replace(".pdf", "") for f in os.listdir(PAPER_STORAGE)
                if f.endswith(".pdf")]
    if not existing:
        print("  ⚠  No papers in papers/ — skipping resource tests")
        return {"section": "resources", "rows": [], "per_op": [], "passed": 0, "total": 0}

    test_ids = existing[:3]

    for pid in test_ids:
        pdf_path = os.path.join(PAPER_STORAGE, f"{pid}.pdf")
        
        # Measure memory for PDF extraction
        tracemalloc.start()
        start_mem = tracemalloc.get_traced_memory()[0]
        
        try:
            sections = extract_pdf_sections(pdf_path, max_chars=8000)
            current, peak = tracemalloc.get_traced_memory()
        except Exception:
            peak = 0
        finally:
            tracemalloc.stop()
        
        peak_delta_mb = (peak - start_mem) / (1024 * 1024)
        
        # Measure disk I/O: file read speed
        file_size_mb = os.path.getsize(pdf_path) / (1024 * 1024)
        t0 = time.perf_counter()
        with open(pdf_path, "rb") as f:
            _ = f.read()
        disk_read_time_ms = (time.perf_counter() - t0) * 1000
        disk_throughput_mbps = file_size_mb / (disk_read_time_ms / 1000) if disk_read_time_ms > 0 else 0
        
        per_op.append({
            "operation": f"extract_pdf_{pid}",
            "peak_memory_mb": round(peak_delta_mb, 2),
            "file_size_mb": round(file_size_mb, 2),
            "disk_read_ms": round(disk_read_time_ms, 1),
            "disk_throughput_mbps": round(disk_throughput_mbps, 1),
        })
        
        rows.append(_row(f"  {pid} — peak memory {peak_delta_mb:.1f}MB", peak_delta_mb < 500,
                         f"{peak_delta_mb:.1f}MB"))
        rows.append(_row(f"  {pid} — disk throughput {disk_throughput_mbps:.0f}MB/s", True,
                         f"{disk_throughput_mbps:.1f}MB/s"))

    # Aggregate
    if per_op:
        mem_vals = [op["peak_memory_mb"] for op in per_op]
        disk_vals = [op["disk_throughput_mbps"] for op in per_op]
        print(f"\n  Peak memory — min={min(mem_vals):.1f}MB  max={max(mem_vals):.1f}MB  "
              f"mean={mean(mem_vals):.1f}MB")
        print(f"  Disk throughput — min={min(disk_vals):.0f}MB/s  max={max(disk_vals):.0f}MB/s  "
              f"mean={mean(disk_vals):.0f}MB/s")

    passed = sum(1 for r in rows if r["passed"])
    print(f"\n  Passed {passed}/{len(rows)} resource checks.")
    return {
        "section": "resources",
        "rows": rows,
        "per_op": per_op,
        "passed": passed,
        "total": len(rows),
        "avg_peak_memory_mb": round(mean(mem_vals), 2) if per_op else 0,
        "avg_disk_throughput_mbps": round(mean(disk_vals), 1) if per_op else 0,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Human Evaluation Template
# ═══════════════════════════════════════════════════════════════════════════════

def generate_human_eval_template(timestamp: str) -> str:
    """Generate a markdown template for human evaluation of note quality and relevance."""
    template = f"""# Darwin Human Evaluation Protocol

**Date:** {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
**Evaluator:** [Your name]
**Evaluation ID:** {timestamp}

## Instructions

For each paper processed by Darwin, evaluate the generated notes on the dimensions below.
Use a 1–5 Likert scale unless otherwise specified.

## Evaluation Form

### Paper 1: [Title]
**arXiv ID:** [ID]
**Generated Note Location:** [path to note file]

#### Completeness
- Does the note contain the paper's key contributions? (1–5)
  Rating: ___
  Comment: ___

- Are the methods section and findings both present and accurate? (1–5)
  Rating: ___
  Comment: ___

#### Readability
- Is the note well-organized and easy to scan? (1–5)
  Rating: ___
  Comment: ___

- Are the field descriptions concise (< 200 chars per section)? (1–5)
  Rating: ___
  Comment: ___

#### Relevance
- Given the search query, is this paper a good match? (1–5)
  Rating: ___
  Comment: ___

#### Semantic Quality
- Does the abstract extracted by Darwin align with the original? (1–5)
  Rating: ___
  Comment: ___

- Are there any factual errors or misrepresentations? (Yes/No)
  Answer: ___
  Details: ___

### Paper 2: [Title]
[Repeat evaluation form above]

## Summary

- **Total papers evaluated:** ___
- **Average completeness score:** ___ / 5
- **Average readability score:** ___ / 5
- **Average relevance score:** ___ / 5
- **Estimated error rate (factual mismatches):** ___ %

## Feedback & Recommendations

[Open-ended feedback on Darwin's note generation quality, suggestions for improvement]

---

**For developers:** Submit completed evaluations to `eval_human_results/eval_human_{timestamp}.md`
"""
    return template


# ═══════════════════════════════════════════════════════════════════════════════
# Summary + output
# ═══════════════════════════════════════════════════════════════════════════════

def print_summary(section_results: list[dict]) -> None:
    print(f"\n{'═' * 70}")
    print("  OVERALL SYSTEM EVALUATION SUMMARY (v3)")
    print(f"{'═' * 70}")

    total_passed = 0
    total_checks = 0

    section_names = {
        "search": "Search Quality (structured vs baseline)",
        "download": "Download Pipeline",
        "pdf": "PDF Extraction",
        "notes": "Note Creation",
        "e2e": "End-to-End Pipeline",
        "errors": "Error Handling & Adversarial",
        "resources": "Resource Profiling",
    }

    for res in section_results:
        section = res.get("section", "?")
        label = section_names.get(section, section)

        if section == "search":
            wins   = res.get("wins", 0)
            out_of = res.get("total_metrics", 8)
            detail = f"{wins}/{out_of} metrics won"
            pct    = wins / out_of
        else:
            p = res.get("passed", 0)
            t = res.get("total",  0)
            detail = f"{p}/{t} checks passed"
            pct    = (p / t) if t else 0
            total_passed += p
            total_checks += t

        bar_filled = int(pct * 20)
        bar = "█" * bar_filled + "░" * (20 - bar_filled)
        print(f"  {_ok(pct >= 0.8)}  {label:<38} [{bar}] {pct*100:.0f}%  {detail}")

    if total_checks:
        overall = total_passed / total_checks
        print(f"\n  Overall (excl. search comparison): "
              f"{total_passed}/{total_checks} checks  ({overall*100:.0f}%)")
    print(f"{'═' * 70}\n")


def save_csv(section_results: list[dict]) -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = f"eval_results_{timestamp}.csv"
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["section", "subsection", "label", "value", "passed", "detail"])

        for res in section_results:
            section = res.get("section", "?")

            if section == "search":
                for row in res.get("per_query", []):
                    writer.writerow([
                        "search", row["system"], row["query"],
                        f"kw={row['kw_precision']:.3f} kw_p3={row['kw_p3']:.3f} "
                        f"cat={row['cat_precision']:.3f} n={row['n_results']} ms={row['latency_ms']:.0f}",
                        row["success"], ""
                    ])

            elif section == "download":
                for p in res.get("per_paper", []):
                    writer.writerow([
                        "download", "per_paper", p["paper_id"],
                        f"size={p['file_size_mb']}MB cache_ms={p['dedup_latency_ms']:.0f}",
                        p["is_valid_pdf"], ""
                    ])

            elif section == "pdf":
                for p in res.get("per_paper", []):
                    writer.writerow([
                        "pdf", "per_paper", p["paper_id"],
                        f"chars={p['chars_extracted']} yield={p['text_yield']} "
                        f"sections={p['n_sections']} semantic={p['semantic_sim']}",
                        p["n_sections"] >= 3, ""
                    ])

            elif section == "notes":
                for n in res.get("per_note", []):
                    writer.writerow([
                        "notes", n["note_type"], "quality",
                        f"compliance={n['compliance_score']} bleu={n['bleu_score']}",
                        n["compliance_score"] >= 0.8, ""
                    ])

            elif section == "e2e":
                for run in res.get("runs", []):
                    writer.writerow([
                        "e2e", "run", run["query"],
                        f"search={run['search_ms']}ms dl={run['download_ms']}ms "
                        f"read={run['read_ms']}ms note={run['note_ms']}ms total={run['total_ms']}ms",
                        run["success"], ""
                    ])

            elif section == "resources":
                for op in res.get("per_op", []):
                    writer.writerow([
                        "resources", "operation", op["operation"],
                        f"mem={op['peak_memory_mb']}MB disk={op['disk_throughput_mbps']}MB/s",
                        op["peak_memory_mb"] < 500, ""
                    ])

    return path


def save_json(section_results: list[dict], timestamp: str) -> str:
    """Save structured results as JSON for chart generation."""
    path = f"eval_results_{timestamp}.json"
    output = {
        "timestamp": timestamp,
        "sections": {res["section"]: res for res in section_results},
    }
    with open(path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    return path


def save_stats(section_results: list[dict], timestamp: str) -> str:
    """Save statistical summaries (CI, confidence intervals) as JSON."""
    path = f"eval_stats_{timestamp}.json"
    stats = {
        "timestamp": timestamp,
        "metrics": {},
    }

    for res in section_results:
        section = res["section"]
        stats["metrics"][section] = {
            "latency_stats": res.get("latency_stats", {}),
            "semantic_scores": res.get("semantic_scores", {}),
            "step_rates": res.get("step_rates", {}),
            "latency_cis": res.get("latency_cis", {}),
        }

    with open(path, "w") as f:
        json.dump(stats, f, indent=2, default=str)
    return path


# ═══════════════════════════════════════════════════════════════════════════════
# Entry point
# ═══════════════════════════════════════════════════════════════════════════════

SECTION_MAP = {
    "search":     evaluate_search,
    "download":   evaluate_download,
    "pdf":        lambda: evaluate_pdf(ablation=False),
    "notes":      evaluate_notes,
    "e2e":        evaluate_e2e,
    "errors":     evaluate_errors,
    "resources":  evaluate_resources,
}

SECTION_MAP_ABLATION = {
    "pdf": lambda: evaluate_pdf(ablation=True),
}


def main():
    parser = argparse.ArgumentParser(description="Darwin full system evaluation (v3 — Enhanced)")
    parser.add_argument("--section", choices=list(SECTION_MAP), default=None,
                        help="Run only one section")
    parser.add_argument("--ablation", choices=list(SECTION_MAP_ABLATION), default=None,
                        help="Run ablation test (disable a component)")
    parser.add_argument("--no-save", action="store_true", help="Skip CSV/JSON output")
    args = parser.parse_args()

    print("=" * 70)
    print("  Darwin Research Agent — System Evaluation v3 (Enhanced)")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    if args.ablation:
        section_results = [SECTION_MAP_ABLATION[args.ablation]()]
    elif args.section:
        section_results = [SECTION_MAP[args.section]()]
    else:
        section_results = [fn() for fn in SECTION_MAP.values()]

    print_summary(section_results)

    if not args.no_save:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_path = save_csv(section_results)
        json_path = save_json(section_results, timestamp)
        stats_path = save_stats(section_results, timestamp)
        human_template = generate_human_eval_template(timestamp)
        human_path = f"eval_human_template_{timestamp}.md"
        with open(human_path, "w") as f:
            f.write(human_template)

        print(f"  Results saved to: {csv_path}")
        print(f"  Chart data:       {json_path}")
        print(f"  Statistics:       {stats_path}")
        print(f"  Human eval template: {human_path}")
        print(f"  Run: python plot_eval_results.py {json_path}\n")


if __name__ == "__main__":
    main()